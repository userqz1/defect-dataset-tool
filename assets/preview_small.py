"""Quick preview: render icon.svg at 48px and upscale 4× for visual inspection.

Used to eyeball how the SVG holds up at taskbar size before committing
the generated .ico. Mirrors the actual ico pipeline (render at 192 → LANCZOS
to 48), then NEAREST-up to 256 so individual pixels are visible.
"""
from pathlib import Path

from PIL import Image

from generate_ico import render_svg

small = render_svg(192).resize((48, 48), Image.LANCZOS)
preview = small.resize((256, 256), Image.NEAREST)
out = Path(__file__).parent / "preview_small.png"
preview.save(out)
print(f"wrote {out}")
