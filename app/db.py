"""SQLite engine + session helpers."""

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from . import config
from . import models  # noqa: F401  (import so tables register on metadata)

Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)

engine = create_engine(config.DB_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
