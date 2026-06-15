"""Shared Jinja2 templates instance."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from . import config

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Exposed to every template so they can build absolute URLs (canonical, og:url,
# og:image) without each route having to pass them in.
templates.env.globals["BASE_URL"] = config.BASE_URL
templates.env.globals["SITE_NAME"] = config.APP_PRODUCT
# The browser's Plex client sends these as X-Plex-Product / X-Plex-Version, so
# plex-client.js reads them from the page (see auth.html / room.html).
templates.env.globals["APP_PRODUCT"] = config.APP_PRODUCT
templates.env.globals["APP_VERSION"] = config.APP_VERSION
