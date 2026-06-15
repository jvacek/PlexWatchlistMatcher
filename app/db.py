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


# Columns earlier releases created but the current code no longer reads or
# writes. create_all never drops columns, so without this they'd linger forever
# on existing databases (dev SQLite and prod Postgres). None are indexed, so a
# plain DROP COLUMN is safe. Idempotent: harmless on a fresh DB that never had
# them. Once every live database has booted past this, the block can be deleted.
_DROPPED_COLUMNS = {
    "room": ("match_mode", "status", "host_participant_id"),
    "watchlistitem": ("studio", "tagline"),
    "participant": ("token_enc",),  # legacy encrypted Plex token; never stored now
}


def _drop_dead_columns() -> None:
    with engine.connect() as conn:
        sqlite = engine.dialect.name == "sqlite"  # ≥3.35 supports DROP COLUMN
        for table, columns in _DROPPED_COLUMNS.items():
            if sqlite:
                rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
                existing = {r[1] for r in rows}
                for col in columns:
                    if col in existing:
                        conn.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {col}")
            else:
                for col in columns:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}"
                    )
        conn.commit()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    # SQLite-only: create_all won't add columns to an existing table. A fresh
    # Postgres database gets the full current schema from create_all directly.
    if engine.dialect.name == "sqlite":
        _ensure_watchlist_columns()
    _drop_dead_columns()


def get_session():
    with Session(engine) as session:
        yield session
