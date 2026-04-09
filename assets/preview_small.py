"""Quick preview: export the simplified 48px icon as a viewable PNG."""
from PIL import Image
from pathlib import Path
from generate_ico import _draw_icon

big = _draw_icon(48 * 4, simplified=True)
small = big.resize((48, 48), Image.LANCZOS)
# Scale up for visibility
preview = small.resize((256, 256), Image.NEAREST)
out = Path(__file__).parent / "preview_small.png"
preview.save(out)
print(f"wrote {out}")
