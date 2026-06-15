#!/usr/bin/env -S uv run python
"""Generate fixed SECRET_KEY and FERNET_KEY values for the app's env config.

On a single instance the app generates these on startup, but fastapi cloud (and
any autoscaling / multi-worker host) runs several processes that must share the
SAME keys — otherwise session cookies won't validate across instances and Plex
tokens encrypted by one instance can't be decrypted by another. So generate the
pair once here and set both as environment variables on the platform.

Usage:
    uv run python scripts/gen_secrets.py            # print KEY=value lines
    uv run python scripts/gen_secrets.py >> .env    # append to a local .env

The two values are independent; regenerating rotates them (logging everyone out
and orphaning any tokens encrypted with the old FERNET_KEY).
"""

import secrets

from cryptography.fernet import Fernet


def main() -> None:
    # Matches how app/config.py generates these when the env vars are unset.
    print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
    print(f"FERNET_KEY={Fernet.generate_key().decode()}")


if __name__ == "__main__":
    main()
