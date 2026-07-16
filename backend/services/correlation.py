from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.utils.filesystem import normalize_fpath
from backend.database.models import (
    Episode,
    Movie,
    MovieVersion,
    ProtectedMedia,
    ProtectionRequest,
    Season,
    Series,
    SeriesServiceRef,
)
from backend.enums import MediaType, ProtectionRequestStatus, Service
from backend.models.correlation import (
    CorrelationDetailResponse,
    CorrelationNode,
    CorrelationResolvedFields,
    CorrelationStatus,
    CorrelationTorrentSummary,
)

_CORRELATION_NOISE_TOKENS = {
    "1080p",
    "720p",
    "2160p",
    "x264",
    "x265",
    "h264",
    "h265",
    "hevc",
    "bluray",
    "brrip",
    "webrip",
    "webdl",
    "web",
    "proper",
    "repack",
    "remux",
    "hdr",
    "dv",
    "dts",
    "aac",
    "ac3",
    "yify",
}


@dataclass
class _MovieMatch:
    score: int
    movie: Movie
    version: MovieVersion


@dataclass
class _EpisodeMatch:
    score: int
    series: Series
    season: Season
    episode: Episode


@dataclass
class CorrelatedArtwork:
    poster_url: str | None
    backdrop_url: str | None
    media_type: MediaType | None = None
    media_id: int | None = None
    reason: str | None = None


