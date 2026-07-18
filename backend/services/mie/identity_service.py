from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.artwork import resolve_backdrop_url, resolve_poster_url
from backend.database.models import (
    MediaAsset,
    Movie,
    OperationHistory,
    QueryFilter,
    Series,
    SupplementalMediaMatch,
)
from backend.enums import MediaType
from backend.models.mie import (
    IdentityActionResponse,
    IdentityArtworkCard,
    IdentityArtworkProfileEntry,
    IdentityArtworkProviderOption,
    IdentityArtworkProviderSelectionRequest,
    IdentityCanonicalSelectionRequest,
    IdentityComparisonField,
    IdentityFieldValue,
    IdentityHistoryEntry,
    IdentityOverrideEntry,
    IdentityOverrideUpsertRequest,
    IdentityProviderComparisonRow,
    IdentityProviderMatch,
    IdentityStudioResponse,
    IdentitySyncHistoryResponse,
    IdentitySyncJobResponse,
    IdentitySyncPreviewResponse,
    IdentityWorkspaceItem,
    IdentityWorkspaceResponse,
)
from backend.services.media_asset_artwork import media_asset_artwork_resolver
from backend.services.query_engine import QueryEngineSpec, apply_spec


class IdentityCenterService:
    """Read/write service for the Identity Center workspace."""

    OVERRIDE_FIELD_OPTIONS: tuple[str, ...] = (
        "title",
        "original_title",
        "sort_title",
        "year",
        "runtime",
        "overview",
        "tagline",
        "language",
        "tmdb_id",
        "imdb_id",
        "tvdb_id",
        "canonical_provider",
        "metadata_profile",
        "artwork_profile",
        "poster_provider",
        "backdrop_provider",
    )

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _normalize_provider_key(value: str | None) -> str:
        return (value or "").strip().lower()

    @staticmethod
    def _artwork_state_for(
        *,
        has_providers: bool,
        artwork_status: str,
    ) -> Literal["present", "missing", "pending", "error"]:
        if has_providers:
            return "present"
        status_key = artwork_status.strip().lower()
        if status_key in {"needs_refresh", "stale"}:
            return "pending"
        if status_key in {"invalid"}:
            return "error"
        return "missing"

    @staticmethod
    def _provider_difference_text(
        *,
        canonical_value: str | None,
        provider_value: str | None,
        field_label: str,
    ) -> str:
        if provider_value is None:
            return f"{field_label} unavailable"
        if canonical_value is None:
            return f"{field_label} provider-specific"
        if provider_value == canonical_value:
            return f"{field_label} identical"
        if field_label.lower() in {"poster", "backdrop", "logo", "banner"}:
            return "Artwork differs"
        return f"{field_label} differs"

    @staticmethod
    def _preferred_provider(media_type: MediaType) -> str:
        return "radarr" if media_type == MediaType.MOVIE else "sonarr"

    @staticmethod
    def _conflict_level(
        provider_count: int,
        max_confidence: int,
    ) -> Literal["none", "low", "medium", "high"]:
        if provider_count <= 1:
            return "none"
        if provider_count >= 3 and max_confidence < 70:
            return "high"
        if provider_count >= 2 and max_confidence < 85:
            return "medium"
        return "low"

    @staticmethod
    def _history_summary(action: str, metadata: dict[str, Any]) -> str:
        if action == "identity_set_canonical":
            provider = metadata.get("provider") or "unknown"
            return f"Canonical provider set to {provider}."
        if action == "identity_override_upsert":
            field = metadata.get("field") or "field"
            return f"Override updated for {field}."
        if action == "identity_set_artwork_provider":
            field = metadata.get("field") or "artwork"
            provider = metadata.get("provider") or "unknown"
            return f"{str(field).title()} provider set to {provider}."
        if action == "identity_sync_run":
            return "Identity sync run requested."
        return "Identity action executed."

    @staticmethod
    def _status_from_confidence(value: int) -> str:
        if value >= 90:
            return "healthy"
        if value >= 75:
            return "review"
        return "attention"

    @staticmethod
    def _calculated_confidence(
        *,
        match_confidence: int,
        identifier_status: str,
        metadata_status: str,
        artwork_status: str,
    ) -> int:
        """Return provider confidence with health-based fallback for match gaps."""
        if match_confidence > 0:
            return max(0, min(100, match_confidence))

        identifier_score = 35 if identifier_status == "healthy" else 10
        metadata_score = 35 if metadata_status == "healthy" else 20
        artwork_score = 30 if artwork_status == "valid" else 10
        return max(0, min(100, identifier_score + metadata_score + artwork_score))

    @staticmethod
    def _normalize_artwork_value(
        *,
        field_key: str,
        value: str | None,
        media_type: MediaType,
        media_id: int,
    ) -> str | None:
        if not value:
            return None
        if field_key == "backdrop":
            return resolve_backdrop_url(value)
        return resolve_poster_url(
            value,
            context="identity_studio_provider",
            media_type=media_type.value,
            media_id=media_id,
        )

    async def _override_keys(self) -> set[tuple[MediaType, int]]:
        rows = (
            await self.db.execute(
                select(OperationHistory.target_type, OperationHistory.target_id)
                .where(
                    OperationHistory.action == "identity_override_upsert",
                    OperationHistory.result == "completed",
                )
                .distinct()
            )
        ).all()
        keys: set[tuple[MediaType, int]] = set()
        for target_type, target_id in rows:
            if not isinstance(target_id, str) or not target_id.isdigit():
                continue
            if target_type == MediaType.MOVIE.value:
                keys.add((MediaType.MOVIE, int(target_id)))
            elif target_type == MediaType.SERIES.value:
                keys.add((MediaType.SERIES, int(target_id)))
        return keys

    async def _artwork_provider_preferences(
        self,
        *,
        media_type: MediaType,
        media_id: int,
    ) -> dict[str, str]:
        rows = (
            (
                await self.db.execute(
                    select(OperationHistory)
                    .where(
                        OperationHistory.action == "identity_set_artwork_provider",
                        OperationHistory.target_type == media_type.value,
                        OperationHistory.target_id == str(media_id),
                    )
                    .order_by(OperationHistory.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        selected: dict[str, str] = {}
        for row in rows:
            metadata_json = row.metadata_json or {}
            field = metadata_json.get("field")
            provider = metadata_json.get("provider")
            if isinstance(field, str) and isinstance(provider, str):
                selected[field] = provider
        return selected

    async def _filtered_media_ids(
        self,
        *,
        media_type: MediaType,
        search: str | None,
        candidates_only: bool,
        imported_filter_ids: list[int],
        decision_filter_ids: list[int],
        smart_filter_ids: list[int],
    ) -> set[int]:
        model = Movie if media_type is MediaType.MOVIE else Series
        query = select(model.id).where(model.removed_at.is_(None))
        count_query = (
            select(func.count()).select_from(model).where(model.removed_at.is_(None))
        )
        query, _ = await apply_spec(
            self.db,
            spec=QueryEngineSpec(
                media_type=media_type,
                search=search,
                candidates_only=candidates_only,
                imported_filter_ids=imported_filter_ids,
                decision_filter_ids=decision_filter_ids,
                smart_filter_ids=smart_filter_ids,
            ),
            query=query,
            count_query=count_query,
        )
        rows = (await self.db.execute(query)).all()
        return {int(media_id) for (media_id,) in rows}

    async def _load_match_index(
        self,
        media_type: MediaType | None = None,
    ) -> dict[tuple[MediaType, int], list[SupplementalMediaMatch]]:
        stmt = select(SupplementalMediaMatch)
        if media_type is not None:
            stmt = stmt.where(SupplementalMediaMatch.media_type == media_type)
        rows = (await self.db.execute(stmt)).scalars().all()

        match_index: dict[tuple[MediaType, int], list[SupplementalMediaMatch]] = (
            defaultdict(list)
        )
        for row in rows:
            target_id = (
                row.movie_id if row.media_type == MediaType.MOVIE else row.series_id
            )
            if target_id is None:
                continue
            match_index[(row.media_type, int(target_id))].append(row)
        return match_index

    def _choose_canonical_provider(
        self,
        media_type: MediaType,
        matches: Sequence[SupplementalMediaMatch],
    ) -> str:
        preferred = self._preferred_provider(media_type)
        providers = [str(row.source_service) for row in matches]
        if preferred in providers:
            return preferred
        if not matches:
            return preferred
        best = max(matches, key=lambda row: int(row.confidence or 0))
        return str(best.source_service)

    async def workspace(
        self,
        *,
        page: int = 1,
        per_page: int = 24,
        search: str | None = None,
        media_type: MediaType | None = None,
        sort_by: str = "title",
        sort_order: str = "asc",
        candidates_only: bool = False,
        imported_filter_ids: list[int] | None = None,
        decision_filter_ids: list[int] | None = None,
        smart_filter_ids: list[int] | None = None,
        min_confidence: int | None = None,
        max_confidence: int | None = None,
        canonical_provider: str | None = None,
        sync_status: str | None = None,
        artwork_status: str | None = None,
        metadata_status: str | None = None,
        identifier_status: str | None = None,
        override_status: str | None = None,
        conflict_level: str | None = None,
        needs_review: bool | None = None,
    ) -> IdentityWorkspaceResponse:
        page = max(1, page)
        per_page = min(max(1, per_page), 100)
        search_value = (search or "").strip().lower()
        imported_ids = [int(v) for v in (imported_filter_ids or [])]
        decision_ids = [int(v) for v in (decision_filter_ids or [])]
        smart_ids = [int(v) for v in (smart_filter_ids or [])]
        allowed_movie_ids: set[int] | None = None
        allowed_series_ids: set[int] | None = None
        if imported_ids or decision_ids or smart_ids or candidates_only or search_value:
            if media_type in {None, MediaType.MOVIE}:
                allowed_movie_ids = await self._filtered_media_ids(
                    media_type=MediaType.MOVIE,
                    search=search,
                    candidates_only=candidates_only,
                    imported_filter_ids=imported_ids,
                    decision_filter_ids=decision_ids,
                    smart_filter_ids=smart_ids,
                )
            if media_type in {None, MediaType.SERIES}:
                allowed_series_ids = await self._filtered_media_ids(
                    media_type=MediaType.SERIES,
                    search=search,
                    candidates_only=candidates_only,
                    imported_filter_ids=imported_ids,
                    decision_filter_ids=decision_ids,
                    smart_filter_ids=smart_ids,
                )
        match_index = await self._load_match_index(media_type)
        override_keys = await self._override_keys()

        items: list[IdentityWorkspaceItem] = []

        if media_type in {None, MediaType.MOVIE}:
            movie_rows = (
                await self.db.execute(
                    select(Movie, MediaAsset)
                    .outerjoin(MediaAsset, MediaAsset.movie_id == Movie.id)
                    .where(Movie.removed_at.is_(None))
                )
            ).all()
            for movie, asset in movie_rows:
                if allowed_movie_ids is not None and movie.id not in allowed_movie_ids:
                    continue
                if search_value and search_value not in movie.title.lower():
                    continue
                matches = match_index.get((MediaType.MOVIE, movie.id), [])
                providers = {str(row.source_service) for row in matches}
                canonical = self._choose_canonical_provider(MediaType.MOVIE, matches)
                match_confidence = max(
                    (int(row.confidence or 0) for row in matches), default=0
                )
                provider_count = len(providers)
                movie_identifier_status = (
                    "healthy" if movie.imdb_id and movie.tmdb_id else "attention"
                )
                movie_metadata_status = (
                    "healthy"
                    if movie.overview and movie.original_language
                    else "review"
                )
                movie_artwork_status = (
                    asset.artwork_status.lower()
                    if asset and asset.artwork_status
                    else "unknown"
                )
                movie_confidence = self._calculated_confidence(
                    match_confidence=match_confidence,
                    identifier_status=movie_identifier_status,
                    metadata_status=movie_metadata_status,
                    artwork_status=movie_artwork_status,
                )
                resolved_movie_artwork = await media_asset_artwork_resolver.resolve(
                    self.db,
                    context="identity_workspace",
                    media_type=MediaType.MOVIE,
                    media_id=movie.id,
                    provider_poster_url=movie.poster_url,
                    provider_backdrop_url=movie.backdrop_url,
                    fallback_reason="identity_workspace",
                )
                movie_conflict = self._conflict_level(provider_count, movie_confidence)
                movie_needs_review = (
                    movie_conflict in {"high", "medium"}
                    or movie_confidence < 75
                    or movie_identifier_status != "healthy"
                    or movie_artwork_status
                    in {"missing", "invalid", "stale", "needs_refresh"}
                )
                items.append(
                    IdentityWorkspaceItem(
                        media_type=MediaType.MOVIE,
                        media_id=movie.id,
                        title=movie.title,
                        year=movie.year,
                        poster_url=resolved_movie_artwork.poster_url,
                        backdrop_url=resolved_movie_artwork.backdrop_url,
                        canonical_provider=canonical,
                        provider_count=provider_count,
                        provider_confidence=movie_confidence,
                        conflict_level=movie_conflict,
                        needs_review=movie_needs_review,
                        artwork_status=movie_artwork_status,
                        metadata_status=movie_metadata_status,
                        identifier_status=movie_identifier_status,
                        override_status=(
                            "manual"
                            if (MediaType.MOVIE, movie.id) in override_keys
                            else "none"
                        ),
                        last_synced_at=(asset.updated_at if asset else None),
                        status=(asset.lifecycle_state if asset else "imported"),
                    )
                )

        if media_type in {None, MediaType.SERIES}:
            series_rows = (
                await self.db.execute(
                    select(Series, MediaAsset)
                    .outerjoin(MediaAsset, MediaAsset.series_id == Series.id)
                    .where(Series.removed_at.is_(None))
                )
            ).all()
            for series, asset in series_rows:
                if (
                    allowed_series_ids is not None
                    and series.id not in allowed_series_ids
                ):
                    continue
                if search_value and search_value not in series.title.lower():
                    continue
                matches = match_index.get((MediaType.SERIES, series.id), [])
                providers = {str(row.source_service) for row in matches}
                canonical = self._choose_canonical_provider(MediaType.SERIES, matches)
                match_confidence = max(
                    (int(row.confidence or 0) for row in matches), default=0
                )
                provider_count = len(providers)
                series_identifier_status = (
                    "healthy"
                    if series.imdb_id and series.tmdb_id and series.tvdb_id
                    else "attention"
                )
                series_metadata_status = (
                    "healthy"
                    if series.overview and series.original_language
                    else "review"
                )
                series_artwork_status = (
                    asset.artwork_status.lower()
                    if asset and asset.artwork_status
                    else "unknown"
                )
                series_confidence = self._calculated_confidence(
                    match_confidence=match_confidence,
                    identifier_status=series_identifier_status,
                    metadata_status=series_metadata_status,
                    artwork_status=series_artwork_status,
                )
                resolved_series_artwork = await media_asset_artwork_resolver.resolve(
                    self.db,
                    context="identity_workspace",
                    media_type=MediaType.SERIES,
                    media_id=series.id,
                    provider_poster_url=series.poster_url,
                    provider_backdrop_url=series.backdrop_url,
                    fallback_reason="identity_workspace",
                )
                series_conflict = self._conflict_level(
                    provider_count,
                    series_confidence,
                )
                series_needs_review = (
                    series_conflict in {"high", "medium"}
                    or series_confidence < 75
                    or series_identifier_status != "healthy"
                    or series_artwork_status
                    in {"missing", "invalid", "stale", "needs_refresh"}
                )
                items.append(
                    IdentityWorkspaceItem(
                        media_type=MediaType.SERIES,
                        media_id=series.id,
                        title=series.title,
                        year=series.year,
                        poster_url=resolved_series_artwork.poster_url,
                        backdrop_url=resolved_series_artwork.backdrop_url,
                        canonical_provider=canonical,
                        provider_count=provider_count,
                        provider_confidence=series_confidence,
                        conflict_level=series_conflict,
                        needs_review=series_needs_review,
                        artwork_status=series_artwork_status,
                        metadata_status=series_metadata_status,
                        identifier_status=series_identifier_status,
                        override_status=(
                            "manual"
                            if (MediaType.SERIES, series.id) in override_keys
                            else "none"
                        ),
                        last_synced_at=(asset.updated_at if asset else None),
                        status=(asset.lifecycle_state if asset else "imported"),
                    )
                )

        if min_confidence is not None:
            items = [
                item
                for item in items
                if item.provider_confidence >= int(min_confidence)
            ]
        if max_confidence is not None:
            items = [
                item
                for item in items
                if item.provider_confidence <= int(max_confidence)
            ]
        if canonical_provider:
            provider_key = canonical_provider.strip().lower()
            items = [
                item
                for item in items
                if item.canonical_provider.strip().lower() == provider_key
            ]
        if sync_status:
            normalized_status = sync_status.strip().lower()
            items = [
                item
                for item in items
                if item.status.strip().lower() == normalized_status
            ]
        if artwork_status:
            normalized_artwork = artwork_status.strip().lower()
            items = [
                item
                for item in items
                if item.artwork_status.strip().lower() == normalized_artwork
            ]
        if metadata_status:
            normalized_metadata = metadata_status.strip().lower()
            items = [
                item
                for item in items
                if item.metadata_status.strip().lower() == normalized_metadata
            ]
        if identifier_status:
            normalized_identifier = identifier_status.strip().lower()
            items = [
                item
                for item in items
                if item.identifier_status.strip().lower() == normalized_identifier
            ]
        if override_status:
            normalized_override = override_status.strip().lower()
            items = [
                item
                for item in items
                if item.override_status.strip().lower() == normalized_override
            ]
        if conflict_level:
            normalized_conflict = conflict_level.strip().lower()
            items = [
                item
                for item in items
                if item.conflict_level.strip().lower() == normalized_conflict
            ]
        if needs_review is not None:
            items = [item for item in items if bool(item.needs_review) is needs_review]

        reverse = sort_order.lower() == "desc"
        if sort_by == "updated":
            items.sort(
                key=lambda row: row.last_synced_at or datetime.fromtimestamp(0, tz=UTC),
                reverse=reverse,
            )
        elif sort_by == "confidence":
            items.sort(key=lambda row: row.provider_confidence, reverse=reverse)
        else:
            items.sort(key=lambda row: (row.title or "").lower(), reverse=reverse)

        total = len(items)
        total_pages = max(1, (total + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page

        return IdentityWorkspaceResponse(
            items=items[start:end],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            generated_at=datetime.now(UTC),
        )

    async def _fetch_target(
        self,
        media_type: MediaType,
        media_id: int,
    ) -> tuple[Movie | Series, MediaAsset | None]:
        if media_type == MediaType.MOVIE:
            movie_row = (
                await self.db.execute(
                    select(Movie, MediaAsset)
                    .outerjoin(MediaAsset, MediaAsset.movie_id == Movie.id)
                    .where(Movie.id == media_id, Movie.removed_at.is_(None))
                )
            ).one_or_none()
            if movie_row is None:
                raise ValueError("Media item not found")
            movie, asset = movie_row
            return movie, asset
        else:
            series_row = (
                await self.db.execute(
                    select(Series, MediaAsset)
                    .outerjoin(MediaAsset, MediaAsset.series_id == Series.id)
                    .where(Series.id == media_id, Series.removed_at.is_(None))
                )
            ).one_or_none()
            if series_row is None:
                raise ValueError("Media item not found")
            series, asset = series_row
            return series, asset

    async def studio(
        self, *, media_type: MediaType, media_id: int
    ) -> IdentityStudioResponse:
        target, asset = await self._fetch_target(media_type, media_id)

        resolved_canonical_artwork = await media_asset_artwork_resolver.resolve(
            self.db,
            context="identity_studio",
            media_type=media_type,
            media_id=media_id,
            provider_poster_url=getattr(target, "poster_url", None),
            provider_backdrop_url=getattr(target, "backdrop_url", None),
            fallback_reason="identity_studio",
        )

        canonical_poster = resolved_canonical_artwork.poster_url
        canonical_backdrop = resolved_canonical_artwork.backdrop_url
        canonical_logo = self._normalize_artwork_value(
            field_key="logo",
            value=asset.logo_url if asset else None,
            media_type=media_type,
            media_id=media_id,
        )
        canonical_banner = self._normalize_artwork_value(
            field_key="banner",
            value=asset.banner_url if asset else None,
            media_type=media_type,
            media_id=media_id,
        )

        match_rows = (
            (
                await self.db.execute(
                    select(SupplementalMediaMatch).where(
                        SupplementalMediaMatch.media_type == media_type,
                        or_(
                            SupplementalMediaMatch.movie_id == media_id,
                            SupplementalMediaMatch.series_id == media_id,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )

        canonical_provider = self._choose_canonical_provider(media_type, match_rows)
        provider_matches: list[IdentityProviderMatch] = []
        for match_row in sorted(
            match_rows,
            key=lambda item: int(item.confidence or 0),
            reverse=True,
        ):
            match_signals = match_row.signals or {}
            preview_candidate = cast(
                str | None, match_signals.get("poster_url")
            ) or cast(str | None, match_signals.get("artwork_poster"))
            preview: str | None = (
                self._normalize_artwork_value(
                    field_key="poster",
                    value=preview_candidate,
                    media_type=media_type,
                    media_id=media_id,
                )
                or canonical_poster
            )
            preview = preview if isinstance(preview, str) and preview.strip() else None
            provider_matches.append(
                IdentityProviderMatch(
                    provider=str(match_row.source_service),
                    provider_item_id=match_row.source_item_id,
                    confidence=int(match_row.confidence or 0),
                    path_tail=match_row.path_tail,
                    artwork_preview_url=preview,
                    metadata_quality=self._status_from_confidence(
                        int(match_row.confidence or 0)
                    ),
                    external_ids_count=int(
                        match_signals.get("external_ids_count") or 0
                    ),
                    collection_count=int(match_signals.get("collection_count") or 0),
                    connection_status=str(
                        match_signals.get("connection_status") or "connected"
                    ),
                    signals=match_signals,
                    updated_at=match_row.updated_at,
                    is_canonical=str(match_row.source_service) == canonical_provider,
                )
            )

        artwork_preferences = await self._artwork_provider_preferences(
            media_type=media_type,
            media_id=media_id,
        )

        metadata_values = {
            "title": target.title,
            "original_title": getattr(target, "original_title", None),
            "sort_title": getattr(target, "sort_title", None),
            "year": str(getattr(target, "year", "") or "") or None,
            "runtime": (str(getattr(target, "runtime", "") or "") or None),
            "language": getattr(target, "original_language", None),
            "status": getattr(target, "status", None),
            "tagline": getattr(target, "tagline", None),
            "overview": getattr(target, "overview", None),
        }

        external_values = {
            "tmdb_id": str(getattr(target, "tmdb_id", "") or "") or None,
            "imdb_id": getattr(target, "imdb_id", None),
            "tvdb_id": getattr(target, "tvdb_id", None),
            "anilist_id": str(getattr(target, "anilist_id", "") or "") or None,
        }

        overview: list[IdentityComparisonField] = [
            IdentityComparisonField(
                key="canonical_provider",
                label="Canonical Provider",
                values=[
                    IdentityFieldValue(
                        provider="canonical",
                        value=canonical_provider,
                        confidence=100,
                        is_canonical=True,
                    )
                ],
            ),
            IdentityComparisonField(
                key="provider_count",
                label="Provider Matches",
                values=[
                    IdentityFieldValue(
                        provider="calculated",
                        value=str(len(provider_matches)),
                        confidence=100,
                        is_canonical=True,
                    )
                ],
            ),
        ]

        metadata: list[IdentityComparisonField] = []
        for key, value in metadata_values.items():
            field_values: list[IdentityFieldValue] = [
                IdentityFieldValue(
                    provider="current",
                    value=value,
                    confidence=100,
                    is_canonical=True,
                )
            ]
            for provider in provider_matches:
                candidate = provider.signals.get(key)
                if candidate is None:
                    candidate = provider.signals.get(f"metadata_{key}")
                field_values.append(
                    IdentityFieldValue(
                        provider=provider.provider,
                        value=(str(candidate) if candidate is not None else None),
                        confidence=provider.confidence,
                        is_canonical=provider.provider == canonical_provider,
                    )
                )
            metadata.append(
                IdentityComparisonField(
                    key=key,
                    label=key.replace("_", " ").title(),
                    values=field_values,
                )
            )

        external_ids: list[IdentityComparisonField] = []
        for key, value in external_values.items():
            external_field_values: list[IdentityFieldValue] = [
                IdentityFieldValue(
                    provider="current",
                    value=value,
                    confidence=100,
                    is_canonical=True,
                )
            ]
            for provider in provider_matches:
                candidate = provider.signals.get(key)
                if candidate is None:
                    candidate = provider.signals.get(f"identifier_{key}")
                external_field_values.append(
                    IdentityFieldValue(
                        provider=provider.provider,
                        value=(str(candidate) if candidate is not None else None),
                        confidence=provider.confidence,
                        is_canonical=provider.provider == canonical_provider,
                    )
                )
            external_ids.append(
                IdentityComparisonField(
                    key=key,
                    label=key.replace("_", " ").upper(),
                    values=external_field_values,
                )
            )

        artwork_fields: list[tuple[str, str, str | None]] = [
            ("poster", "Poster", canonical_poster),
            ("backdrop", "Backdrop", canonical_backdrop),
            ("logo", "Logo", canonical_logo),
            ("banner", "Banner", canonical_banner),
        ]

        artwork: list[IdentityComparisonField] = []
        artwork_cards: list[IdentityArtworkCard] = []
        canonical_artwork_profile: list[IdentityArtworkProfileEntry] = []
        for field_key, field_label, canonical_value in artwork_fields:
            values: list[IdentityFieldValue] = [
                IdentityFieldValue(
                    provider="current",
                    value=canonical_value,
                    confidence=int(asset.artwork_confidence * 100) if asset else 100,
                    is_canonical=True,
                )
            ]

            provider_options: list[IdentityArtworkProviderOption] = []
            optional_type = field_key in {"logo", "banner"}
            for provider in provider_matches:
                candidate = provider.signals.get(f"{field_key}_url")
                if candidate is None:
                    candidate = provider.signals.get(f"artwork_{field_key}")
                if not isinstance(candidate, str) or not candidate.strip():
                    continue
                normalized_candidate = self._normalize_artwork_value(
                    field_key=field_key,
                    value=candidate,
                    media_type=media_type,
                    media_id=media_id,
                )
                if normalized_candidate is None:
                    continue
                values.append(
                    IdentityFieldValue(
                        provider=provider.provider,
                        value=normalized_candidate,
                        confidence=provider.confidence,
                        is_canonical=(
                            provider.provider
                            == artwork_preferences.get(field_key, canonical_provider)
                        ),
                    )
                )
                width = provider.signals.get(f"{field_key}_width")
                height = provider.signals.get(f"{field_key}_height")
                resolution = (
                    f"{width}x{height}"
                    if isinstance(width, (int, str)) and isinstance(height, (int, str))
                    else None
                )
                provider_options.append(
                    IdentityArtworkProviderOption(
                        provider=provider.provider,
                        image_url=normalized_candidate,
                        resolution=resolution,
                        last_updated=provider.updated_at,
                        confidence=provider.confidence,
                        selected=(
                            provider.provider
                            == artwork_preferences.get(field_key, canonical_provider)
                        ),
                    )
                )

            if optional_type and len(provider_options) == 0:
                canonical_artwork_profile.append(
                    IdentityArtworkProfileEntry(
                        key=field_key,
                        label=field_label,
                        provider=None,
                    )
                )
                continue

            selected_provider: str | None = artwork_preferences.get(
                field_key,
                canonical_provider,
            )
            if selected_provider and not any(
                option.provider == selected_provider for option in provider_options
            ):
                selected_provider = None

            shared_across = False
            if len(provider_options) > 1:
                shared_across = (
                    len({option.image_url for option in provider_options}) == 1
                )

            for option in provider_options:
                option.selected = option.provider == selected_provider

            artwork_state = self._artwork_state_for(
                has_providers=len(provider_options) > 0,
                artwork_status=(asset.artwork_status if asset else "unknown")
                or "unknown",
            )
            missing_message = (
                f"No {field_label} Available"
                if artwork_state == "missing"
                else (
                    f"{field_label} sync pending"
                    if artwork_state == "pending"
                    else f"{field_label} retrieval error"
                )
            )
            artwork_cards.append(
                IdentityArtworkCard(
                    key=field_key,
                    label=field_label,
                    state=artwork_state,
                    selected_provider=selected_provider,
                    shared_across_providers=shared_across,
                    providers=(
                        provider_options[:1] if shared_across else provider_options
                    ),
                    message=(None if artwork_state == "present" else missing_message),
                )
            )
            canonical_artwork_profile.append(
                IdentityArtworkProfileEntry(
                    key=field_key,
                    label=field_label,
                    provider=selected_provider,
                )
            )
            artwork.append(
                IdentityComparisonField(
                    key=field_key,
                    label=field_label,
                    values=values,
                )
            )

        provider_comparison: list[IdentityProviderComparisonRow] = []
        for provider in provider_matches:
            poster_diff = self._provider_difference_text(
                canonical_value=canonical_poster,
                provider_value=(
                    cast(str | None, provider.signals.get("poster_url"))
                    or cast(str | None, provider.signals.get("artwork_poster"))
                ),
                field_label="Poster",
            )
            backdrop_diff = self._provider_difference_text(
                canonical_value=canonical_backdrop,
                provider_value=(
                    cast(str | None, provider.signals.get("backdrop_url"))
                    or cast(str | None, provider.signals.get("artwork_backdrop"))
                ),
                field_label="Backdrop",
            )

            metadata_has_diff = any(
                (value.provider == provider.provider)
                and ((value.value or "") != (row.values[0].value or ""))
                for row in metadata
                for value in row.values[1:]
            )
            external_has_diff = any(
                (value.provider == provider.provider)
                and ((value.value or "") != (row.values[0].value or ""))
                for row in external_ids
                for value in row.values[1:]
            )

            differences = [poster_diff, backdrop_diff]
            if metadata_has_diff:
                differences.append("Metadata differs")
            if external_has_diff:
                differences.append("Identifiers differ")

            provider_comparison.append(
                IdentityProviderComparisonRow(
                    provider=provider.provider,
                    connection_status=provider.connection_status,
                    matched=True,
                    identifiers=(
                        "IDs differ" if external_has_diff else "IDs identical"
                    ),
                    metadata=(
                        "Metadata differs"
                        if metadata_has_diff
                        else "Metadata identical"
                    ),
                    artwork=(
                        "Poster selected"
                        if provider.provider
                        == artwork_preferences.get("poster", canonical_provider)
                        else "Poster differs"
                    ),
                    health=(
                        "Healthy"
                        if provider.confidence >= 90
                        else "Review"
                        if provider.confidence >= 75
                        else "Attention"
                    ),
                    differences=differences,
                )
            )

        history_rows = (
            (
                await self.db.execute(
                    select(OperationHistory)
                    .where(
                        OperationHistory.action.like("identity_%"),
                        OperationHistory.target_type == media_type.value,
                        OperationHistory.target_id == str(media_id),
                    )
                    .order_by(OperationHistory.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )

        overrides: list[IdentityOverrideEntry] = []
        history: list[IdentityHistoryEntry] = []
        for history_row in history_rows:
            metadata_json = history_row.metadata_json or {}
            if history_row.action == "identity_override_upsert":
                value = metadata_json.get("value")
                field = metadata_json.get("field")
                if isinstance(value, str) and isinstance(field, str):
                    scope_value = (
                        cast(Literal["media", "global"], metadata_json["scope"])
                        if metadata_json.get("scope") in {"media", "global"}
                        else "media"
                    )
                    overrides.append(
                        IdentityOverrideEntry(
                            field=field,
                            value=value,
                            scope=scope_value,
                            reason=(
                                metadata_json.get("reason")
                                if isinstance(metadata_json.get("reason"), str)
                                else None
                            ),
                            created_at=history_row.created_at,
                            created_by_user_id=history_row.created_by_user_id,
                        )
                    )

            history.append(
                IdentityHistoryEntry(
                    id=history_row.id,
                    action=history_row.action,
                    result=history_row.result,
                    summary=self._history_summary(history_row.action, metadata_json),
                    created_at=history_row.created_at,
                )
            )

        title = target.title
        year = getattr(target, "year", None)

        return IdentityStudioResponse(
            media_type=media_type,
            media_id=media_id,
            title=title,
            year=year,
            canonical_provider=canonical_provider,
            overview=overview,
            providers=provider_matches,
            artwork=artwork,
            artwork_cards=artwork_cards,
            canonical_artwork_profile=canonical_artwork_profile,
            provider_comparison=provider_comparison,
            metadata=metadata,
            external_ids=external_ids,
            overrides=overrides,
            history=history,
            synchronization=[
                IdentityComparisonField(
                    key="sync_preview",
                    label="Synchronization Preview",
                    values=[
                        IdentityFieldValue(
                            provider="current",
                            value="Current values will be compared against provider values before apply.",
                            confidence=100,
                            is_canonical=True,
                        )
                    ],
                )
            ],
            diagnostics=[
                IdentityComparisonField(
                    key="identity_conflict",
                    label="Conflict Level",
                    values=[
                        IdentityFieldValue(
                            provider="calculated",
                            value=self._conflict_level(
                                max(1, len(provider_matches)),
                                max(
                                    (
                                        provider.confidence
                                        for provider in provider_matches
                                    ),
                                    default=0,
                                ),
                            ),
                            confidence=100,
                            is_canonical=True,
                        )
                    ],
                )
            ],
            override_field_options=list(self.OVERRIDE_FIELD_OPTIONS),
            generated_at=datetime.now(UTC),
        )

    async def identity_health_summary(self) -> dict[str, int | float]:
        assets = (await self.db.execute(select(MediaAsset))).scalars().all()
        total_assets = len(assets)
        valid_statuses = {"valid"}
        missing_statuses = {"missing", "invalid", "placeholder"}

        healthy_count = 0
        missing_count = 0
        review_count = 0
        for asset in assets:
            status = (asset.artwork_status or "").strip().lower()
            confidence = float(asset.artwork_confidence or 0.0)
            if status in valid_statuses and confidence >= 0.85:
                healthy_count += 1
                continue
            if status in missing_statuses:
                missing_count += 1
            else:
                review_count += 1

        coverage_percent = (
            (healthy_count / total_assets) * 100 if total_assets > 0 else 0.0
        )
        return {
            "total_assets": total_assets,
            "healthy_count": healthy_count,
            "missing_count": missing_count,
            "review_count": review_count,
            "coverage_percent": coverage_percent,
        }

    async def set_canonical_provider(
        self,
        *,
        media_type: MediaType,
        media_id: int,
        payload: IdentityCanonicalSelectionRequest,
        user_id: int | None,
    ) -> IdentityActionResponse:
        await self._fetch_target(media_type, media_id)

        self.db.add(
            OperationHistory(
                action="identity_set_canonical",
                target_type=media_type.value,
                target_id=str(media_id),
                result="completed",
                safety_level="safe",
                metadata_json={"provider": payload.provider, "reason": payload.reason},
                created_by_user_id=user_id,
            )
        )
        await self.db.commit()

        return IdentityActionResponse(
            accepted=True,
            action="set_canonical",
            message=f"Canonical provider set to {payload.provider}.",
        )

    async def set_artwork_provider(
        self,
        *,
        media_type: MediaType,
        media_id: int,
        payload: IdentityArtworkProviderSelectionRequest,
        user_id: int | None,
    ) -> IdentityActionResponse:
        await self._fetch_target(media_type, media_id)

        self.db.add(
            OperationHistory(
                action="identity_set_artwork_provider",
                target_type=media_type.value,
                target_id=str(media_id),
                result="completed",
                safety_level="safe",
                metadata_json={
                    "field": payload.artwork_field,
                    "provider": payload.provider,
                    "reason": payload.reason,
                },
                created_by_user_id=user_id,
            )
        )
        # Queue a sync event immediately so workflow changes are visible in sync history.
        self.db.add(
            OperationHistory(
                action="identity_sync_run",
                target_type="identity",
                target_id="all",
                result="queued",
                safety_level="safe",
                metadata_json={
                    "trigger": "artwork_provider_change",
                    "field": payload.artwork_field,
                    "provider": payload.provider,
                    "requested_at": datetime.now(UTC).isoformat(),
                },
                created_by_user_id=user_id,
            )
        )
        await self.db.commit()

        return IdentityActionResponse(
            accepted=True,
            action="set_artwork_provider",
            message=(
                f"{payload.artwork_field.title()} provider set to "
                f"{payload.provider}. Sync queued."
            ),
        )

    async def upsert_override(
        self,
        *,
        media_type: MediaType,
        media_id: int,
        payload: IdentityOverrideUpsertRequest,
        user_id: int | None,
    ) -> IdentityActionResponse:
        await self._fetch_target(media_type, media_id)

        if payload.field not in self.OVERRIDE_FIELD_OPTIONS:
            return IdentityActionResponse(
                accepted=False,
                action="upsert_override",
                message=(
                    f"Invalid override field '{payload.field}'."
                    " Select a supported override target."
                ),
            )

        self.db.add(
            OperationHistory(
                action="identity_override_upsert",
                target_type=media_type.value,
                target_id=str(media_id),
                result="completed",
                safety_level="safe",
                metadata_json={
                    "field": payload.field,
                    "value": payload.value,
                    "scope": payload.scope,
                    "reason": payload.reason,
                },
                created_by_user_id=user_id,
            )
        )
        await self.db.commit()

        return IdentityActionResponse(
            accepted=True,
            action="upsert_override",
            message=f"Override for {payload.field} saved.",
        )

    async def sync_preview(self) -> IdentitySyncPreviewResponse:
        assets = (await self.db.execute(select(MediaAsset))).scalars().all()
        total = len(assets)
        low_confidence = sum(
            1 for asset in assets if float(asset.artwork_confidence or 0.0) < 0.7
        )
        missing_artwork = sum(
            1
            for asset in assets
            if (asset.artwork_status or "").upper() in {"MISSING", "INVALID"}
        )

        warnings: list[str] = []
        if low_confidence > 0:
            warnings.append(f"{low_confidence} assets have low artwork confidence.")
        if missing_artwork > 0:
            warnings.append(f"{missing_artwork} assets are missing valid artwork.")

        details = [
            "Preview computes canonical identity candidates and metadata deltas.",
            "No destructive changes are applied during preview.",
        ]

        return IdentitySyncPreviewResponse(
            target_count=total,
            changed_count=low_confidence + missing_artwork,
            warnings=warnings,
            details=details,
        )

    async def start_sync(self, *, user_id: int | None) -> IdentitySyncJobResponse:
        history_row = OperationHistory(
            action="identity_sync_run",
            target_type="identity",
            target_id="all",
            result="queued",
            safety_level="safe",
            metadata_json={"requested_at": datetime.now(UTC).isoformat()},
            created_by_user_id=user_id,
        )
        self.db.add(history_row)
        await self.db.flush()
        operation_id = history_row.id
        await self.db.commit()

        return IdentitySyncJobResponse(
            accepted=True,
            status="queued",
            message="Identity sync job queued.",
            operation_history_id=operation_id,
        )

    async def sync_history(self, *, limit: int = 50) -> IdentitySyncHistoryResponse:
        bounded_limit = max(1, min(limit, 200))
        history_rows = (
            (
                await self.db.execute(
                    select(OperationHistory)
                    .where(OperationHistory.action.like("identity_%"))
                    .order_by(OperationHistory.created_at.desc())
                    .limit(bounded_limit)
                )
            )
            .scalars()
            .all()
        )

        return IdentitySyncHistoryResponse(
            items=[
                IdentityHistoryEntry(
                    id=row.id,
                    action=row.action,
                    result=row.result,
                    summary=self._history_summary(row.action, row.metadata_json or {}),
                    created_at=row.created_at,
                )
                for row in history_rows
            ]
        )
