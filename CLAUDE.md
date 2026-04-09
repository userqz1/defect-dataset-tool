# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**数据坊 (DataForge)** — A Windows desktop tool (Python 3.11 + PyQt6 + qfluentwidgets) for managing defect-annotation datasets. Users scan a dataset directory, browse images by category, view/edit LabelMe annotations, compute statistics, run quality checks, deduplicate, augment, split, and export to YOLO/COCO/VOC formats.

Primary input: **LabelMe JSON**. Expected disk layout: `<root>/<category>/images/` + `<root>/<category>/labels/` (auto-detected; also handles flat, single-category, and recursive layouts).

## Commands

The project uses a conda env named `defect-tool`. Conda is not on PATH; use the env's python directly:

```bash
# Run the app
C:/Users/zq/miniconda3/envs/defect-tool/python.exe main.py

# Install deps (unset proxy first to avoid SSL errors)
unset HTTP_PROXY HTTPS_PROXY
C:/Users/zq/miniconda3/envs/defect-tool/python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

No test suite exists yet. When added, use pytest.

## Architecture (must follow)

### Core invariant

**`core/` is pure Python — no PyQt, no GUI imports.** This enables reuse for CLI/Web frontends. The `core-guardian` agent audits this.

### Layers

- **`core/`** — Domain logic. `models.py` (dataclasses: `Dataset`, `Category`, `ImageInfo`, `Annotation`, `Shape`), `dataset.py` (scan + layout detection), `annotation.py` (LabelMe parser), `annotation_writer.py` (write-back), `stats.py`, `quality.py`, `dedup.py`, `splitter.py`, `augment.py`, `transform.py`, `convert.py`, `predictor.py`, `exporter/{yolo,coco,voc,subset,report}.py`. Each exporter is a separate file behind a common interface.
- **`gui/`** — PyQt6 + qfluentwidgets. `main_window.py` (FluentWindow with grouped sidebar navigation + back/forward history), `views/` (one per feature), `widgets/` (reusable components), `workers/` (QThread wrappers), `dialogs/` (parameter-collection dialogs), `theme.py` + `styles/app.qss`.
- **`config/default_config.yaml`** — Externalized config (cache paths, image extensions, theme).
- **`main.py`** — Entry point.

### Key patterns

**Signal-driven wiring**: `MainWindow._build_views()` instantiates views; `_connect_signals()` wires them together (view signals → workers → view slots). Views never call workers directly.

**Background workers**: All long-running ops go through `gui/workers/`. Pattern: `QThread` subclass with `progress(int, int, str)`, `finished_ok(result)`, `failed(str)` signals. `BatchWorker` is a generic wrapper accepting any `fn(progress_cb)` callable.

**Dialogs don't execute ops**: `gui/dialogs/op_dialogs.py` dialogs inherit `MessageBoxBase`, expose `.options()` returning a dataclass. The caller wraps the actual operation in a `BatchWorker`.

**Three-layer styling** (enforced by `style-cop` agent):
1. `gui/theme.py` — `Tokens` dataclass (colors, spacing, sizes) with LIGHT/DARK instances. Module-level proxy `T` always reflects current theme.
2. qfluentwidgets semantic widgets + project custom widgets.
3. `gui/styles/app.qss` — single QSS file with `{TOKEN}` placeholders, substituted at runtime via `load_qss()`.

**Rule**: Never write `setStyleSheet(f"color:#xxx")` in views. All colors come from theme tokens.

**All dialogs/message boxes must use qfluentwidgets** — never native QDialog/QMessageBox.

**Dataset scan**: Two phases — (1) `scan_dataset()` enumerates files via `os.scandir` without parsing JSON, (2) `count_annotations()` optionally parses LabelMe annotations. Results cached to SQLite via `index_cache.py`.

**Thumbnails**: Lazy-loaded via `ThumbnailWorker` with on-disk cache (`diskcache`).

### Adding a new view

1. Create `core/<feature>.py` (pure Python).
2. Create `gui/views/<feature>_view.py` inheriting from a qfluentwidgets base.
3. Register in `MainWindow._build_views()` with `addSubInterface()`.
4. Wire signals in `_connect_signals()`.
5. Use the `/wire` skill to automate this.

## Gotchas

- **Chinese paths**: Always use `pathlib.Path`, never byte strings.
- **Mismatched image/label pairs**: Flag them, don't crash.
- **LabelMe schema drift**: Parser must be tolerant of malformed JSON and record failures.
- **SSL/proxy on this machine**: Unset `HTTP_PROXY`/`HTTPS_PROXY` before pip/conda installs; use Tsinghua mirrors.
- **Config is read-once**: `core/config.load()` is `@lru_cache(maxsize=1)`. Changes need app restart.

## Reference

Full design rationale, data models, and phased feature list in `解决方案.md`. Read sections 三 (directory layout), 六 (data models), and 九 (extensibility) before non-trivial changes.
