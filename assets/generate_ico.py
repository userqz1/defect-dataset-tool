"""One-shot script: render icon.svg → icon.png (512px) + icon.ico (multi-size).

**Requires cairosvg** — the Pillow-based fallback used to silently drift
from the SVG design (review #12: font position / beam layout off).
A mismatched shipped ico is worse than a build-time error, so we fail
loudly if cairosvg isn't installed.

Install: ``pip install -r requirements-dev.txt``.
Run once, commit the generated ``icon.png`` + ``icon.ico`` — the app
loads them as assets, it never regenerates at runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow not installed — install requirements-dev.txt first")

try:
    import cairosvg
except ImportError:
    sys.exit(
        "cairosvg is required to regenerate the icon — it guarantees the\n"
        "rendered output matches icon.svg. Install via:\n"
        "    pip install -r requirements-dev.txt\n"
        "(Fallback renderers were removed in review #12 because they\n"
        "produced visibly different glyphs from the design.)"
    )

HERE = Path(__file__).parent
SVG = HERE / "icon.svg"
PNG = HERE / "icon.png"
ICO = HERE / "icon.ico"


def render_svg_to_png(size: int = 512) -> Image.Image:
    """Render icon.svg at *size* px via cairosvg and return a PIL Image."""
    cairosvg.svg2png(url=str(SVG), write_to=str(PNG),
                      output_width=size, output_height=size)
    return Image.open(PNG)


def _draw_icon(size: int, simplified: bool = False) -> Image.Image:
    """Draw the prism icon at the given pixel size.

    Args:
        simplified: If True, only draw hexagon + "坊" (for small sizes like taskbar).
    """
    from PIL import ImageDraw, ImageFont

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def s(x: float, y: float) -> tuple[float, float]:
        """Scale 512-space coords to current size."""
        return (x * size / 512, y * size / 512)

    def sw(w: float) -> int:
        """Scale a stroke width."""
        return max(1, round(w * size / 512))

    # --- Rounded-rect background with subtle gradient ---
    pad = size * 32 / 512
    side = size - 2 * pad
    r = size * 96 / 512
    x0, y0, x1, y1 = pad, pad, pad + side, pad + side

    # Base fill
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=(196, 88, 52))

    # Simulate gradient: draw overlapping rounded rects with varying alpha
    # Top-left lighter overlay
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=(230, 140, 100, 50))
    # Mask: fade from top-left to bottom-right
    import numpy as np
    arr = np.array(overlay, dtype=np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    fade = 1.0 - np.clip(((xx + yy) / (size * 1.5)), 0, 1)
    arr[:, :, 3] = arr[:, :, 3] * fade
    overlay = Image.fromarray(arr.astype(np.uint8))
    img = Image.alpha_composite(img, overlay)

    # Bottom-right darker overlay
    overlay2 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    od2 = ImageDraw.Draw(overlay2)
    od2.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=(120, 50, 25, 40))
    arr2 = np.array(overlay2, dtype=np.float32)
    fade2 = np.clip(((xx + yy) / (size * 1.5) - 0.3), 0, 1)
    arr2[:, :, 3] = arr2[:, :, 3] * fade2
    overlay2 = Image.fromarray(arr2.astype(np.uint8))
    img = Image.alpha_composite(img, overlay2)

    draw = ImageDraw.Draw(img)

    # --- Hexagonal prism (always drawn, slightly larger when simplified) ---
    if simplified:
        # Bigger, centered hexagon + thicker stroke for legibility
        hex_pts = [s(256, 80), s(380, 152), s(380, 296), s(256, 368), s(132, 296), s(132, 152)]
        draw.polygon(hex_pts, outline=(255, 255, 255, 240), width=sw(18))
    else:
        hex_pts = [s(256, 100), s(360, 160), s(360, 288), s(256, 348), s(152, 288), s(152, 160)]
        draw.polygon(hex_pts, outline=(255, 255, 255, 235), width=sw(14))

        # Inner facet lines (3D depth)
        center = s(256, 230)
        for pt in [s(256, 100), s(360, 160), s(152, 160)]:
            draw.line([pt, center], fill=(255, 255, 255, 64), width=sw(6))

        # --- Incoming beam (left) ---
        draw.line([s(60, 224), s(152, 224)], fill=(255, 255, 255, 166), width=sw(10))

        # --- Refracted output beams (right) ---
        beam_color = (255, 214, 196, 180)
        draw.line([s(360, 192), s(440, 148)], fill=beam_color, width=sw(7))
        draw.line([s(360, 224), s(448, 224)], fill=beam_color, width=sw(7))
        draw.line([s(360, 256), s(440, 300)], fill=beam_color, width=sw(7))

        # Beam endpoint dots
        dot_color = (255, 214, 196, 153)
        for cx, cy, dr in [(444, 146, 6), (452, 224, 6), (444, 302, 6)]:
            ex, ey = s(cx, cy)
            er = dr * size / 512
            draw.ellipse([ex - er, ey - er, ex + er, ey + er], fill=dot_color)

    # --- "坊" character (larger weight when simplified) ---
    font_size = round((90 if simplified else 72) * size / 512)
    font = None
    for font_path in [
        "C:/Windows/Fonts/msyhbd.ttc",  # Microsoft YaHei Bold
        "C:/Windows/Fonts/msyh.ttc",
        "msyh.ttc",
    ]:
        try:
            from PIL import ImageFont as IF
            font = IF.truetype(font_path, size=font_size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    tx, ty = s(256, 240 if simplified else 252)
    draw.text((tx, ty), "坊", fill=(255, 255, 255, 235), font=font, anchor="mm")

    if not simplified:
        # --- Subtle bottom accent line ---
        draw.line([s(200, 398), s(312, 398)], fill=(255, 255, 255, 64), width=sw(4))

    return img


def main():
    img = render_svg_to_png(512)
    img.save(PNG, "PNG")
    print(f"  wrote {PNG} ({img.size[0]}x{img.size[1]})")

    # Generate ICO with multiple sizes
    # Small sizes (<=48px) use simplified icon for legibility
    sizes = [16, 24, 32, 48, 64, 128, 256]
    SIMPLIFY_THRESHOLD = 48
    print("  rendering simplified variant for small sizes...")
    small_big = _draw_icon(SIMPLIFY_THRESHOLD * 4, simplified=True)
    small_img = small_big.resize((SIMPLIFY_THRESHOLD, SIMPLIFY_THRESHOLD), Image.LANCZOS)

    frames = []
    for sz in sizes:
        if sz <= SIMPLIFY_THRESHOLD:
            resized = small_img.resize((sz, sz), Image.LANCZOS)
        else:
            resized = img.resize((sz, sz), Image.LANCZOS)
        frames.append(resized)

    frames[0].save(ICO, format="ICO", sizes=[(f.width, f.height) for f in frames],
                   append_images=frames[1:])
    print(f"  wrote {ICO} (sizes: {sizes})")


if __name__ == "__main__":
    main()
