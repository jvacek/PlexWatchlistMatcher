"""Environment-driven settings. Sensible (insecure) defaults for local dev."""

import hashlib
import os
from uuid import uuid4

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

# Signs session cookies. Required: every instance must share the SAME value or
# a cookie set by one can't be validated by another (sessions break mid-login).
SECRET_KEY = os.environ["SECRET_KEY"]
DATA_DIR = os.getenv("DATA_DIR", "./data")
CACHE_DIR = os.getenv("CACHE_DIR", "./data/imgcache")
ROOM_TTL_HOURS = int(os.getenv("ROOM_TTL_HOURS", "24"))

# Only send cookies over HTTPS in production. Off by default so localhost works.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# Key for encrypting Plex tokens at rest. Required and shared across instances:
# each process needs the SAME key to decrypt tokens the others wrote.
_fkey = os.environ["FERNET_KEY"]
_fernet = Fernet(_fkey.encode())


# Diagnostics. A per-process id plus short fingerprints of the keys: if two
# requests in one Plex login log different fingerprints, the instances disagree
# on SECRET_KEY/FERNET_KEY — which is exactly what breaks sessions across an
# autoscaled deploy. Fingerprints are one-way hashes, safe to log.
INSTANCE_ID = uuid4().hex[:8]
SECRET_KEY_FP = hashlib.sha256(SECRET_KEY.encode()).hexdigest()[:8]
FERNET_KEY_FP = hashlib.sha256(_fkey.encode()).hexdigest()[:8]


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
