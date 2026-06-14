"""SQLite engine + session helpers."""

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from . import config
from . import models  # noqa: F401  (import so tables register on metadata)

Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)

engine = create_engine(config.DB_URL, connect_args={"check_same_thread": False})


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


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _ensure_watchlist_columns()


def get_session():
    with Session(engine) as session:
        yield session
