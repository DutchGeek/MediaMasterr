from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.service_manager import service_manager
from backend.core.utils.filesystem import normalize_fpath
from backend.database.models import ServiceConfig
from backend.enums import Service
from backend.models.mie import (
    MigrationConflict,
    MigrationConflictResolution,
    MigrationDiscoveryRequest,
    MigrationDiscoveryResponse,
    MigrationInstanceOption,
    MigrationInventory,
    MigrationInventorySummary,
    MigrationMediaItem,
    MigrationMetadataPlan,
    MigrationNamedValue,
    MigrationPlanItem,
    MigrationPlanRequest,
    MigrationPlanResponse,
    MigrationPlanSummary,
    MigrationRootFolder,
    MigrationRootMapping,
    MigrationWorkspaceResponse,
)
from backend.services.mie.request_context import MieRequestContext
from backend.services.radarr import RadarrClient
from backend.services.sonarr import SonarrClient


class MigrationCenterService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        request_context: MieRequestContext | None = None,
    ) -> None:
        self.db = db
        self.request_context = request_context

    async def workspace(self) -> MigrationWorkspaceResponse:
        options = await self._instance_options()
        return MigrationWorkspaceResponse(
            available_sources=options,
            available_destinations=options,
        )

    async def discover(
        self, request: MigrationDiscoveryRequest
    ) -> MigrationDiscoveryResponse:
        source_config = await self._config_by_id(request.source_config_id)
        destination_config = await self._config_by_id(request.destination_config_id)
        source = await self._discover_inventory(source_config)
        destination = await self._discover_inventory(destination_config)

        warnings: list[str] = []
        compatible = source.instance.service_type == destination.instance.service_type
        if not compatible:
            warnings.append(
                "Source and destination use different ARR services. Discovery is allowed, but planning will require manual review."
            )
        return MigrationDiscoveryResponse(
            source=source,
            destination=destination,
            compatible=compatible,
            warnings=warnings,
        )

    async def plan(self, request: MigrationPlanRequest) -> MigrationPlanResponse:
        discovery = await self.discover(
            MigrationDiscoveryRequest(
                source_config_id=request.source_config_id,
                destination_config_id=request.destination_config_id,
            )
        )
        source = discovery.source
        destination = discovery.destination

        destination_matches = self._destination_match_index(destination.media_items)
        destination_duplicates = self._duplicate_match_keys(destination.media_items)

        items: list[MigrationPlanItem] = []
        conflicts: list[MigrationConflict] = []

        for source_item in source.media_items:
            match_key = self._identity_key(source_item)
            destination_item = destination_matches.get(match_key)
            mapped_path = self._apply_root_mappings(
                source_item.current_path or source_item.root_folder_path,
                request.root_mappings,
            )
            status = "copy_required"
            notes: list[str] = []
            conflict_keys: list[str] = []

            if not source_item.current_path:
                status = "skipped"
                notes.append("Source item has no filesystem path to migrate.")
                conflict = self._make_conflict(
                    key=f"missing:{source_item.kind}:{source_item.external_id}",
                    conflict_type="missing_media",
                    title=source_item.title,
                    description="Source media is missing a current filesystem path.",
                    source_value=source_item.root_folder_path,
                    destination_value=None,
                    resolutions=["skip", "compare"],
                )
                conflicts.append(conflict)
                conflict_keys.append(conflict.key)
            elif match_key in destination_duplicates:
                status = "manual_decision"
                notes.append(
                    "Multiple destination entries appear to represent the same media."
                )
                conflict = self._make_conflict(
                    key=f"duplicate:{source_item.kind}:{source_item.external_id}",
                    conflict_type="duplicate_media",
                    title=source_item.title,
                    description="The destination already contains more than one matching media item.",
                    source_value=source_item.current_path,
                    destination_value=destination_item.current_path if destination_item else None,
                    resolutions=["compare", "keep_destination", "skip"],
                )
                conflicts.append(conflict)
                conflict_keys.append(conflict.key)
            elif destination_item is None:
                status = "copy_required"
                notes.append(
                    "Media does not exist on the destination and would need to be copied or imported."
                )
            else:
                status = "existing"
                notes.append(
                    "Media already exists on the destination. Metadata and path differences were checked for conflicts."
                )
                if mapped_path and destination_item.current_path:
                    normalized_mapped = normalize_fpath(
                        mapped_path, strip_ending_slash=True, lower=True
                    )
                    normalized_destination = normalize_fpath(
                        destination_item.current_path,
                        strip_ending_slash=True,
                        lower=True,
                    )
                    if normalized_mapped != normalized_destination:
                        status = "conflict"
                        conflict = self._make_conflict(
                            key=f"root:{source_item.kind}:{source_item.external_id}",
                            conflict_type="different_root",
                            title=source_item.title,
                            description="The destination copy exists under a different root or folder path.",
                            source_value=mapped_path,
                            destination_value=destination_item.current_path,
                            resolutions=[
                                "keep_destination",
                                "overwrite",
                                "compare",
                                "skip",
                            ],
                        )
                        conflicts.append(conflict)
                        conflict_keys.append(conflict.key)
                if source_item.quality_profile != destination_item.quality_profile:
                    conflict = self._make_conflict(
                        key=f"quality:{source_item.kind}:{source_item.external_id}",
                        conflict_type="different_quality_profile",
                        title=source_item.title,
                        description="Source and destination use different quality profiles.",
                        source_value=source_item.quality_profile,
                        destination_value=destination_item.quality_profile,
                        resolutions=["keep_destination", "overwrite", "merge_metadata", "compare"],
                    )
                    conflicts.append(conflict)
                    conflict_keys.append(conflict.key)
                if source_item.monitored != destination_item.monitored:
                    conflict = self._make_conflict(
                        key=f"monitor:{source_item.kind}:{source_item.external_id}",
                        conflict_type="different_monitored_state",
                        title=source_item.title,
                        description="Source and destination have different monitored states.",
                        source_value=str(source_item.monitored),
                        destination_value=str(destination_item.monitored),
                        resolutions=["keep_destination", "overwrite", "merge_metadata", "compare"],
                    )
                    conflicts.append(conflict)
                    conflict_keys.append(conflict.key)
                if conflict_keys:
                    status = "manual_decision" if status == "existing" else status

            items.append(
                MigrationPlanItem(
                    key=f"{source_item.kind}:{source_item.external_id}",
                    kind=source_item.kind,
                    title=source_item.title,
                    year=source_item.year,
                    source_path=source_item.current_path,
                    destination_path=(destination_item.current_path if destination_item else None),
                    mapped_destination_path=mapped_path,
                    status=cast(Any, status),
                    size_bytes=source_item.size_bytes,
                    episode_count=source_item.episode_count,
                    conflict_keys=conflict_keys,
                    notes=notes,
                )
            )

        summary = self._plan_summary(items)
        metadata_plan = self._metadata_plan(source.instance.service_type)
        return MigrationPlanResponse(
            source=source,
            destination=destination,
            root_mappings=request.root_mappings,
            items=items,
            conflicts=conflicts,
            summary=summary,
            metadata_plan=metadata_plan,
            generated_at=datetime.now(UTC),
        )

    async def _instance_options(self) -> list[MigrationInstanceOption]:
        configs = await self._migration_configs()
        options = [await self._instance_option(config) for config in configs]
        options.sort(key=lambda row: (row.service_type, row.name.lower()))
        return options

    async def _migration_configs(self) -> list[ServiceConfig]:
        result = await self.db.execute(
            select(ServiceConfig).where(
                ServiceConfig.service_type.in_([Service.SONARR, Service.RADARR])
            )
        )
        return list(result.scalars().all())

    async def _config_by_id(self, config_id: int) -> ServiceConfig:
        config = (
            await self.db.execute(
                select(ServiceConfig).where(ServiceConfig.id == config_id)
            )
        ).scalar_one_or_none()
        if config is None:
            raise ValueError(f"Migration instance {config_id} was not found.")
        if config.service_type not in {Service.SONARR, Service.RADARR}:
            raise ValueError("Migration Center only supports Sonarr and Radarr.")
        return config

    async def _instance_option(self, config: ServiceConfig) -> MigrationInstanceOption:
        warnings: list[str] = []
        client = self._client_for_config(config)
        version: str | None = None
        root_count = 0
        item_count = 0
        is_available = False

        if client is not None:
            try:
                version = await client.get_app_version()
                roots = await self._endpoint_list(client, "rootfolder")
                root_count = len(roots)
                items = await self._media_items_for_client(config, client)
                item_count = len(items)
                is_available = True
            except Exception as exc:
                warnings.append(str(exc))

        return MigrationInstanceOption(
            config_id=config.id,
            service_type=cast(Any, config.service_type.value),
            name=config.name or f"{config.service_type.value.title()} {config.id}",
            base_url=config.base_url,
            enabled=config.enabled,
            is_available=is_available,
            version=version,
            library_count=root_count,
            root_folder_count=root_count,
            item_count=item_count,
            warnings=warnings,
        )

    async def _discover_inventory(self, config: ServiceConfig) -> MigrationInventory:
        option = await self._instance_option(config)
        client = self._client_for_config(config)
        if client is None:
            return MigrationInventory(instance=option, warnings=["Client unavailable."])

        warnings = list(option.warnings)
        roots = await self._root_folders(client, warnings)
        libraries = [
            MigrationNamedValue(id=root.id, name=root.path, description="Root folder")
            for root in roots
        ]
        tags = await self._named_endpoint(client, "tag", warnings)
        quality_profiles = await self._named_endpoint(client, "qualityprofile", warnings)
        language_profiles = await self._named_endpoint(client, "languageprofile", warnings)
        custom_formats = await self._named_endpoint(client, "customformat", warnings)
        metadata_profiles = await self._named_endpoint(client, "metadataprofile", warnings)
        collections = await self._named_endpoint(client, "collection", warnings)
        media_items = await self._media_items_for_client(config, client)

        summary = MigrationInventorySummary(
            root_folder_count=len(roots),
            library_count=len(libraries),
            tag_count=len(tags),
            quality_profile_count=len(quality_profiles),
            language_profile_count=len(language_profiles),
            custom_format_count=len(custom_formats),
            metadata_profile_count=len(metadata_profiles),
            collection_count=len(collections),
            media_count=len(media_items),
            episode_count=sum(item.episode_count for item in media_items),
            total_size_bytes=sum(item.size_bytes for item in media_items),
        )

        option.library_count = summary.library_count
        option.root_folder_count = summary.root_folder_count
        option.item_count = summary.media_count
        option.warnings = warnings

        return MigrationInventory(
            instance=option,
            roots=roots,
            libraries=libraries,
            tags=tags,
            quality_profiles=quality_profiles,
            language_profiles=language_profiles,
            custom_formats=custom_formats,
            metadata_profiles=metadata_profiles,
            collections=collections,
            media_items=media_items,
            summary=summary,
            warnings=warnings,
            discovered_at=datetime.now(UTC),
        )

    def _client_for_config(
        self, config: ServiceConfig
    ) -> SonarrClient | RadarrClient | None:
        if config.service_type is Service.SONARR:
            return service_manager.get_sonarr(config.id) or SonarrClient(
                api_key=config.api_key,
                base_url=config.base_url,
            )
        if config.service_type is Service.RADARR:
            return service_manager.get_radarr(config.id) or RadarrClient(
                api_key=config.api_key,
                base_url=config.base_url,
            )
        return None

    async def _endpoint_list(
        self,
        client: SonarrClient | RadarrClient,
        endpoint: str,
    ) -> list[Mapping[str, object]]:
        _, data = await client._make_request("GET", endpoint, timeout=120)
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, Mapping)]

    async def _named_endpoint(
        self,
        client: SonarrClient | RadarrClient,
        endpoint: str,
        warnings: list[str],
    ) -> list[MigrationNamedValue]:
        try:
            rows = await self._endpoint_list(client, endpoint)
        except Exception as exc:
            warnings.append(f"{endpoint}: {exc}")
            return []

        values: list[MigrationNamedValue] = []
        for row in rows:
            item_id = row.get("id")
            name = row.get("name") or row.get("label") or row.get("path")
            if item_id is None or not name:
                continue
            values.append(MigrationNamedValue(id=str(item_id), name=str(name)))
        return values

    async def _root_folders(
        self,
        client: SonarrClient | RadarrClient,
        warnings: list[str],
    ) -> list[MigrationRootFolder]:
        try:
            roots = await self._endpoint_list(client, "rootfolder")
            disk_by_path: dict[str, Mapping[str, object]] = {}
            try:
                for entry in await client.get_disk_space():
                    path = str(entry.get("path") or "").strip()
                    if path:
                        disk_by_path[normalize_fpath(path, strip_ending_slash=True)] = entry
            except Exception as exc:
                warnings.append(f"diskspace: {exc}")
            items: list[MigrationRootFolder] = []
            for row in roots:
                path = str(row.get("path") or "").strip()
                if not path:
                    continue
                disk = disk_by_path.get(normalize_fpath(path, strip_ending_slash=True), {})
                items.append(
                    MigrationRootFolder(
                        id=str(row.get("id") or path),
                        path=path,
                        free_space=(
                            int(cast(int, disk.get("free_space")))
                            if disk.get("free_space") is not None
                            else None
                        ),
                        total_space=(
                            int(cast(int, disk.get("total_space")))
                            if disk.get("total_space") is not None
                            else None
                        ),
                    )
                )
            return items
        except Exception as exc:
            warnings.append(f"rootfolder: {exc}")
            return []

    async def _media_items_for_client(
        self,
        config: ServiceConfig,
        client: SonarrClient | RadarrClient,
    ) -> list[MigrationMediaItem]:
        if config.service_type is Service.SONARR:
            return await self._sonarr_media_items(cast(SonarrClient, client))
        return await self._radarr_media_items(cast(RadarrClient, client))

    async def _sonarr_media_items(
        self, client: SonarrClient
    ) -> list[MigrationMediaItem]:
        tags = {row.id: row.label for row in await client.get_tags()}
        quality_profiles = {
            row.id: row.name for row in await self._named_endpoint(client, "qualityprofile", [])
        }
        language_profiles = {
            row.id: row.name for row in await self._named_endpoint(client, "languageprofile", [])
        }
        metadata_profiles = {
            row.id: row.name for row in await self._named_endpoint(client, "metadataprofile", [])
        }
        items: list[MigrationMediaItem] = []
        for series in await client.get_all_series():
            raw = dict(series.raw or {})
            statistics = raw.get("statistics")
            episode_count = 0
            size_bytes = 0
            if isinstance(statistics, Mapping):
                episode_count = int(statistics.get("episodeFileCount") or 0)
                size_bytes = int(statistics.get("sizeOnDisk") or 0)
            quality_profile_id = raw.get("qualityProfileId")
            language_profile_id = raw.get("languageProfileId")
            metadata_profile_id = raw.get("metadataProfileId")
            items.append(
                MigrationMediaItem(
                    kind="series",
                    external_id=str(series.id),
                    title=series.title,
                    year=series.year,
                    tmdb_id=series.tmdb_id,
                    tvdb_id=series.tvdb_id,
                    imdb_id=series.imdb_id,
                    current_path=series.path,
                    root_folder_path=str(raw.get("rootFolderPath") or "").strip() or None,
                    monitored=series.monitored,
                    tags=[tags[tag_id] for tag_id in series.tags if tag_id in tags],
                    quality_profile=quality_profiles.get(str(quality_profile_id))
                    or (str(quality_profile_id) if quality_profile_id is not None else None),
                    language_profile=language_profiles.get(str(language_profile_id))
                    or (str(language_profile_id) if language_profile_id is not None else None),
                    metadata_profile=metadata_profiles.get(str(metadata_profile_id))
                    or (str(metadata_profile_id) if metadata_profile_id is not None else None),
                    custom_formats=[str(item) for item in raw.get("customFormatIds") or []],
                    series_type=str(raw.get("seriesType") or "").strip() or None,
                    season_monitoring=str(raw.get("monitorNewItems") or "").strip() or None,
                    size_bytes=size_bytes,
                    episode_count=episode_count,
                    season_count=series.season_count,
                )
            )
        return items

    async def _radarr_media_items(self, client: RadarrClient) -> list[MigrationMediaItem]:
        tags = {row.id: row.label for row in await client.get_tags()}
        quality_profiles = {
            row.id: row.name for row in await self._named_endpoint(client, "qualityprofile", [])
        }
        metadata_profiles = {
            row.id: row.name for row in await self._named_endpoint(client, "metadataprofile", [])
        }
        items: list[MigrationMediaItem] = []
        for movie in await client.get_all_movies():
            raw = dict(movie.raw or {})
            quality_profile_id = raw.get("qualityProfileId")
            metadata_profile_id = raw.get("metadataProfileId")
            collection_name = None
            collection = raw.get("collection")
            if isinstance(collection, Mapping):
                collection_name = str(collection.get("name") or "").strip() or None
            items.append(
                MigrationMediaItem(
                    kind="movie",
                    external_id=str(movie.id),
                    title=movie.title,
                    year=movie.year,
                    tmdb_id=movie.tmdb_id,
                    imdb_id=movie.imdb_id,
                    current_path=movie.path,
                    root_folder_path=str(raw.get("rootFolderPath") or "").strip() or None,
                    monitored=movie.monitored,
                    tags=[tags[tag_id] for tag_id in movie.tags if tag_id in tags],
                    quality_profile=quality_profiles.get(str(quality_profile_id))
                    or (str(quality_profile_id) if quality_profile_id is not None else None),
                    metadata_profile=metadata_profiles.get(str(metadata_profile_id))
                    or (str(metadata_profile_id) if metadata_profile_id is not None else None),
                    custom_formats=[str(item) for item in raw.get("customFormatIds") or []],
                    minimum_availability=(
                        str(raw.get("minimumAvailability") or "").strip() or None
                    ),
                    collections=[collection_name] if collection_name else [],
                    has_file=movie.has_file,
                    size_bytes=int(raw.get("sizeOnDisk") or 0),
                )
            )
        return items

    @staticmethod
    def _identity_key(item: MigrationMediaItem) -> str:
        if item.kind == "series":
            if item.tvdb_id is not None:
                return f"series:tvdb:{item.tvdb_id}"
            if item.tmdb_id is not None:
                return f"series:tmdb:{item.tmdb_id}"
        else:
            if item.tmdb_id is not None:
                return f"movie:tmdb:{item.tmdb_id}"
        if item.imdb_id:
            return f"imdb:{item.imdb_id.lower()}"
        return f"{item.kind}:{item.title.lower()}:{item.year or 0}"

    def _destination_match_index(
        self, items: list[MigrationMediaItem]
    ) -> dict[str, MigrationMediaItem]:
        matches: dict[str, MigrationMediaItem] = {}
        for item in items:
            matches.setdefault(self._identity_key(item), item)
        return matches

    def _duplicate_match_keys(self, items: list[MigrationMediaItem]) -> set[str]:
        counts: dict[str, int] = {}
        for item in items:
            key = self._identity_key(item)
            counts[key] = counts.get(key, 0) + 1
        return {key for key, count in counts.items() if count > 1}

    @staticmethod
    def _apply_root_mappings(
        path: str | None,
        mappings: list[MigrationRootMapping],
    ) -> str | None:
        if not path:
            return None
        normalized_path = normalize_fpath(path, strip_ending_slash=True)
        ordered = sorted(
            mappings,
            key=lambda row: len(normalize_fpath(row.source_root, strip_ending_slash=True)),
            reverse=True,
        )
        for mapping in ordered:
            source_root = normalize_fpath(mapping.source_root, strip_ending_slash=True)
            destination_root = normalize_fpath(
                mapping.destination_root, strip_ending_slash=True
            )
            if not source_root:
                continue
            if normalized_path == source_root:
                return destination_root
            prefix = f"{source_root.rstrip('/')}/"
            if normalized_path.startswith(prefix):
                suffix = normalized_path[len(prefix) :]
                return f"{destination_root.rstrip('/')}/{suffix}" if suffix else destination_root
        return normalized_path

    @staticmethod
    def _make_conflict(
        *,
        key: str,
        conflict_type: str,
        title: str,
        description: str,
        source_value: str | None,
        destination_value: str | None,
        resolutions: list[MigrationConflictResolution],
    ) -> MigrationConflict:
        return MigrationConflict(
            key=key,
            conflict_type=conflict_type,
            title=title,
            description=description,
            source_value=source_value,
            destination_value=destination_value,
            resolutions=resolutions,
        )

    @staticmethod
    def _plan_summary(items: list[MigrationPlanItem]) -> MigrationPlanSummary:
        return MigrationPlanSummary(
            series_count=sum(1 for item in items if item.kind == "series"),
            movie_count=sum(1 for item in items if item.kind == "movie"),
            episode_count=sum(item.episode_count for item in items),
            item_count=len(items),
            files_requiring_copy=sum(1 for item in items if item.status == "copy_required"),
            existing_files=sum(1 for item in items if item.status == "existing"),
            skipped_files=sum(1 for item in items if item.status == "skipped"),
            conflict_count=sum(1 for item in items if item.status == "conflict"),
            manual_decision_count=sum(
                1 for item in items if item.status == "manual_decision"
            ),
            total_size_bytes=sum(item.size_bytes for item in items),
            estimated_duration_minutes=MigrationCenterService._estimate_duration_minutes(
                sum(item.size_bytes for item in items if item.status == "copy_required")
            ),
        )

    @staticmethod
    def _estimate_duration_minutes(bytes_to_copy: int) -> int | None:
        if bytes_to_copy <= 0:
            return 0
        bytes_per_minute = 125 * 1024 * 1024 * 60
        return max(1, int(round(bytes_to_copy / bytes_per_minute)))

    @staticmethod
    def _metadata_plan(service_type: str) -> MigrationMetadataPlan:
        if service_type == "sonarr":
            return MigrationMetadataPlan(
                monitored_state=True,
                tags=True,
                root_folder=True,
                quality_profile=True,
                language_profile=True,
                season_monitoring=True,
                custom_formats=True,
                series_type=True,
                metadata_profile=True,
            )
        return MigrationMetadataPlan(
            monitored_state=True,
            tags=True,
            root_folder=True,
            quality_profile=True,
            custom_formats=True,
            metadata_profile=True,
            minimum_availability=True,
            collections=True,
        )