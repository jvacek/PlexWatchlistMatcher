"""Point the app at a throwaway SQLite file before it gets imported."""

import os
import pathlib

# Drop any real Postgres URL from the environment so the suite can never drop
# and recreate tables against a production database.
os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("DB_URL", "sqlite:///./data/test.db")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("BASE_URL", "http://testserver")

_db = pathlib.Path("./data/test.db")
if _db.exists():
    _db.unlink()

# Create the schema up front (tests construct TestClient without the lifespan).
from app import db  # noqa: E402

db.init_db()
