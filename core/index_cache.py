"""SQLite index cache for fast dataset reopen.

Schema:
    datasets(root TEXT PK, scanned_at REAL, fingerprint TEXT,
             total_images INT, total_annotations INT)
    images(root TEXT, category TEXT, path TEXT,
           has_label INT, label_path TEXT,
           PRIMARY KEY(root, path))

Fingerprint = sha1(sorted top-level directory mtimes). Recompute fast; if it
changes since the last scan, the cache is treated as stale.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from .models import Category, Dataset, ImageInfo

DEFAULT_DB = Path.home() / ".dataforge" / "index.sqlite"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or DEFAULT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS datasets (
            root TEXT PRIMARY KEY,
            scanned_at REAL,
            fingerprint TEXT,
            total_images INTEGER,
            total_annotations INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS images (
            root TEXT,
            category TEXT,
            path TEXT,
            has_label INTEGER,
            label_path TEXT,
            PRIMARY KEY(root, path)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_root_cat ON images(root, category)")
    return conn


def compute_fingerprint(root: Path) -> str:
    """Signature: sha1 over two-level subdir mtimes (root → cat → images/labels).

    Covers the common case where files are added/removed in
    ``<root>/<cat>/images/`` or ``<root>/<cat>/labels/``.
    """
    h = hashlib.sha1()
    try:
        for p in sorted(root.iterdir()):
            if not p.is_dir():
                continue
            try:
                h.update(f"{p.name}|{p.stat().st_mtime_ns}".encode())
                # Second level: images/ and labels/ subdirs
                for child in sorted(p.iterdir()):
                    if child.is_dir():
                        try:
                            h.update(f"{p.name}/{child.name}|{child.stat().st_mtime_ns}".encode())
                        except OSError:
                            continue
            except OSError:
                continue
    except OSError:
        pass
    return h.hexdigest()


def save(dataset: Dataset, db_path: Path | None = None) -> None:
    conn = _connect(db_path)
    try:
        root = str(dataset.root_path)
        fp = compute_fingerprint(dataset.root_path)
        conn.execute("DELETE FROM datasets WHERE root = ?", (root,))
        conn.execute("DELETE FROM images WHERE root = ?", (root,))
        conn.execute(
            "INSERT INTO datasets VALUES (?, ?, ?, ?, ?)",
            (root, time.time(), fp, dataset.total_images, dataset.total_annotations),
        )
        rows = []
        for cat in dataset.categories:
            for img in cat.images:
                rows.append(
                    (
                        root,
                        cat.name,
                        str(img.path),
                        1 if img.has_label else 0,
                        str(img.label_path) if img.label_path else None,
                    )
                )
        conn.executemany("INSERT INTO images VALUES (?, ?, ?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


def load(root: Path, db_path: Path | None = None) -> Dataset | None:
    """Return cached Dataset if fingerprint matches; else None."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT scanned_at, fingerprint, total_images, total_annotations FROM datasets WHERE root = ?",
            (str(root),),
        ).fetchone()
        if row is None:
            return None
        _, stored_fp, total_images, total_annotations = row
        if stored_fp != compute_fingerprint(root):
            return None  # stale

        cur = conn.execute(
            "SELECT category, path, has_label, label_path FROM images WHERE root = ? ORDER BY category, path",
            (str(root),),
        )
        cat_map: dict[str, list[ImageInfo]] = {}
        for category, path_str, has_label, label_path in cur.fetchall():
            img = ImageInfo(
                path=Path(path_str),
                category=category,
                has_label=bool(has_label),
                label_path=Path(label_path) if label_path else None,
            )
            cat_map.setdefault(category, []).append(img)

        categories = []
        for name, imgs in cat_map.items():
            label_count = sum(1 for i in imgs if i.has_label)
            categories.append(
                Category(
                    name=name,
                    image_count=len(imgs),
                    label_count=label_count,
                    images=imgs,
                )
            )
        return Dataset(
            name=root.name,
            root_path=root,
            categories=sorted(categories, key=lambda c: c.image_count, reverse=True),
            total_images=total_images,
            total_annotations=total_annotations,
        )
    finally:
        conn.close()


def clear(root: Path, db_path: Path | None = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM datasets WHERE root = ?", (str(root),))
        conn.execute("DELETE FROM images WHERE root = ?", (str(root),))
        conn.commit()
    finally:
        conn.close()
