"""On-disk thumbnail cache. Pure Python — no PyQt."""
from __future__ import annotations

import logging
from pathlib import Path

import diskcache
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path.home() / ".dataforge" / "thumbnails"


class ThumbnailCache:
    def __init__(self, cache_dir: Path | None = None, size_gb: float = 2.0) -> None:
        cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = diskcache.Cache(str(cache_dir), size_limit=int(size_gb * 1024**3))

    @staticmethod
    def _key(path: Path, size: int) -> str:
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        return f"{path}|{mtime}|{size}"

    def get_or_generate(self, path: Path, size: int = 170) -> bytes | None:
        """Return JPEG bytes of a thumbnail, generating + caching if missing."""
        key = self._key(path, size)
        data = self._cache.get(key)
        if data is not None:
            return data  # type: ignore[return-value]
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((size, size), Image.Resampling.LANCZOS)
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                import io
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=85)
                data = buf.getvalue()
        except Exception:
            logger.exception("thumbnail generation failed for %s", path)
            return None
        self._cache.set(key, data)
        return data

    def get_dimensions(self, path: Path) -> tuple[int, int] | None:
        """Return (w, h) reading only the header — cheap."""
        key = f"dim|{path}|{path.stat().st_mtime_ns if path.exists() else 0}"
        dim = self._cache.get(key)
        if dim is not None:
            return dim  # type: ignore[return-value]
        try:
            with Image.open(path) as im:
                dim = im.size  # (w, h)
        except Exception:
            logger.warning("could not read dimensions of %s", path, exc_info=True)
            return None
        self._cache.set(key, dim)
        return dim

    def volume(self) -> int:
        """Approximate on-disk size in bytes."""
        try:
            return int(self._cache.volume())
        except Exception:
            logger.exception("thumbnail cache volume() failed")
            return 0

    def clear(self) -> int:
        """Drop all cached entries. Returns number of items removed."""
        try:
            return int(self._cache.clear())
        except Exception:
            logger.exception("thumbnail cache clear() failed")
            return 0

    def close(self) -> None:
        self._cache.close()