class MediaCorrelationService:
    """Provider-independent read-only media correlation service."""

    @staticmethod
    def torrent_summary_from_raw(
        item: dict[str, Any], *, index: int = 0
    ) -> CorrelationTorrentSummary:
        raw_hash = str(item.get("hash") or "").strip()
        save_path = str(item.get("save_path") or "").strip() or None
        category = str(item.get("category") or "").strip() or None
        state = str(item.get("state") or "").strip() or None
        name = str(item.get("name") or "").strip() or f"Torrent {index + 1}"

        if raw_hash:
            torrent_id = raw_hash.lower()
        else:
            seed = f"{name}|{save_path or ''}|{category or ''}|{index}"
            torrent_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()

        return CorrelationTorrentSummary(
            id=torrent_id,
            hash=raw_hash or None,
            name=name,
            category=category,
            state=state,
            save_path=save_path,
            provider=Service.QBITTORRENT.value,
        )

    @staticmethod
    def build_torrent_summaries(
        torrents_raw: list[dict[str, Any]],
    ) -> list[CorrelationTorrentSummary]:
        items = [
            MediaCorrelationService.torrent_summary_from_raw(item, index=index)
            for index, item in enumerate(torrents_raw)
            if isinstance(item, dict)
        ]
        items.sort(key=lambda row: (row.name.lower(), row.id))
        return items

    @staticmethod
    def _status_value(value: str | None) -> tuple[CorrelationStatus, str]:
        if value is None:
            return ("unknown", "Unknown")
        cleaned = value.strip()
        if not cleaned:
            return ("unknown", "Unknown")
        return ("known", cleaned)

    @staticmethod
    def _name_token(name: str) -> str:
        token = name.lower().strip()
        if token.startswith("[") and "]" in token:
            token = token.split("]", 1)[1].strip()
        token = token.replace(".", " ").replace("_", " ").replace("-", " ")
        noise = {
            "1080p",
            "720p",
            "2160p",
            "x264",
            "x265",
            "h264",
            "h265",
            "hevc",
            "bluray",
            "brrip",
            "webrip",
            "webdl",
            "proper",
            "repack",
            "remux",
            "dts",
            "aac",
            "ac3",
            "hdr",
            "dv",
        }
        parts = [p for p in token.split() if p and p not in noise and not p.isdigit()]
        return " ".join(parts[:8])[:96]

    @staticmethod
    def _normalize_identity_text(value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
        return " ".join(cleaned.split())

    @staticmethod
    def _parse_torrent_identity(name: str) -> tuple[str, int | None]:
        lowered = (name or "").lower()
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", lowered)
        year = int(year_match.group(1)) if year_match else None

        base = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", lowered)
        base = re.sub(r"\b(s\d{1,2}e\d{1,2}|season\s*\d+|episode\s*\d+)\b", " ", base)
        tokens = [
            t
            for t in re.split(r"[^a-z0-9]+", base)
            if t and t not in _CORRELATION_NOISE_TOKENS and not t.isdigit()
        ]
        return (" ".join(tokens[:8]).strip(), year)

    @staticmethod
    def _titles_compatible(parsed_title: str, candidate_title: str) -> bool:
        parsed = MediaCorrelationService._normalize_identity_text(parsed_title)
        candidate = MediaCorrelationService._normalize_identity_text(candidate_title)
        if not parsed or not candidate:
            return False
        return parsed == candidate or parsed.startswith(candidate) or candidate.startswith(parsed)

    @staticmethod
    def _movie_identity_confident(
        *,
        parsed_title: str,
        parsed_year: int | None,
        save_path: str | None,
        candidate: _MovieMatch,
    ) -> bool:
        title_match = MediaCorrelationService._titles_compatible(parsed_title, candidate.movie.title)
        year_match = parsed_year is None or candidate.movie.year is None or candidate.movie.year == parsed_year
        path_overlap = MediaCorrelationService._path_overlap_depth(save_path, candidate.version.path)
        return (title_match and year_match) or path_overlap >= 2

    @staticmethod
    def _episode_identity_confident(
        *,
        parsed_title: str,
        save_path: str | None,
        candidate: _EpisodeMatch,
    ) -> bool:
        title_match = MediaCorrelationService._titles_compatible(parsed_title, candidate.series.title)
        path_overlap = MediaCorrelationService._path_overlap_depth(save_path, candidate.episode.path)
        return title_match or path_overlap >= 2

    @staticmethod
    def _path_overlap_depth(left: str | None, right: str | None) -> int:
        if not left or not right:
            return 0
        left_parts = [p for p in normalize_fpath(left, strip_ending_slash=True, lower=True).split("/") if p]
        right_parts = [p for p in normalize_fpath(right, strip_ending_slash=True, lower=True).split("/") if p]
        depth = 0
        for l, r in zip(left_parts, right_parts):
            if l != r:
                break
            depth += 1
        return depth

    @staticmethod
    def _movie_match_score(
        *,
        version_path: str | None,
        movie_title: str,
        save_path: str | None,
        token: str,
        category: str | None,
    ) -> int:
        score = 0
        normalized_path = normalize_fpath(
            version_path or "", strip_ending_slash=True, lower=True
        )
        overlap_depth = MediaCorrelationService._path_overlap_depth(save_path, normalized_path)
        if overlap_depth >= 3:
            score += 110
        elif overlap_depth == 2:
            score += 70
        elif overlap_depth == 1:
            score += 30
        if save_path and normalized_path and normalized_path.startswith(save_path):
            score += 75
        if token and normalized_path and token in normalized_path:
            score += 45
        if token and token in movie_title.lower():
            score += 30
        if category and ("movie" in category or "radarr" in category):
            score += 10
        if category and (
            "series" in category or "sonarr" in category or "tv" in category
        ):
            score -= 5
        return score

    @staticmethod
    def _episode_match_score(
        *,
        episode_path: str | None,
        series_title: str,
        episode_name: str | None,
        save_path: str | None,
        token: str,
        category: str | None,
    ) -> int:
        score = 0
        normalized_path = normalize_fpath(
            episode_path or "", strip_ending_slash=True, lower=True
        )
        overlap_depth = MediaCorrelationService._path_overlap_depth(save_path, normalized_path)
        if overlap_depth >= 3:
            score += 110
        elif overlap_depth == 2:
            score += 70
        elif overlap_depth == 1:
            score += 30
        if save_path and normalized_path and normalized_path.startswith(save_path):
            score += 75
        if token and normalized_path and token in normalized_path:
            score += 45
        if token and token in series_title.lower():
            score += 20
        if token and episode_name and token in episode_name.lower():
            score += 20
        if category and (
            "series" in category or "sonarr" in category or "tv" in category
        ):
            score += 10
        if category and ("movie" in category or "radarr" in category):
            score -= 5
        return score

    async def _find_best_movie_match(
        self,
        db: AsyncSession,
        *,
        save_path: str | None,
        token: str,
        category: str | None,
    ) -> _MovieMatch | None:
        filters: list[Any] = []
        if save_path:
            filters.append(func.lower(MovieVersion.path).like(f"{save_path}%"))
        if token:
            filters.append(func.lower(MovieVersion.path).like(f"%{token}%"))
            filters.append(func.lower(Movie.title).like(f"%{token}%"))
        if not filters:
            return None

        rows = (
            await db.execute(
                select(MovieVersion, Movie)
                .join(Movie, MovieVersion.movie_id == Movie.id)
                .where(MovieVersion.path.is_not(None), or_(*filters))
                .limit(120)
            )
        ).all()

        best: _MovieMatch | None = None
        for version, movie in rows:
            score = self._movie_match_score(
                version_path=version.path,
                movie_title=movie.title,
                save_path=save_path,
                token=token,
                category=category,
            )
            # Require strong evidence to avoid cross-title artwork collisions.
            if score < 80:
                continue
            candidate = _MovieMatch(score=score, movie=movie, version=version)
            if best is None or candidate.score > best.score:
                best = candidate
        return best

    async def _find_best_episode_match(
        self,
        db: AsyncSession,
        *,
        save_path: str | None,
        token: str,
        category: str | None,
    ) -> _EpisodeMatch | None:
        filters: list[Any] = []
        if save_path:
            filters.append(func.lower(Episode.path).like(f"{save_path}%"))
        if token:
            filters.append(func.lower(Episode.path).like(f"%{token}%"))
            filters.append(func.lower(Series.title).like(f"%{token}%"))
            filters.append(func.lower(Episode.name).like(f"%{token}%"))
        if not filters:
            return None

        rows = (
            await db.execute(
                select(Episode, Season, Series)
                .join(Season, Episode.season_id == Season.id)
                .join(Series, Season.series_id == Series.id)
                .where(Episode.path.is_not(None), or_(*filters))
                .limit(150)
            )
        ).all()

        best: _EpisodeMatch | None = None
        for episode, season, series in rows:
            score = self._episode_match_score(
                episode_path=episode.path,
                series_title=series.title,
                episode_name=episode.name,
                save_path=save_path,
                token=token,
                category=category,
            )
            # Require strong evidence to avoid cross-title artwork collisions.
            if score < 80:
                continue
            candidate = _EpisodeMatch(
                score=score, episode=episode, season=season, series=series
            )
            if best is None or candidate.score > best.score:
                best = candidate
        return best

    async def _movie_protection_status(
        self,
        db: AsyncSession,
        movie_id: int,
        movie_version_id: int,
    ) -> str:
        now = datetime.now(UTC)
        protected_count = (
            await db.execute(
                select(func.count())
                .select_from(ProtectedMedia)
                .where(
                    ProtectedMedia.movie_id == movie_id,
                    or_(
                        ProtectedMedia.movie_version_id.is_(None),
                        ProtectedMedia.movie_version_id == movie_version_id,
                    ),
                    or_(
                        ProtectedMedia.permanent.is_(True),
                        ProtectedMedia.expires_at.is_(None),
                        ProtectedMedia.expires_at > now,
                    ),
                )
            )
        ).scalar_one()
        if protected_count > 0:
            return "Protected"

        pending_count = (
            await db.execute(
                select(func.count())
                .select_from(ProtectionRequest)
                .where(
                    ProtectionRequest.movie_id == movie_id,
                    ProtectionRequest.status == ProtectionRequestStatus.PENDING,
                    or_(
                        ProtectionRequest.movie_version_id.is_(None),
                        ProtectionRequest.movie_version_id == movie_version_id,
                    ),
                )
            )
        ).scalar_one()
        if pending_count > 0:
            return "Pending Request"
        return "Unprotected"

    async def _series_scope_protection_status(
        self,
        db: AsyncSession,
        *,
        series_id: int,
        season_id: int,
        episode_id: int,
    ) -> str:
        now = datetime.now(UTC)
        protected_count = (
            await db.execute(
                select(func.count())
                .select_from(ProtectedMedia)
                .where(
                    ProtectedMedia.series_id == series_id,
                    or_(
                        and_(
                            ProtectedMedia.season_id.is_(None),
                            ProtectedMedia.episode_id.is_(None),
                        ),
                        and_(
                            ProtectedMedia.season_id == season_id,
                            ProtectedMedia.episode_id.is_(None),
                        ),
                        ProtectedMedia.episode_id == episode_id,
                    ),
                    or_(
                        ProtectedMedia.permanent.is_(True),
                        ProtectedMedia.expires_at.is_(None),
                        ProtectedMedia.expires_at > now,
                    ),
                )
            )
        ).scalar_one()
        if protected_count > 0:
            return "Protected"

        pending_count = (
            await db.execute(
                select(func.count())
                .select_from(ProtectionRequest)
                .where(
                    ProtectionRequest.series_id == series_id,
                    ProtectionRequest.status == ProtectionRequestStatus.PENDING,
                    or_(
                        and_(
                            ProtectionRequest.season_id.is_(None),
                            ProtectionRequest.episode_id.is_(None),
                        ),
                        and_(
                            ProtectionRequest.season_id == season_id,
                            ProtectionRequest.episode_id.is_(None),
                        ),
                        ProtectionRequest.episode_id == episode_id,
                    ),
                )
            )
        ).scalar_one()
        if pending_count > 0:
            return "Pending Request"
        return "Unprotected"

    async def correlate_torrent(
        self,
        db: AsyncSession,
        torrent: CorrelationTorrentSummary,
    ) -> CorrelationDetailResponse:
        save_path = (
            normalize_fpath(
                torrent.save_path or "", strip_ending_slash=True, lower=True
            )
            or None
        )
        token = self._name_token(torrent.name)
        parsed_title, parsed_year = self._parse_torrent_identity(torrent.name)
        category = (torrent.category or "").lower() or None

        best_movie = await self._find_best_movie_match(
            db,
            save_path=save_path,
            token=token,
            category=category,
        )
        best_episode = await self._find_best_episode_match(
            db,
            save_path=save_path,
            token=token,
            category=category,
        )

        selected_mode: str | None = None
        if best_movie and best_episode:
            selected_mode = (
                "movie" if best_movie.score >= best_episode.score else "episode"
            )
        elif best_movie:
            selected_mode = "movie"
        elif best_episode:
            selected_mode = "episode"

        series_value = "Unknown"
        episode_value = "Unknown"
        movie_value = "Unknown"
        file_value = "Unknown"
        media_server_value = "Unknown"
        watch_status = "Unknown"
        protection_status = "Unknown"
        import_status = "Unknown"
        provider_value = torrent.provider

        if selected_mode == "movie" and best_movie:
            movie = best_movie.movie
            version = best_movie.version
            movie_value = (
                f"{movie.title} ({movie.year})"
                if movie.year is not None
                else movie.title
            )
            file_value = version.path or "Unknown"
            media_server_value = f"{version.service.value}:{version.service_item_id}"
            watch_status = "Watched" if (movie.view_count or 0) > 0 else "Unwatched"
            protection_status = await self._movie_protection_status(
                db,
                movie_id=movie.id,
                movie_version_id=version.id,
            )
            import_status = "Imported"
            provider_value = version.service.value

        if selected_mode == "episode" and best_episode:
            episode = best_episode.episode
            season = best_episode.season
            series = best_episode.series
            series_value = (
                f"{series.title} ({series.year})"
                if series.year is not None
                else series.title
            )
            episode_name = episode.name or "Unknown Episode"
            episode_value = f"S{season.season_number:02d}E{episode.episode_number:02d} - {episode_name}"
            file_value = episode.path or "Unknown"

            media_ref = (
                await db.execute(
                    select(SeriesServiceRef)
                    .where(SeriesServiceRef.series_id == series.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if media_ref is not None:
                media_server_value = f"{media_ref.service.value}:{media_ref.service_id}"
                provider_value = media_ref.service.value

            watch_status = "Watched" if (episode.view_count or 0) > 0 else "Unwatched"
            protection_status = await self._series_scope_protection_status(
                db,
                series_id=series.id,
                season_id=season.id,
                episode_id=episode.id,
            )
            import_status = "Imported"

        storage_value = torrent.save_path or "Unknown"

        fields = CorrelationResolvedFields(
            torrent=torrent.name,
            series=series_value,
            episode=episode_value,
            movie=movie_value,
            file=file_value,
            media_server=media_server_value,
            protection_status=protection_status,
            watch_status=watch_status,
            import_status=import_status,
            provider=provider_value,
            storage_path=storage_value,
        )

        category_status, category_value = self._status_value(torrent.category)
        file_status, file_known_value = self._status_value(
            file_value if file_value != "Unknown" else None
        )
        watch_state_status, watch_state_value = self._status_value(
            watch_status if watch_status != "Unknown" else None
        )
        protection_state_status, protection_state_value = self._status_value(
            protection_status if protection_status != "Unknown" else None
        )

        series_status, series_node_value = self._status_value(
            series_value if series_value != "Unknown" else None
        )
        episode_status, episode_node_value = self._status_value(
            episode_value if episode_value != "Unknown" else None
        )
        movie_status, movie_node_value = self._status_value(
            movie_value if movie_value != "Unknown" else None
        )
        media_server_status, media_server_node_value = self._status_value(
            media_server_value if media_server_value != "Unknown" else None
        )

        nodes = [
            CorrelationNode(
                stage="download_client",
                label="Download Client",
                status="known",
                value="qBittorrent",
                provider=Service.QBITTORRENT.value,
            ),
            CorrelationNode(
                stage="torrent",
                label="Torrent",
                status="known",
                value=torrent.name,
                provider=torrent.provider,
                path=torrent.save_path,
                metadata={"hash": torrent.hash, "state": torrent.state},
            ),
            CorrelationNode(
                stage="category",
                label="Category",
                status=category_status,
                value=category_value,
                provider=torrent.provider,
            ),
            CorrelationNode(
                stage="imported_file",
                label="Imported File",
                status=file_status,
                value=file_known_value,
                path=file_known_value if file_status == "known" else None,
            ),
            CorrelationNode(
                stage="sonarr_episode",
                label="Sonarr Episode",
                status=episode_status,
                value=episode_node_value,
                provider=Service.SONARR.value if episode_status == "known" else None,
            ),
            CorrelationNode(
                stage="sonarr_series",
                label="Sonarr Series",
                status=series_status,
                value=series_node_value,
                provider=Service.SONARR.value if series_status == "known" else None,
            ),
            CorrelationNode(
                stage="radarr_movie",
                label="Radarr Movie",
                status=movie_status,
                value=movie_node_value,
                provider=Service.RADARR.value if movie_status == "known" else None,
            ),
            CorrelationNode(
                stage="media_server_item",
                label="Media Server Item",
                status=media_server_status,
                value=media_server_node_value,
                provider=provider_value if media_server_status == "known" else None,
            ),
            CorrelationNode(
                stage="watched_state",
                label="Watched State",
                status=watch_state_status,
                value=watch_state_value,
            ),
            CorrelationNode(
                stage="cleanup_protection",
                label="Cleanup Protection",
                status=protection_state_status,
                value=protection_state_value,
            ),
        ]

        return CorrelationDetailResponse(torrent=torrent, fields=fields, nodes=nodes)

    async def resolve_torrent_artwork(
        self,
        db: AsyncSession,
        torrent: CorrelationTorrentSummary,
    ) -> CorrelatedArtwork:
        """Resolve artwork for a torrent using the same matching pipeline as correlation."""
        save_path = (
            normalize_fpath(
                torrent.save_path or "", strip_ending_slash=True, lower=True
            )
            or None
        )
        token = self._name_token(torrent.name)
        parsed_title, parsed_year = self._parse_torrent_identity(torrent.name)
        category = (torrent.category or "").lower() or None

        best_movie = await self._find_best_movie_match(
            db,
            save_path=save_path,
            token=token,
            category=category,
        )
        best_episode = await self._find_best_episode_match(
            db,
            save_path=save_path,
            token=token,
            category=category,
        )

        selected_mode: str | None = None
        if best_movie and best_episode:
            selected_mode = (
                "movie" if best_movie.score >= best_episode.score else "episode"
            )
        elif best_movie:
            selected_mode = "movie"
        elif best_episode:
            selected_mode = "episode"

        if selected_mode == "movie" and best_movie and self._movie_identity_confident(
            parsed_title=parsed_title,
            parsed_year=parsed_year,
            save_path=save_path,
            candidate=best_movie,
        ):
            return CorrelatedArtwork(
                poster_url=best_movie.movie.poster_url,
                backdrop_url=best_movie.movie.backdrop_url,
                media_type=MediaType.MOVIE,
                media_id=best_movie.movie.id,
                reason=(
                    None
                    if best_movie.movie.poster_url
                    else "movie_match_missing_poster"
                ),
            )

        if selected_mode == "episode" and best_episode and self._episode_identity_confident(
            parsed_title=parsed_title,
            save_path=save_path,
            candidate=best_episode,
        ):
            return CorrelatedArtwork(
                poster_url=best_episode.series.poster_url,
                backdrop_url=best_episode.series.backdrop_url,
                media_type=MediaType.SERIES,
                media_id=best_episode.series.id,
                reason=(
                    None
                    if best_episode.series.poster_url
                    else "series_match_missing_poster"
                ),
            )

        return CorrelatedArtwork(
            poster_url=None,
            backdrop_url=None,
            reason="no_matching_media_asset",
        )
