from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.database.models import MediaAsset, MediaIdentity, Movie, Series
from backend.enums import MediaType
from backend.models.mie import (
    MieCorrelationArrIntelligence,
    MieCorrelationArtworkIntelligence,
    MieCorrelationExternalIds,
    MieCorrelationFileIntelligence,
    MieCorrelationHealthSummary,
    MieCorrelationIdentity,
    MieCorrelationRequestIntelligence,
    MieCorrelationTimelineEvent,
    MieCorrelationTorrentIntelligence,
)


@dataclass(slots=True)
class CorrelationSubject:
    media_type: MediaType
    media_id: int
    title: str
    year: int | None
    tmdb_id: int | None
    imdb_id: str | None
    tvdb_id: str | None
    anilist_id: int | None
    trakt_rating: int | None
    movie: Movie | None = None
    series: Series | None = None


@dataclass(slots=True)
class CorrelationBuildContext:
    subject: CorrelationSubject
    media_asset: MediaAsset | None = None
    media_identity: MediaIdentity | None = None
    identity: MieCorrelationIdentity | None = None
    request_intelligence: MieCorrelationRequestIntelligence = field(
        default_factory=MieCorrelationRequestIntelligence
    )
    arr_intelligence: MieCorrelationArrIntelligence = field(
        default_factory=MieCorrelationArrIntelligence
    )
    torrent_intelligence: MieCorrelationTorrentIntelligence = field(
        default_factory=MieCorrelationTorrentIntelligence
    )
    file_intelligence: MieCorrelationFileIntelligence = field(
        default_factory=MieCorrelationFileIntelligence
    )
    artwork_intelligence: MieCorrelationArtworkIntelligence = field(
        default_factory=MieCorrelationArtworkIntelligence
    )
    timeline: list[MieCorrelationTimelineEvent] = field(default_factory=list)
    health: MieCorrelationHealthSummary | None = None

    def fallback_identity(self) -> MieCorrelationIdentity:
        return MieCorrelationIdentity(
            media_identity_id=(self.media_identity.id if self.media_identity else None),
            canonical_title=self.subject.title,
            canonical_ids=MieCorrelationExternalIds(
                tmdb=(str(self.subject.tmdb_id) if self.subject.tmdb_id else None),
                tvdb=self.subject.tvdb_id,
                imdb=self.subject.imdb_id,
                trakt=(
                    str(self.subject.trakt_rating)
                    if self.subject.trakt_rating is not None
                    else None
                ),
                additional=(
                    {"anilist": str(self.subject.anilist_id)}
                    if self.subject.anilist_id is not None
                    else {}
                ),
            ),
            media_type=self.subject.media_type,
            release_year=self.subject.year,
            canonical_provider=(
                self.media_identity.canonical_provider if self.media_identity else None
            ),
        )


def utcnow() -> datetime:
    return datetime.now(UTC)
