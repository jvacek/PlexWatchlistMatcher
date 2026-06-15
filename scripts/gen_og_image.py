"""Generate the social-share image and icon set for Plex Watchlist Matcher.

Author-time tool — run it once (or whenever the branding changes) and commit the
PNGs it writes into ``app/static/``. The app only ever serves the committed files,
so the production runtime never needs Pillow.

    uv run --with pillow python scripts/gen_og_image.py
    # or, with pillow already in the dev group:
    uv run python scripts/gen_og_image.py

It tries to fetch the real brand fonts (Fraunces + Hanken Grotesk) via httpx and
falls back to local system fonts, so it still works offline.

Outputs (all under app/static/):
    og-image.png         1200x630  Open Graph / Twitter card
    apple-touch-icon.png 180x180
    icon-192.png         192x192   PWA manifest
    icon-512.png         512x512   PWA manifest
    favicon.ico          multi-size 16/32/48
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
LOGO_SVG = STATIC / "newlogo.svg"

# Brand palette (mirrors the CSS custom properties in app/static/app.css).
INK = (12, 11, 13)  # --ink-900  #0c0b0d
PAPER = (236, 230, 218)  # --paper    #ece6da
PAPER_DIM = (194, 188, 176)  # --paper-dim #c2bcb0
GOLD = (240, 178, 46)  # --gold     #f0b22e

# Variable brand fonts from the google/fonts repo, plus the axis values that give
# us a heavy display weight / a strong UI weight. Brackets are URL-encoded.
FRAUNCES_URL = (
    "https://github.com/google/fonts/raw/main/ofl/fraunces/"
    "Fraunces%5BSOFT,WONK,opsz,wght%5D.ttf"
)
FRAUNCES_AXES = [0, 0, 144, 900]  # SOFT, WONK, opsz, wght
HANKEN_URL = (
    "https://github.com/google/fonts/raw/main/ofl/hankengrotesk/"
    "HankenGrotesk%5Bwght%5D.ttf"
)
HANKEN_AXES = [600]  # wght

# Local fallbacks (macOS): a serif to echo Fraunces, a sans to echo Hanken.
SERIF_FALLBACKS = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/Library/Fonts/Georgia.ttf",
]
SANS_FALLBACKS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _try_remote_font(url: str, axes: list[int]) -> bytes | None:
    try:
        import httpx

        data = httpx.get(url, follow_redirects=True, timeout=30.0).content
        # Validate it actually loads (and that the variation axes apply).
        f = ImageFont.truetype(io.BytesIO(data), size=64)
        try:
            f.set_variation_by_axes(axes)
        except Exception:
            pass
        return data
    except Exception as exc:  # network off, 404, parse error...
        print(f"  (remote font unavailable, using fallback: {exc})")
        return None


def font_loader(url: str, axes: list[int], fallbacks: list[str]):
    """Return a callable size -> ImageFont, resolved once and reused."""
    data = _try_remote_font(url, axes)
    local = None
    if data is None:
        for path in fallbacks:
            if Path(path).exists():
                local = path
                break

    def load(size: int) -> ImageFont.FreeTypeFont:
        if data is not None:
            f = ImageFont.truetype(io.BytesIO(data), size=size)
            try:
                f.set_variation_by_axes(axes)
            except Exception:
                pass
            return f
        if local is not None:
            return ImageFont.truetype(local, size=size)
        return ImageFont.load_default(size)

    return load


def load_logo(size: int) -> Image.Image:
    """Rasterize the brand SVG (newlogo.svg) to a square RGBA image.

    Pillow can't render SVG, so we shell out to ImageMagick (which renders it
    via its rsvg delegate). Author-time only — the committed PNGs are what ship."""
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        raise RuntimeError(
            "ImageMagick is required to rasterize newlogo.svg "
            "(install it, e.g. `brew install imagemagick`)."
        )
    png = subprocess.run(
        [magick, "-background", "none", str(LOGO_SVG),
         "-resize", f"{size}x{size}", "png:-"],
        check=True, capture_output=True,
    ).stdout
    return Image.open(io.BytesIO(png)).convert("RGBA")


def make_icon(size: int) -> Image.Image:
    """The brand logo at the requested icon size."""
    return load_logo(size)


def fit_font(load, text: str, max_w: int, start: int, min_size: int = 24):
    """Largest font size (<= start) at which `text` fits within max_w."""
    size = start
    while size > min_size:
        font = load(size)
        if _text_w(font, text) <= max_w:
            return font
        size -= 2
    return load(min_size)


def _text_w(font: ImageFont.FreeTypeFont, text: str) -> float:
    return font.getbbox(text)[2]


def make_og(serif, sans) -> Image.Image:
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), INK)

    # Projector glow from the top — a soft gold ellipse, blurred.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W * 0.18, -260, W * 0.82, 240], fill=(*GOLD, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))

    d = ImageDraw.Draw(img)
    margin = 90

    # Wordmark row: logo + product name.
    logo = load_logo(56)
    img.paste(logo, (margin, 120 - 28), logo)
    mark_font = sans(34)
    d.text(
        (margin + 70, 120),
        "Plex Watchlist Matcher",
        font=mark_font,
        fill=PAPER,
        anchor="lm",
    )

    # Headline (the value prop, keyword-rich).
    head_lines = ["Compare Plex watchlists", "with friends."]
    head_font = fit_font(serif, max(head_lines, key=len), W - 2 * margin, start=92)
    y = 230
    for line in head_lines:
        d.text((margin, y), line, font=head_font, fill=PAPER, anchor="lm")
        y += int(head_font.size * 1.08)

    # Gold rule.
    d.rectangle([margin, y + 6, margin + 90, y + 11], fill=GOLD)

    # Subhead.
    sub_font = sans(33)
    d.text(
        (margin, y + 58),
        "See the movies & shows everyone wants to watch.",
        font=sub_font,
        fill=PAPER_DIM,
        anchor="lm",
    )
    return img


def main() -> None:
    STATIC.mkdir(parents=True, exist_ok=True)
    print("Loading fonts...")
    serif = font_loader(FRAUNCES_URL, FRAUNCES_AXES, SERIF_FALLBACKS)
    sans = font_loader(HANKEN_URL, HANKEN_AXES, SANS_FALLBACKS)

    print("Rendering og-image.png (1200x630)...")
    make_og(serif, sans).save(STATIC / "og-image.png", optimize=True)

    for name, size in [
        ("apple-touch-icon.png", 180),
        ("icon-192.png", 192),
        ("icon-512.png", 512),
    ]:
        print(f"Rendering {name} ({size}x{size})...")
        make_icon(size).save(STATIC / name, optimize=True)

    print("Rendering favicon.ico...")
    make_icon(256).save(STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    print(f"Done. Wrote assets to {STATIC}")


if __name__ == "__main__":
    main()
