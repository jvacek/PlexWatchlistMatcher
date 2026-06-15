"""SQLite engine + session helpers."""

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from . import config
from . import models  # noqa: F401  (import so tables register on metadata)

# Managed Postgres providers (Neon, Heroku, …) hand out postgres:// URLs; route
# them through psycopg 3, which is the driver we install.
_url = config.DB_URL
for _prefix in ("postgresql://", "postgres://"):
    if _url.startswith(_prefix):
        _url = "postgresql+psycopg://" + _url[len(_prefix) :]
        break

if _url.startswith("sqlite"):
    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    engine = create_engine(_url, connect_args={"check_same_thread": False})
else:
    # pre_ping recycles connections Neon dropped while the instance was idle.
    engine = create_engine(_url, pool_pre_ping=True)


# Columns added to watchlistitem after its first release. SQLite create_all
# won't alter an existing table, so add any missing ones (simple dev migration).
_WATCHLIST_ADDED_COLUMNS = {
    "rating_key": "VARCHAR",
    "audience_rating": "FLOAT",
    "content_rating": "VARCHAR",
    "duration": "INTEGER",
    "studio": "VARCHAR",
    "tagline": "VARCHAR",
    "genres": "VARCHAR",
    "director": "VARCHAR",
    "view_count": "INTEGER",
    "view_offset": "INTEGER",
}


def _ensure_watchlist_columns() -> None:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(watchlistitem)").fetchall()
        existing = {r[1] for r in rows}
        if not existing:  # table not created yet
            return
        for name, sqltype in _WATCHLIST_ADDED_COLUMNS.items():
            if name not in existing:
                conn.exec_driver_sql(
                    f"ALTER TABLE watchlistitem ADD COLUMN {name} {sqltype}"
                )
        conn.commit()


def _drop_legacy_token_column() -> None:
    """Pre-migration cleanup. The Plex token is no longer stored server-side, so
    drop the old participant.token_enc column — and any encrypted tokens still in
    it — from databases created before that change. create_all never removes
    columns, so without this the column (and real tokens) would linger. Idempotent
    and safe on a fresh DB, where the column was never created."""
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            rows = conn.exec_driver_sql("PRAGMA table_info(participant)").fetchall()
            if any(r[1] == "token_enc" for r in rows):  # SQLite ≥3.35 DROP COLUMN
                conn.exec_driver_sql("ALTER TABLE participant DROP COLUMN token_enc")
        else:
            conn.exec_driver_sql(
                "ALTER TABLE participant DROP COLUMN IF EXISTS token_enc"
            )
        conn.commit()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    # SQLite-only: create_all won't add columns to an existing table. A fresh
    # Postgres database gets the full current schema from create_all directly.
    if engine.dialect.name == "sqlite":
        _ensure_watchlist_columns()
    _drop_legacy_token_column()


def get_session():
    with Session(engine) as session:
        yield session
