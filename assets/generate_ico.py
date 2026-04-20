"""One-shot script: render icon.svg → icon.png (512px) + icon.ico (multi-size).

**Requires cairosvg** — the Pillow-based fallback used to silently drift
from the SVG design (review #12). Per review #3, the previous "small-size
simplified" path drew a different hexagon in Python and shipped that to
the taskbar / tray; we now render every ico frame from the same SVG and
LANCZOS-resize it down, so taskbar and About-dialog show the same glyph.

Install: ``pip install -r requirements-dev.txt``.
Run once, commit the generated ``icon.png`` + ``icon.ico`` — the app
loads them as assets, it never regenerates at runtime.
"""
from __future__ import annotations

import io
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
        "    pip install -r requirements-dev.txt"
    )

HERE = Path(__file__).parent
SVG = HERE / "icon.svg"
PNG = HERE / "icon.png"
ICO = HERE / "icon.ico"


def render_svg(size: int) -> Image.Image:
    """Render icon.svg to an in-memory RGBA PIL Image at *size* px."""
    buf = io.BytesIO()
    cairosvg.svg2png(url=str(SVG), write_to=buf,
                      output_width=size, output_height=size)
    buf.seek(0)
    return Image.open(buf).convert("RGBA")


def main():
    # Single source of truth: render at 512 once and save as the canonical PNG.
    base = render_svg(512)
    base.save(PNG, "PNG")
    print(f"  wrote {PNG} ({base.size[0]}x{base.size[1]})")

    # ICO frames — small sizes start from a higher-res render so LANCZOS
    # has good detail to subsample from. Avoids the visible pixelation
    # that downscaling 512→16 in one step produces.
    sizes = [16, 24, 32, 48, 64, 128, 256]
    src_for = {sz: render_svg(max(sz * 4, 192)) for sz in sizes if sz <= 64}

    frames = []
    for sz in sizes:
        src = src_for.get(sz, base)
        frames.append(src.resize((sz, sz), Image.LANCZOS))

    frames[0].save(ICO, format="ICO",
                    sizes=[(f.width, f.height) for f in frames],
                    append_images=frames[1:])
    print(f"  wrote {ICO} (sizes: {sizes})")


if __name__ == "__main__":
    main()
