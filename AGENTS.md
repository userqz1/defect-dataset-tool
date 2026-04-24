# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project

**数据坊 (DataForge)** — A Windows desktop tool (Python 3.11 + PyQt6 + qfluentwidgets) for managing image datasets across CV task types (classification, detection, segmentation, anomaly detection). The tool covers three dataset lifecycle stages: **fresh** (raw images, no labels), **semi-finished** (partial labels), **existing** (fully labeled — format conversion, augmentation, re-split, LLM-dataset export).

Annotation formats: LabelMe JSON (primary), YOLO, Pascal VOC, COCO. Expected disk layout: `<root>/<category>/images/` + `<root>/<category>/labels/` (auto-detected; also handles flat, single-category, and recursive layouts).

App data lives in `~/.dataforge/` (project metadata, cache, settings).

## Commands

The project uses a conda env named `defect-tool`. Conda is not on PATH; use the env's python directly:

```bash
# Run the app
C:/ProgramData/miniconda3/envs/defect-tool/python.exe main.py

# Install deps (unset proxy first to avoid SSL errors)
unset HTTP_PROXY HTTPS_PROXY
C:/ProgramData/miniconda3/envs/defect-tool/python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

No test suite exists yet. When added, use pytest.

## Architecture (must follow)

### Core invariant

**`core/` is pure Python — no PyQt, no GUI imports.** This enables reuse for CLI/Web frontends. The `core-guardian` agent audits this.

### Layers

- **`core/`** — Domain logic, zero GUI dependencies.
  - Data models: `models.py` (dataclasses: `Dataset`, `Category`, `ImageInfo`, `Annotation`, `Shape`).
  - Scanning: `dataset.py` (two-phase scan + layout detection), `index_cache.py` (SQLite cache).
  - Annotation: `annotation.py` (LabelMe parser), `annotation_formats.py` (multi-format), `annotation_writer.py` (write-back).
  - Processing: `quality.py`, `dedup.py`, `augment.py`, `transform.py`, `convert.py`, `predictor.py`, `splitter.py`, `task_readiness.py`.
  - Pipeline / ingest / schema: `pipeline/`, `ingest/`, `schema/` packages (run-config, file-ingest rules, per-format compliance).
  - Exporters: `exporter/{yolo,coco,voc,subset,report,csv_export,jsonl,llava,sharegpt,swift}.py` — each behind a common interface.
  - Infrastructure: `config.py`, `project.py`, `recent.py`, `user_settings.py`, `fileops.py`, `stats.py`, `thumbnail_cache.py`, `history.py`, `api.py`, `task_types.py`.

- **`gui/`** — PyQt6 + qfluentwidgets.
  - `main_window.py` — `FluentWindow` with Home (`DatasetWelcome`), Organize (`organize_view`), Browser (`DatasetBrowserView`), plus a Settings popup (`settings_view`).
  - `views/` — `dataset_welcome.py` (recents + open/create), `organize_view.py` (ingest/organize helper), `dataset_browser_view.py` (outer shell: top bar + category catalog + browser + detail), `browser_view.py` (grid + filter chips + pagination), `detail_view.py` (single-image viewer + annotation editor), `settings_view.py` (floating popup).
  - `widgets/` — Reusable components: `thumbnail_grid.py` (card grid + delegate), `image_viewer.py` (pan/zoom + shape overlay), `category_tree.py`, `catalog_panel.py`, `dataset_bar.py`, `distribution_chart.py`, `brand_title_bar.py`, `tool_sidebar.py`, `chips.py`, `preview_pane.py`.
  - `workers/` — QThread wrappers: `BatchWorker` (generic `fn(progress_cb)` runner), `BatchRunner` (worker + progress dialog + result handler), `ScanWorker` (dataset scan), `ThumbnailWorker` (lazy thumbnails).
  - `dialogs/` — Parameter-collection + progress dialogs: `op_dialogs.py` (progress, failure detail, move-to-category), `tool_dialogs.py` (quality / stats / dedup config + results), `batch_ops.py`, `history_dialog.py`, `export_wizard.py`, `export_validation_dialog.py`, `category_dialogs.py`, `task_type_dialog.py` (task-type picker on first dataset open).
  - `theme.py` + `styles/app.qss` + `i18n.py` — Three-layer styling system + minimal i18n.
  - `app_state.py` — Shared `AppState` (dataset + project + derived artifacts), Qt-signal-based.

- **`config/default_config.yaml`** — Externalized config (cache paths, image extensions, theme).
- **`main.py`** — Entry point. App data dir: `~/.dataforge/`.

### Navigation & signal flow

```
MainWindow (FluentWindow)
├── Home (DatasetWelcome)
│   ├── Recents list + "open dataset" / "create project"
│   └── open_dataset(path, task_type) → _open_dataset() → switchTo(browser)
├── Organize (OrganizeView)
│   └── File-ingest helper (copy/rename into the <root>/<cat>/ structure)
├── Browser (DatasetBrowserView)
│   ├── DatasetBar (top strip: title, path, stat pills, open/analyse buttons)
│   ├── ToolSidebar (analysis / process / output / other groups)
│   ├── CatalogPanel (category tree + distribution chart)
│   ├── BrowserView (grid + filter chips + pagination)  ← browser_stack idx 0
│   └── DetailView (single-image viewer + annotation editor) ← browser_stack idx 1
└── Settings (SettingsView popup)
    └── theme_changed → _on_theme_changed()
