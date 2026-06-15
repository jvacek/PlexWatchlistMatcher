"""Environment-driven settings. Sensible (insecure) defaults for local dev."""

import os
import secrets

from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

APP_PRODUCT = "Plex Watchlist Matcher"
APP_VERSION = "0.1.0"

# Absolute base URL of this app. Used to build the Plex OAuth forwardUrl, so it
# must be reachable by the user's browser. Set per environment (e.g. the fastapi
# cloud URL in prod); falls back to localhost for dev.
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

# Shared database. On a multi-instance host (e.g. fastapi cloud) every instance
# must point at the SAME database, or rooms created on one are invisible to the
# others. Prefer DATABASE_URL (the name managed Postgres providers like Neon
# expose) and fall back to a local SQLite file for single-instance dev.
DB_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or "sqlite:///./data/app.db"

# Signs session cookies. If unset we generate a random key on startup. That's
# fine for a SINGLE ephemeral instance, but the key changes on every restart
# (logging everyone out) and differs between processes — so set it in env when
# running multiple workers/replicas, or to keep sessions across restarts.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
DATA_DIR = os.getenv("DATA_DIR", "./data")
CACHE_DIR = os.getenv("CACHE_DIR", "./data/imgcache")
ROOM_TTL_HOURS = int(os.getenv("ROOM_TTL_HOURS", "24"))

# Only send cookies over HTTPS in production. Off by default so localhost works.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# Key for encrypting Plex tokens at rest. If unset we generate one on startup —
# fine for a single ephemeral instance (tokens just won't survive a restart, and
# the DB is wiped anyway). Set FERNET_KEY in env for multiple workers/replicas
# (each process needs the SAME key to decrypt tokens the others wrote) or to keep
# tokens across restarts.
_fkey = os.getenv("FERNET_KEY") or Fernet.generate_key().decode()
_fernet = Fernet(_fkey.encode())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
