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
    rating_key: str | None = None  # Plex ratingKey, used to add to a watchlist
    title: str
    type: str | None = None
    year: int | None = None
    summary: str | None = None
    thumb: str | None = None
    rating: float | None = None  # critic rating (0-10)
    audience_rating: float | None = None
    content_rating: str | None = None
    duration: int | None = None  # milliseconds
    studio: str | None = None
    tagline: str | None = None
    genres: str | None = None  # '|'-separated
    director: str | None = None  # '|'-separated
    view_count: int | None = None  # >0 means this user has watched it
    view_offset: int | None = None  # ms into the item; >0 means in progress


class WatchState(SQLModel, table=True):
    """A participant's watch state for an item that may NOT be on their own
    watchlist (Plex drops watched items from the watchlist). Populated by a
    cross-reference sync over every item in the room."""

    id: int | None = Field(default=None, primary_key=True)
    participant_id: int = Field(foreign_key="participant.id", index=True)
    rating_key: str = Field(index=True)
    view_count: int = 0
    view_offset: int = 0