```

Signal wiring lives directly in `MainWindow.__init__()` and `DatasetBrowserView.__init__()` connecting view signals to handler methods. There is no separate `_connect_signals()` method.

`AppState` is the single source of truth for dataset + project + derived artifacts (quality issues, dedup groups, extended stats). Views subscribe via `dataset_changed` / `quality_changed` / `duplicates_changed` / `ext_stats_changed` and re-render from the state.

### Key patterns

**Background workers**: All long-running ops go through `gui/workers/`. Pattern: `QThread` subclass with `progress(int, int, str)`, `finished_ok(result)`, `failed(str)` signals. `BatchWorker` is a generic wrapper accepting any `fn(progress_cb)` callable.

**Dialogs don't execute ops**: Dialogs inherit `MessageBoxBase` (qfluentwidgets), expose `.options()` or `.get_values()` returning a dict/dataclass. The caller wraps the actual operation in a `BatchWorker`.

**Three-layer styling** (enforced by `style-cop` agent):
1. `gui/theme.py` — `Tokens` dataclass (colors, spacing, sizes) with LIGHT/DARK instances. Module-level proxy `T` always reflects current theme. `set_theme(name)` swaps the active instance.
2. qfluentwidgets semantic widgets + project custom widgets.
3. `gui/styles/app.qss` — single QSS file with `{TOKEN}` placeholders, substituted at runtime via `load_qss()`.

**Rule**: Never write `setStyleSheet(f"color:#xxx")` in views. All colors come from theme tokens.

**All dialogs/message boxes must use qfluentwidgets** — never native QDialog/QMessageBox.

**Dataset scan**: Two phases — (1) `scan_dataset()` enumerates files via `os.scandir` without parsing JSON, (2) `count_annotations()` optionally parses annotations. Results cached to SQLite via `index_cache.py`.

**Thumbnails**: Lazy-loaded via `ThumbnailWorker` with on-disk cache (`diskcache`).

**Worker cleanup**: Before `deleteLater()`ing a view that owns a `ThumbnailWorker` / `ScanWorker`, stop the worker first — otherwise dangling thread references can segfault.

**Styling exceptions**: `gui/widgets/image_viewer.py:PALETTE` and `gui/widgets/category_tree.py:_EARTHEN`/`_NAMED` hold hex color literals. These are **category-identity** palettes (same colors must read against both light and dark themes), not theme colors; they are the only allowed hex-literal sites in `gui/`. All other colors must come from `gui.theme.T`.

### Adding a new processing operation

1. Create or extend `core/<feature>.py` (pure Python, `progress_cb` supported for anything > ~100ms).
2. Hook it into the UI from `DatasetBrowserView` — usually as a toolbar button that opens a config dialog (`gui/dialogs/tool_dialogs.py`) and runs via `BatchRunner(parent, title).run(task=…, on_done=…)`.
3. If it produces a derived artifact (quality issues, dedup groups, stats), store it on `AppState` via a `set_*` method so other views can subscribe.

## Gotchas

- **Chinese paths**: Always use `pathlib.Path`, never byte strings.
- **Mismatched image/label pairs**: Flag them, don't crash.
- **Annotation schema drift**: Parser must be tolerant of malformed JSON and record failures.
- **SSL/proxy on this machine**: Unset `HTTP_PROXY`/`HTTPS_PROXY` before pip/conda installs; use Tsinghua mirrors.
- **Config is read-once**: `core/config.load()` is `@lru_cache(maxsize=1)`. Changes need app restart.
- **Tool clicks require a loaded dataset**: Sidebar tool buttons are disabled until `AppState.dataset` has `total_images > 0`.
- **Nav rail auto-collapse**: Sidebar collapses/expands at 1100px window width threshold.
