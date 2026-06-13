"""SQLModel tables. A Room holds Participants; each Participant has WatchlistItems."""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Naive UTC timestamp (keeps SQLite comparisons consistent)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Room(SQLModel, table=True):
    id: str = Field(primary_key=True)  # short share slug
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    match_mode: str = "intersection_partials"
    host_participant_id: int | None = None
    status: str = "open"


class Participant(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    room_id: str = Field(foreign_key="room.id", index=True)
    plex_uuid: str = Field(index=True)
    plex_username: str
    plex_thumb: str | None = None
    client_id: str  # the Plex client identifier this person authed with
    token_enc: str | None = None  # Fernet-encrypted Plex token; purged on expiry
    status: str = "pending"  # pending | fetching | ready | error
    joined_at: datetime = Field(default_factory=utcnow)
    watchlist_fetched_at: datetime | None = None


class WatchlistItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    participant_id: int = Field(foreign_key="participant.id", index=True)
    plex_guid: str = Field(index=True)  # plex://... — the cross-account match key
    title: str
    type: str | None = None
    year: int | None = None
    summary: str | None = None
    thumb: str | None = None
    rating: float | None = None
