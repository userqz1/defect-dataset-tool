"""Shared pytest fixtures.

``synthetic_dataset`` builds a real-on-disk 6-image / 2-category labeled
dataset and returns a ``Dataset`` pointing at it. Previously defined in
tests/test_exporters.py; moved here so all test files share one builder
instead of each rolling its own.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from core.models import Category, Dataset, ImageInfo


# -- Windows tmpdir hardening ------------------------------------------------
# Goal: make the suite pass on any Windows box regardless of antivirus / search
# indexer / onedrive / previous interrupted runs holding file locks on
# pytest's working directories.  The default basetemp
# (C:\Users\<user>\AppData\Local\Temp\pytest-of-<user>) is the source of
# most flakiness because:
#
#   * external processes keep file handles open on files pytest wrote;
#   * pytest's ``cleanup_numbered_dir`` / ``cleanup_dead_symlinks`` walk the
#     entire basetemp tree and re-raise on the first OSError;
#   * stale ``pytest-<N>`` directories from killed runs accumulate and
#     eventually poison future runs;
#   * ``make_numbered_dir`` retries mkdir at most 10 times — if something
#     keeps failing mkdir deterministically (OneDrive placeholder dir,
#     controlled folder access, read-only overlay), every tmp_path
#     fixture dies.
#
# Defense in depth, applied only on Windows:
#   1. Swallow OSError in every pytest cleanup hook (teardown path).
#   2. Replace ``find_prefixed`` with a version that tolerates per-entry
#      scandir errors (setup path, enumeration step).
#   3. Wrap ``make_numbered_dir`` so that if its own 10-try mkdir loop
#      fails, we fall back to ``tempfile.mkdtemp`` inside the same root —
#      ``mkdtemp`` is atomic in the kernel and doesn't care about
#      pre-existing numbered dirs.
#   4. Probe the project-local basetemp before committing to it: create
#      and delete a scratch sub-dir.  If that fails, leave basetemp at
#      pytest's default so it falls through to the system tempdir.
#   5. Probe that default too, and if everything is unhappy, point
#      basetemp explicitly at ``tempfile.gettempdir()`` as a last resort.
def pytest_configure(config):
    if sys.platform != "win32":
        return

    # --- Part 1: swallow OSError in every pytest cleanup hook ---
    import _pytest.pathlib as _pp

    def _wrap_swallow(mod, attr: str):
        """Replace ``mod.attr`` with a wrapper that calls it, ignoring
        OSError.  No-op if the attribute is missing on this pytest version.
        """
        orig = getattr(mod, attr, None)
        if orig is None or not callable(orig):
            return

        def _safe(*args, **kwargs):
            try:
                return orig(*args, **kwargs)
            except OSError:
                return None

        setattr(mod, attr, _safe)

    for attr in (
        "cleanup_dead_symlinks",
        "cleanup_numbered_dir",
        "try_cleanup",
        "rm_rf",
        "ensure_reset_dir",
    ):
        _wrap_swallow(_pp, attr)

    # --- Part 2: harden the SETUP path too, not just cleanup ---
    # Every test that uses ``tmp_path`` goes through
    # ``make_numbered_dir(root, prefix)`` → ``find_suffixes`` → ``find_prefixed``,
    # which calls ``os.scandir(root)`` on the basetemp.  If any entry in
    # basetemp is locked by AV/search indexer/OneDrive, the raw scandir
    # raises PermissionError and the fixture blows up before the test body
    # runs.  Replace ``find_prefixed`` with a generator that swallows OSError
    # per-entry and on scandir-open, so make_numbered_dir can always make
    # progress (worst case it picks ``<prefix>0`` and mkdir fails → retry
    # loop inside make_numbered_dir kicks in).
    import os as _os
    if hasattr(_pp, "find_prefixed"):
        def _safe_find_prefixed(root, prefix):
            l_prefix = prefix.lower()
            try:
                it = _os.scandir(root)
            except OSError:
                return
            with it:
                while True:
                    try:
                        entry = next(it)
                    except StopIteration:
                        return
                    except OSError:
                        continue  # locked entry — skip, keep iterating
                    try:
                        if entry.name.lower().startswith(l_prefix):
                            yield entry
                    except OSError:
                        continue

        _pp.find_prefixed = _safe_find_prefixed

    # --- Part 3: bulletproof make_numbered_dir ---
    # Even after fixing find_prefixed, the 10-retry mkdir loop inside
    # make_numbered_dir can still fail deterministically on certain
    # Windows configs (OneDrive placeholder dirs, Controlled Folder Access,
    # virus-scanner write-blockers, filesystem overlays).  Wrap it: if the
    # original returns or raises, fall back to ``tempfile.mkdtemp``, which
    # is a single kernel-level atomic op and doesn't read the parent
    # directory at all.  The returned path still lives under the same
    # ``root`` so pytest's downstream cleanup sees it where it expects to.
    import tempfile as _tempfile
    if hasattr(_pp, "make_numbered_dir"):
        _orig_make_numbered_dir = _pp.make_numbered_dir

        def _robust_make_numbered_dir(root, prefix, mode: int = 0o700):
            try:
                return _orig_make_numbered_dir(root, prefix, mode=mode)
            except (OSError, ValueError):
                pass
            # Fallback — mkdtemp picks a random suffix, doesn't need to
            # enumerate `root` and doesn't collide with existing entries.
            try:
                path_str = _tempfile.mkdtemp(prefix=prefix, dir=str(root))
            except OSError:
                # Last-ditch: skip the project-local root entirely and use
                # the system tempdir.  Tests that compare paths literally
                # would break here, but any test that just asks for
                # "somewhere writable" will succeed.
                path_str = _tempfile.mkdtemp(prefix=prefix)
            return Path(path_str)

        _pp.make_numbered_dir = _robust_make_numbered_dir
        # make_numbered_dir_with_cleanup internally calls make_numbered_dir
        # by name — re-patch the wrapper's binding too for older pytests
        # that imported the symbol at module load.
        if hasattr(_pp, "make_numbered_dir_with_cleanup"):
            import inspect
            try:
                src = inspect.getsource(_pp.make_numbered_dir_with_cleanup)
                if "make_numbered_dir(" in src:
                    # The function calls make_numbered_dir via the module
                    # global, so patching _pp.make_numbered_dir is enough.
                    pass
            except OSError:
                pass

    # _pytest.tmpdir re-imports some of these symbols — re-patch its copies.
    try:
        import _pytest.tmpdir as _td
        if hasattr(_td, "cleanup_dead_symlinks"):
            _td.cleanup_dead_symlinks = _pp.cleanup_dead_symlinks
        if hasattr(_td, "cleanup_numbered_dir"):
            _td.cleanup_numbered_dir = _pp.cleanup_numbered_dir
        if hasattr(_td, "find_prefixed"):
            _td.find_prefixed = _pp.find_prefixed
        if hasattr(_td, "make_numbered_dir"):
            _td.make_numbered_dir = _pp.make_numbered_dir
        if hasattr(_td, "make_numbered_dir_with_cleanup"):
            # Re-bind so tmpdir uses our robust version.
            _td.make_numbered_dir_with_cleanup = (
                _pp.make_numbered_dir_with_cleanup
            )
    except ImportError:
        pass

    # --- Part 4: pick a basetemp that actually works ---
    if config.option.basetemp is not None:
        return  # user passed --basetemp explicitly

    import os
    import shutil

    def _probe_writable(parent: Path) -> bool:
        """Confirm we can create *and actually remove* a sub-dir under
        ``parent``.  Returns True only if the probe dir was created **and**
        the filesystem reports it gone afterwards.

        The ``ignore_errors=True`` on ``rmtree`` is load-bearing (we don't
        want it to raise on Windows file-lock noise) but it silently
        swallows every failure mode — including the OneDrive placeholder /
        Controlled Folder Access case where the dir is "可见但不可稳定
        删除".  Without the post-rmtree existence check, we were
        committing basetemp to a parent whose children can be created but
        not cleaned up, exactly the state where ``make_numbered_dir``
        later fails deterministically.
        """
        try:
            probe = Path(_tempfile.mkdtemp(prefix=".probe_", dir=str(parent)))
        except OSError:
            return False
        shutil.rmtree(probe, ignore_errors=True)
        # If the probe directory still exists after rmtree, the parent is
        # unstable — treat it as non-writable and let the caller fall back.
        try:
            return not probe.exists()
        except OSError:
            return False

    project_root = Path(__file__).resolve().parent.parent
    tmp_parent = project_root / ".pytest_tmp"
    basetemp: Path | None = None

    # Preferred location: project-local .pytest_tmp/<pid>.
    try:
        tmp_parent.mkdir(exist_ok=True)
    except OSError:
        tmp_parent = None  # type: ignore[assignment]

    if tmp_parent is not None:
        # Best-effort cleanup of old per-PID directories from prior runs.
        try:
            old_entries = list(tmp_parent.iterdir())
        except OSError:
            old_entries = []
        for old in old_entries:
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)

        run_dir = tmp_parent / str(os.getpid())
        try:
            run_dir.mkdir(exist_ok=True)
            if _probe_writable(run_dir):
                basetemp = run_dir
        except OSError:
            basetemp = None

    # Fallback: system tempdir under a per-PID prefix.  ``mkdtemp`` here
    # gives us an isolated directory we fully own; no enumeration, no
    # collision with earlier runs.
    if basetemp is None:
        try:
            fallback = Path(_tempfile.mkdtemp(prefix=f"dataforge-pytest-{os.getpid()}-"))
            if _probe_writable(fallback):
                basetemp = fallback
        except OSError:
            basetemp = None

    # Final fallback: don't set basetemp at all — let pytest pick its
    # default (C:\Users\<user>\AppData\Local\Temp\pytest-of-<user>).  The
    # patched cleanup + setup hooks absorb the fallout either way.
    if basetemp is not None:
        config.option.basetemp = str(basetemp)


def _write_image(path: Path, color: tuple[int, int, int] = (200, 200, 100)) -> None:
    Image.new("RGB", (64, 64), color).save(path)


def _write_labelme(json_path: Path, image_path: Path, label: str) -> None:
    payload = {
        "version": "5.0.1",
        "shapes": [
            {
                "label": label,
                "points": [[8.0, 8.0], [40.0, 40.0]],
                "group_id": None,
                "shape_type": "rectangle",
                "flags": {},
            }
        ],
        "imagePath": image_path.name,
        "imageHeight": 64,
        "imageWidth": 64,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def synthetic_dataset(tmp_path: Path) -> Dataset:
    """Real-on-disk 6-image, 2-category, all-labeled dataset."""
    root = tmp_path / "raw"
    cats: list[Category] = []
    plan = [("cat", 4, (200, 100, 100)), ("dog", 2, (100, 200, 100))]
    for cls_name, n, color in plan:
        cat_dir = root / cls_name
        img_dir = cat_dir / "images"
        lbl_dir = cat_dir / "labels"
        img_dir.mkdir(parents=True)
        lbl_dir.mkdir(parents=True)

        images: list[ImageInfo] = []
        for i in range(n):
            ip = img_dir / f"{cls_name}_{i}.png"
            jp = lbl_dir / f"{cls_name}_{i}.json"
            _write_image(ip, color)
            _write_labelme(jp, ip, cls_name)
            images.append(ImageInfo(
                path=ip, category=cls_name,
                width=64, height=64,
                has_label=True, label_path=jp,
            ))
        cats.append(Category(
            name=cls_name, image_count=n, label_count=n, images=images,
        ))

    return Dataset(
        name="synthetic", root_path=root, categories=cats,
        total_images=6, total_annotations=6, layout="standard",
    )


@pytest.fixture
def empty_dataset(tmp_path: Path) -> Dataset:
    """Dataset with zero categories/images — for testing "not ready" branches."""
    return Dataset(
        name="empty", root_path=tmp_path / "empty",
        categories=[], total_images=0, total_annotations=0, layout="empty",
    )


@pytest.fixture
def unlabeled_dataset(tmp_path: Path) -> Dataset:
    """3 images, 2 categories, zero labels — tests the unlabeled path."""
    root = tmp_path / "raw_unlabeled"
    cats: list[Category] = []
    for cls_name, n, color in [("a", 2, (200, 100, 100)), ("b", 1, (100, 200, 100))]:
        img_dir = root / cls_name / "images"
        img_dir.mkdir(parents=True)
        images: list[ImageInfo] = []
        for i in range(n):
            ip = img_dir / f"{cls_name}_{i}.png"
            _write_image(ip, color)
            images.append(ImageInfo(path=ip, category=cls_name,
                                    width=64, height=64, has_label=False))
        cats.append(Category(name=cls_name, image_count=n, label_count=0, images=images))
    return Dataset(
        name="unlabeled", root_path=root, categories=cats,
        total_images=3, total_annotations=0, layout="standard",
    )
