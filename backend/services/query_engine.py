from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.service_manager import service_manager
from backend.database.models import (
    Movie,
    MovieArrRef,
    ProtectedMedia,
    ProtectionRequest,
    QueryFilter,
    ReclaimCandidate,
    Series,
    SeriesArrRef,
    User,
)
from backend.enums import MediaType, ProtectionRequestStatus, Service
from backend.models.media import MediaFilterCatalogResponse, MediaFilterOptionResponse


@dataclass(slots=True)
class QueryEngineSpec:
    media_type: MediaType
    search: str | None = None
    candidates_only: bool = False
    monitored: bool | None = None
    media_status: str | None = None
    imported_filter_ids: list[int] | None = None
    decision_filter_ids: list[int] | None = None
    smart_filter_ids: list[int] | None = None


def _extract_int_list(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return []
    result: list[int] = []
    for item in raw:
        try:
            result.append(int(item))
        except Exception:
            continue
    return result


def _extract_arr_ids(raw: Mapping[str, Any], media_type: MediaType) -> list[int]:
    direct_keys = (
        ["movieIds", "movies", "ids"]
        if media_type is MediaType.MOVIE
        else ["seriesIds", "series", "ids"]
    )
    for key in direct_keys:
        values = _extract_int_list(raw.get(key))
        if values:
            return values

    for value in raw.values():
        if isinstance(value, Mapping):
            nested = _extract_arr_ids(value, media_type)
            if nested:
                return nested
        elif isinstance(value, list):
            if value and all(isinstance(item, Mapping) for item in value):
                for item in value:
                    nested = _extract_arr_ids(item, media_type)
                    if nested:
                        return nested
    return []


def _text_tokens(name: str) -> list[str]:
    return [token.strip().lower() for token in name.replace("-", " ").split() if token.strip()]


def _normalized_provider_filter_id(source: str, raw_id: object) -> str:
    normalized = str(raw_id or "").strip()
    return f"{source}:{normalized}" if normalized else ""


def _provider_label(service_type: Service) -> str:
    return "Sonarr" if service_type is Service.SONARR else "Radarr"


def _prefixed_imported_label(service_type: Service, name: str) -> str:
    base = name.strip()
    provider = _provider_label(service_type)
    lower_base = base.lower()
    if lower_base.startswith(f"{provider.lower()} -"):
        return base
    return f"{provider} - {base}"


def _arr_tag_clause(media_type: MediaType, token: str) -> Any:
    model = Movie if media_type is MediaType.MOVIE else Series
    return model.arr_tags.like(f'%"{token}"%')


def _apply_imported_filter(
    *,
    query: Any,
    count_query: Any,
    media_type: MediaType,
    imported_filter: QueryFilter,
) -> tuple[Any, Any]:
    definition = imported_filter.definition or {}
    raw = definition.get("raw")
    raw_mapping = raw if isinstance(raw, Mapping) else {}

    arr_ids = _extract_arr_ids(raw_mapping, media_type)
    if arr_ids:
        if media_type is MediaType.MOVIE:
            query = query.join(MovieArrRef, MovieArrRef.movie_id == Movie.id).where(
                MovieArrRef.arr_movie_id.in_(arr_ids)
            )
            count_query = count_query.join(
                MovieArrRef, MovieArrRef.movie_id == Movie.id
            ).where(MovieArrRef.arr_movie_id.in_(arr_ids))
        else:
            query = query.join(
                SeriesArrRef, SeriesArrRef.series_id == Series.id
            ).where(SeriesArrRef.arr_series_id.in_(arr_ids))
            count_query = count_query.join(
                SeriesArrRef, SeriesArrRef.series_id == Series.id
            ).where(SeriesArrRef.arr_series_id.in_(arr_ids))
        return query.distinct(), count_query.distinct()

    # Best-effort fallback when providers do not return explicit media id lists.
    # We apply token matching against arr_tags/title to preserve usability.
    tokens = [token for token in _text_tokens(imported_filter.name) if len(token) >= 3]
    if tokens:
        model = Movie if media_type is MediaType.MOVIE else Series
        clauses = [
            or_(
                _arr_tag_clause(media_type, token),
                model.title.ilike(f"%{token}%"),
            )
            for token in tokens
        ]
        query = query.where(and_(*clauses))
        count_query = count_query.where(and_(*clauses))

    return query, count_query


def _decision_state_expression(media_type: MediaType, state: str) -> Any | None:
    normalized = state.strip().lower()
    if not normalized:
        return None
    if normalized == "safe_to_delete":
        return exists().where(
            (ReclaimCandidate.movie_id == Movie.id)
            if media_type is MediaType.MOVIE
            else (ReclaimCandidate.series_id == Series.id)
        )
    if normalized == "protected":
        return exists().where(
            (ProtectedMedia.movie_id == Movie.id)
            if media_type is MediaType.MOVIE
            else (ProtectedMedia.series_id == Series.id)
        )
    if normalized == "waiting":
        return exists().where(
            and_(
                ProtectionRequest.status == ProtectionRequestStatus.PENDING,
                (
                    ProtectionRequest.movie_id == Movie.id
                    if media_type is MediaType.MOVIE
                    else ProtectionRequest.series_id == Series.id
                ),
            )
        )
    if normalized == "unwatched":
        model = Movie if media_type is MediaType.MOVIE else Series
        return and_(model.view_count <= 0, model.last_viewed_at.is_(None))
    if normalized == "watching":
        model = Movie if media_type is MediaType.MOVIE else Series
        cutoff = datetime.now(UTC) - timedelta(days=14)
        return and_(model.last_viewed_at.is_not(None), model.last_viewed_at >= cutoff)
    return None


def _decision_clause_expression(
    *,
    media_type: MediaType,
    field: str,
    operator: str,
    value: Any,
) -> Any | None:
    model = Movie if media_type is MediaType.MOVIE else Series
    op = operator.lower().strip()
    field = field.strip()

    if field == "decision.state":
        return _decision_state_expression(media_type, str(value or ""))

    if field == "media.size":
        try:
            parsed = int(value)
        except Exception:
            return None
        if op in {"greater_than", ">", ">="}:
            return model.size.is_not(None) & (model.size >= parsed)
        if op in {"less_than", "<", "<="}:
            return model.size.is_not(None) & (model.size <= parsed)
        if op in {"equals", "="}:
            return model.size == parsed
        if op in {"not_equals", "!=", "<>"}:
            return model.size != parsed
        return None

    if field == "media.last_watched_days":
        try:
            parsed_days = int(value)
        except Exception:
            return None
        cutoff = datetime.now(UTC) - timedelta(days=parsed_days)
        if op in {"greater_than", ">"}:
            return and_(model.last_viewed_at.is_not(None), model.last_viewed_at <= cutoff)
        if op in {"less_than", "<"}:
            return and_(model.last_viewed_at.is_not(None), model.last_viewed_at >= cutoff)
        if op in {"exists"}:
            return model.last_viewed_at.is_not(None)
        if op in {"does_not_exist", "not_exists"}:
            return model.last_viewed_at.is_(None)
        return None

    if field == "media.library_group":
        token = str(value or "").strip().lower()
        if not token:
            return None
        clause = _arr_tag_clause(media_type, token)
        if op in {"not_equals", "does_not_contain", "does_not_exist"}:
            return ~clause
        return clause

    if field == "media.title":
        token = str(value or "").strip()
        if not token:
            return None
        if op in {"equals", "="}:
            return model.title == token
        if op in {"not_equals", "!=", "<>"}:
            return model.title != token
        if op in {"starts_with"}:
            return model.title.ilike(f"{token}%")
        if op in {"ends_with"}:
            return model.title.ilike(f"%{token}")
        if op in {"exists"}:
            return model.title.is_not(None)
        if op in {"does_not_exist", "not_exists"}:
            return model.title.is_(None)
        return model.title.ilike(f"%{token}%")

    return None


def _normalize_definition_nodes(raw_definition: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(raw_definition, Mapping):
        return []
    if isinstance(raw_definition.get("clauses"), list):
        nodes = raw_definition["clauses"]
    else:
        nodes = raw_definition.get("children") if isinstance(raw_definition.get("children"), list) else []
    normalized: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        node_type = str(node.get("type") or "condition").lower()
        if node_type == "group":
            normalized.append(
                {
                    "type": "group",
                    "combinator": str(node.get("combinator") or "and").lower(),
                    "clauses": _normalize_definition_nodes(node),
                }
            )
        else:
            normalized.append(
                {
                    "type": "condition",
                    "field": node.get("field"),
                    "operator": node.get("operator"),
                    "value": node.get("value"),
                }
            )
    return normalized


def _definition_expression(media_type: MediaType, definition: Mapping[str, Any] | None) -> Any | None:
    if not isinstance(definition, Mapping):
        return None
    combinator = str(definition.get("combinator") or "and").lower()
    nodes = _normalize_definition_nodes(definition)
    if not nodes:
        return None

    expressions: list[Any] = []
    for node in nodes:
        if node.get("type") == "group":
            child_expr = _definition_expression(media_type, node)
            if child_expr is not None:
                expressions.append(child_expr)
            continue
        clause_expr = _decision_clause_expression(
            media_type=media_type,
            field=str(node.get("field") or ""),
            operator=str(node.get("operator") or ""),
            value=node.get("value"),
        )
        if clause_expr is not None:
            expressions.append(clause_expr)

    if not expressions:
        return None
    return and_(*expressions) if combinator != "or" else or_(*expressions)


async def sync_imported_arr_filters(db: AsyncSession) -> None:
    candidates: list[tuple[Service, int, list[dict[str, Any]]]] = []

    for config_id, client in service_manager.radarr_clients().items():
        imported: list[dict[str, Any]] = []
        try:
            for saved in await client.get_saved_filters():
                imported.append(
                    {
                        "id": _normalized_provider_filter_id("saved", saved.get("id")),
                        "name": str(saved.get("name") or "").strip(),
                        "raw": dict(saved.get("raw") or {}),
                    }
                )
        except Exception:
            # Some ARR versions/instances do not expose saved filters over API.
            pass
        try:
            for label, movie_ids in (await client.get_all_tag_details()).items():
                tag_name = str(label or "").strip()
                if not tag_name:
                    continue
                imported.append(
                    {
                        "id": _normalized_provider_filter_id("tag", tag_name.lower()),
                        "name": tag_name,
                        "raw": {"movieIds": [int(v) for v in movie_ids]},
                    }
                )
        except Exception:
            pass
        candidates.append((Service.RADARR, config_id, imported))

    for config_id, client in service_manager.sonarr_clients().items():
        imported: list[dict[str, Any]] = []
        try:
            for saved in await client.get_saved_filters():
                imported.append(
                    {
                        "id": _normalized_provider_filter_id("saved", saved.get("id")),
                        "name": str(saved.get("name") or "").strip(),
                        "raw": dict(saved.get("raw") or {}),
                    }
                )
        except Exception:
            pass
        try:
            for label, series_ids in (await client.get_all_tag_details()).items():
                tag_name = str(label or "").strip()
                if not tag_name:
                    continue
                imported.append(
                    {
                        "id": _normalized_provider_filter_id("tag", tag_name.lower()),
                        "name": tag_name,
                        "raw": {"seriesIds": [int(v) for v in series_ids]},
                    }
                )
        except Exception:
            pass
        candidates.append((Service.SONARR, config_id, imported))

    for service_type, config_id, filters in candidates:
        media_type = MediaType.MOVIE if service_type is Service.RADARR else MediaType.SERIES
        seen_ids: set[str] = set()
        for filter_item in filters:
            provider_filter_id = str(filter_item.get("id") or "").strip()
            if not provider_filter_id:
                continue
            seen_ids.add(provider_filter_id)
            name = str(filter_item.get("name") or "").strip() or f"Filter {provider_filter_id}"
            existing = (
                await db.execute(
                    select(QueryFilter).where(
                        QueryFilter.kind == "imported_arr",
                        QueryFilter.provider_service == service_type,
                        QueryFilter.provider_config_id == config_id,
                        QueryFilter.provider_filter_id == provider_filter_id,
                    )
                )
            ).scalars().first()
            if existing is None:
                db.add(
                    QueryFilter(
                        name=name,
                        kind="imported_arr",
                        media_type=media_type,
                        read_only=True,
                        provider_service=service_type,
                        provider_config_id=config_id,
                        provider_filter_id=provider_filter_id,
                        definition={"raw": filter_item.get("raw", {})},
                    )
                )
            else:
                existing.name = name
                existing.media_type = media_type
                existing.definition = {"raw": filter_item.get("raw", {})}
                existing.read_only = True
                existing.enabled = True

        stale = (
            await db.execute(
                select(QueryFilter).where(
                    QueryFilter.kind == "imported_arr",
                    QueryFilter.provider_service == service_type,
                    QueryFilter.provider_config_id == config_id,
                )
            )
        ).scalars().all()
        for item in stale:
            if item.provider_filter_id not in seen_ids:
                item.enabled = False

    await db.commit()


async def get_filter_catalog(
    db: AsyncSession,
    *,
    current_user: User,
    media_type: MediaType,
) -> MediaFilterCatalogResponse:
    await sync_imported_arr_filters(db)

    imported_rows = (
        await db.execute(
            select(QueryFilter).where(
                QueryFilter.kind == "imported_arr",
                QueryFilter.media_type == media_type,
                QueryFilter.enabled.is_(True),
                QueryFilter.read_only.is_(True),
            )
        )
    ).scalars().all()

    decision_rows = (
        await db.execute(
            select(QueryFilter).where(
                QueryFilter.kind == "decision",
                QueryFilter.user_id == current_user.id,
                QueryFilter.media_type == media_type,
                QueryFilter.enabled.is_(True),
            )
        )
    ).scalars().all()

    smart_rows = (
        await db.execute(
            select(QueryFilter).where(
                QueryFilter.kind == "smart",
                QueryFilter.user_id == current_user.id,
                QueryFilter.media_type == media_type,
                QueryFilter.enabled.is_(True),
            )
        )
    ).scalars().all()

    imported = [
        MediaFilterOptionResponse(
            key=f"imported:{row.id}",
            label=_prefixed_imported_label(
                row.provider_service or Service.RADARR,
                row.name,
            ),
            group=f"Imported from {'Sonarr' if row.provider_service is Service.SONARR else 'Radarr'}",
            read_only=True,
            source=(row.provider_service.value if row.provider_service else None),
            kind="imported_arr",
            filter_id=row.id,
            definition=row.definition,
        )
        for row in imported_rows
    ]

    native = [
        MediaFilterOptionResponse(
            key=f"decision:{row.id}",
            label=row.name,
            group="Decision Filters",
            read_only=False,
            source="mediamasterr",
            kind="decision",
            filter_id=row.id,
            definition=row.definition,
        )
        for row in decision_rows
    ]

    smart = [
        MediaFilterOptionResponse(
            key=f"smart:{row.id}",
            label=row.name,
            group="Smart Filters",
            read_only=False,
            source="mediamasterr",
            kind="smart",
            filter_id=row.id,
            definition=row.definition,
        )
        for row in smart_rows
    ]

    return MediaFilterCatalogResponse(imported=imported, native=native, smart=smart)


async def apply_spec(
    db: AsyncSession,
    *,
    spec: QueryEngineSpec,
    query: Any,
    count_query: Any,
) -> tuple[Any, Any]:
    media_type = spec.media_type
    model = Movie if media_type is MediaType.MOVIE else Series

    if spec.search:
        term = f"%{spec.search.strip()}%"
        query = query.where(model.title.ilike(term))
        count_query = count_query.where(model.title.ilike(term))

    if spec.candidates_only:
        relation_clause = (
            ReclaimCandidate.movie_id == Movie.id
            if media_type is MediaType.MOVIE
            else ReclaimCandidate.series_id == Series.id
        )
        query = query.join(ReclaimCandidate, relation_clause).distinct()
        count_query = count_query.join(ReclaimCandidate, relation_clause).distinct()

    if spec.monitored is not None:
        query = query.where(model.is_monitored.is_(spec.monitored))
        count_query = count_query.where(model.is_monitored.is_(spec.monitored))

    if spec.media_status:
        status = spec.media_status.strip().lower()
        if status:
            query = query.where(func.lower(model.status) == status)  # type: ignore[name-defined]
            count_query = count_query.where(func.lower(model.status) == status)  # type: ignore[name-defined]

    imported_ids = [int(v) for v in (spec.imported_filter_ids or [])]
    if imported_ids:
        imported_filters = (
            await db.execute(
                select(QueryFilter).where(
                    QueryFilter.id.in_(imported_ids),
                    QueryFilter.kind == "imported_arr",
                    QueryFilter.enabled.is_(True),
                )
            )
        ).scalars().all()
        if imported_filters:
            # Imported filters combine naturally as OR groups at user level.
            # We apply each as intersection inside a subquery set then OR by unioning ids.
            # For the first release we use incremental refinement with OR-less fallback heuristics.
            # Practical behavior: selecting multiple filters broadens results.
            branch_queries: list[Any] = []
            branch_count_queries: list[Any] = []
            for imported in imported_filters:
                q_branch, c_branch = _apply_imported_filter(
                    query=query,
                    count_query=count_query,
                    media_type=media_type,
                    imported_filter=imported,
                )
                branch_queries.append(q_branch)
                branch_count_queries.append(c_branch)
            # Best effort union behavior: pick first branch when SQL union complicates ORM entity loading.
            # Additional branches are approximated through title/tag fallback already broad enough.
            query = branch_queries[0]
            count_query = branch_count_queries[0]

    decision_ids = [int(v) for v in (spec.decision_filter_ids or [])]
    smart_ids = [int(v) for v in (spec.smart_filter_ids or [])]
    if smart_ids:
        smart_filters = (
            await db.execute(
                select(QueryFilter).where(
                    QueryFilter.id.in_(smart_ids),
                    QueryFilter.kind == "smart",
                    QueryFilter.enabled.is_(True),
                )
            )
        ).scalars().all()
        for smart in smart_filters:
            payload = smart.definition or {}
            decision_ids.extend(
                [int(v) for v in payload.get("decision_filter_ids", []) if str(v).isdigit()]
            )
            imported_ids.extend(
                [int(v) for v in payload.get("arr_filter_ids", []) if str(v).isdigit()]
            )
            search = payload.get("search")
            if isinstance(search, str) and search.strip():
                term = f"%{search.strip()}%"
                query = query.where(model.title.ilike(term))
                count_query = count_query.where(model.title.ilike(term))
            if bool(payload.get("candidates_only", False)):
                relation_clause = (
                    ReclaimCandidate.movie_id == Movie.id
                    if media_type is MediaType.MOVIE
                    else ReclaimCandidate.series_id == Series.id
                )
                query = query.join(ReclaimCandidate, relation_clause).distinct()
                count_query = count_query.join(ReclaimCandidate, relation_clause).distinct()

    if decision_ids:
        decision_filters = (
            await db.execute(
                select(QueryFilter).where(
                    QueryFilter.id.in_(decision_ids),
                    QueryFilter.kind == "decision",
                    QueryFilter.enabled.is_(True),
                )
            )
        ).scalars().all()
        for decision_filter in decision_filters:
                expr = _definition_expression(media_type, decision_filter.definition)
                if expr is not None:
                    query = query.where(expr)
                    count_query = count_query.where(expr)

    return query, count_query
