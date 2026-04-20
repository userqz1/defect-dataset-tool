"""Generate the brand D-chip icon.png + icon.ico.

Draws a clay-filled rounded square with a subtle top→bottom-right
gradient, a specular highlight strip, and an italic serif "D" centered
on top. Matches the in-window ``_BrandChip`` widget pixel-for-pixel
(within PIL/Qt font-rendering differences) so taskbar / title-bar /
about-dialog all show the same mark.

Run once, commit the generated ``icon.png`` + ``icon.ico``:
    python assets/generate_ico.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow + numpy required — pip install -r requirements.txt")

HERE = Path(__file__).parent
PNG = HERE / "icon.png"
ICO = HERE / "icon.ico"

# Palette — mirrors LIGHT.ACCENT in gui/theme.py.
CLAY_TOP = (201, 100, 66)          # #C96442
CLAY_BOT = (173, 85, 55)           # ≈ CLAY_TOP.darker(115)
HIGHLIGHT = (255, 255, 255, 32)    # top-edge specular


def _font_for(size_px: int) -> ImageFont.FreeTypeFont:
    """Try the font stack the widget uses (Georgia first)."""
    candidates = [
        "georgia.ttf", "Georgia.ttf",
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/timesbi.ttf",  # Times Bold Italic fallback
        "C:/Windows/Fonts/simsun.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size_px)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_d_chip(size: int) -> Image.Image:
    """Render a D-chip icon at *size* px square. RGBA."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Radius scaled from the 20→5 ratio of the in-window chip.
    radius = max(2, int(size * 5 / 20))
    pad = 0
    x0, y0, x1, y1 = pad, pad, size - 1 - pad, size - 1 - pad

    # -- Clay gradient (top-left → bottom-right) via numpy ramp -------
    # ImageDraw has no native gradient, so interpolate per-pixel,
    # then mask by a rounded-rect alpha to get the chip shape.
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    t = np.clip((xx + yy) / (2 * (size - 1)), 0, 1)
    r = CLAY_TOP[0] * (1 - t) + CLAY_BOT[0] * t
    g = CLAY_TOP[1] * (1 - t) + CLAY_BOT[1] * t
    b = CLAY_TOP[2] * (1 - t) + CLAY_BOT[2] * t
    grad = np.stack([r, g, b, np.full_like(t, 255.0)], axis=-1).astype(np.uint8)
    grad_img = Image.fromarray(grad, "RGBA")

    # Rounded-rect alpha mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [x0, y0, x1, y1], radius=radius, fill=255,
    )
    img.paste(grad_img, (0, 0), mask)

    # -- Top highlight strip ------------------------------------------
    hl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hl_draw = ImageDraw.Draw(hl)
    hl_h = max(2, int(size * 0.45))
    inset = max(1, int(size * 0.04))
    hl_draw.rounded_rectangle(
        [inset, inset, size - 1 - inset, hl_h],
        radius=max(1, radius - 1), fill=HIGHLIGHT,
    )
    img = Image.alpha_composite(img, hl)

    # -- Italic serif "D" centered ------------------------------------
    d = ImageDraw.Draw(img)
    font_size = max(8, int(size * 0.62))
    font = _font_for(font_size)
    text = "D"
    # Use textbbox for accurate centering (PIL ≥ 8.0).
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Italic slants the glyph right — nudge left 1/20 of size so the
    # optical center lines up with the chip center.
    dx = -(bbox[0]) + (size - tw) / 2 - size / 20
    dy = -(bbox[1]) + (size - th) / 2 - size * 0.02
    d.text((dx, dy), text, font=font, fill=(255, 255, 255, 255))

    return img


def main() -> None:
    # High-res canonical PNG (for the About dialog / marketing reuse).
    big = draw_d_chip(512)
    big.save(PNG, "PNG")
    print(f"  wrote {PNG} (512x512)")

    # Multi-frame .ico. Small sizes render from their own draw (not a
    # downscale of 512) so the glyph stays crisp — 20px text rendered
    # at 20px looks better than a 16px crop of a 512→16 LANCZOS.
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [draw_d_chip(sz) for sz in sizes]
    # PIL's ICO writer iterates ``sizes`` kwarg (or the default 16→256
    # list) and skips any size larger than the PRIMARY image. Pass the
    # 256px frame as primary so every requested size has a match.
    primary = frames[-1]       # 256
    extras = frames[:-1]       # 16, 24, 32, 48, 64, 128
    primary.save(ICO, format="ICO", append_images=extras)
    print(f"  wrote {ICO} (sizes: {sizes})")


if __name__ == "__main__":
    main()
