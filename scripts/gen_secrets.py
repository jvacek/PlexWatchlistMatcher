#!/usr/bin/env -S uv run python
"""Generate a fixed SECRET_KEY for the app's env config.

SECRET_KEY signs the session cookie. On a single instance the app can generate
one on startup, but fastapi cloud (and any autoscaling / multi-worker host) runs
several processes that must share the SAME value — otherwise a cookie set by one
process won't validate on another and sessions break mid-login. So generate it
once here and set it as an environment variable on the platform.

There is no token-encryption key any more: Plex tokens live only in the user's
browser and never reach the server, so SECRET_KEY is the only shared secret.

Usage:
    uv run python scripts/gen_secrets.py            # print KEY=value line
    uv run python scripts/gen_secrets.py >> .env    # append to a local .env

Regenerating rotates it, logging everyone out.
"""

import secrets


def main() -> None:
    print(f"SECRET_KEY={secrets.token_urlsafe(48)}")


if __name__ == "__main__":
    main()
