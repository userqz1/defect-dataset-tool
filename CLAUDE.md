# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**数据坊 (DataForge)** — A Windows desktop tool (Python 3.11 + PyQt6 + qfluentwidgets) for managing image datasets across CV task types (classification, detection, segmentation, anomaly detection). Users build visual processing pipelines on an n8n-style node canvas: drag tool nodes (quality check, dedup, augment, split, export…) onto a canvas, connect them, configure parameters, and execute.

Annotation formats: LabelMe JSON (primary), YOLO, Pascal VOC, COCO. Expected disk layout: `<root>/<category>/images/` + `<root>/<category>/labels/` (auto-detected; also handles flat, single-category, and recursive layouts).

App data lives in `~/.dataforge/` (schemes, cache, settings).

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

- **`core/`** — Domain logic, zero GUI dependencies.
  - Data models: `models.py` (dataclasses: `Dataset`, `Category`, `ImageInfo`, `Annotation`, `Shape`).
  - Scanning: `dataset.py` (two-phase scan + layout detection), `index_cache.py` (SQLite cache).
  - Annotation: `annotation.py` (LabelMe parser), `annotation_formats.py` (multi-format), `annotation_writer.py` (write-back).
  - Processing: `quality.py`, `dedup.py`, `augment.py`, `transform.py`, `convert.py`, `predictor.py`, `splitter.py`.
  - Node system: `nodes.py` (ProcessingNode protocol + NODES registry), `pipeline.py` (graph execution engine), `scheme.py` (scheme serialization).
  - Exporters: `exporter/{yolo,coco,voc,subset,report,csv_export,jsonl,llava,sharegpt,swift}.py` — each behind a common interface.
  - Infrastructure: `config.py`, `project.py`, `recent.py`, `user_settings.py`, `fileops.py`, `stats.py`, `compliance.py`, `format_grid.py`, `task_types.py`, `standards.py`, `thumbnail_cache.py`.

- **`gui/`** — PyQt6 + qfluentwidgets.
  - `main_window.py` — `FluentWindow` with three primary interfaces: Home (SchemeWelcome), Editor (PipelineView), Settings. Tools sidebar populated dynamically from `core.nodes.NODES`.
  - `views/` — One per feature. Primary views: `scheme_welcome_view.py` (home/scheme manager), `pipeline_view.py` (node canvas editor), `settings_view.py`. Node workspace views (opened via double-click on canvas node): `augment_view`, `cleaning_view`, `dedup_view`, `export_view`, `predict_view`, `quality_view`, `split_view`, `standards_view`, `transform_view`.
  - `widgets/` — Reusable components. Most important: `node_editor.py` (NodeCanvas, NodeItem, PortItem, ConnectionItem — the entire n8n-style graph editor, ~34K).
  - `workers/` — QThread wrappers: `BatchWorker` (generic), `ScanWorker` (dataset scan), `ThumbnailWorker` (lazy thumbnails).
  - `dialogs/` — Parameter-collection dialogs. `node_config_dialog.py` (per-node config forms), `op_dialogs.py` (progress, transform ops), `category_dialogs.py`, `export_validation_dialog.py`.
  - `theme.py` + `styles/app.qss` — Three-layer styling system.

- **`config/default_config.yaml`** — Externalized config (cache paths, image extensions, theme).
- **`main.py`** — Entry point. App data dir: `~/.dataforge/`.

### Navigation & signal flow

```
MainWindow (FluentWindow)
├── Home (SchemeWelcome)
│   ├── New scheme → _new_scheme() → enters editor with blank canvas
│   ├── Open scheme → _open_scheme(path) → deserializes JSON, populates canvas
│   └── Use template → _use_template(idx)
├── Editor (PipelineView)
│   ├── NodeCanvas (graph editing surface)
│   │   ├── NodeItem(s) — draggable, double-click → open workspace
│   │   └── ConnectionItem(s) — Bézier curves between ports
│   └── Workspace views (stacked, one per node type)
├── Tools sidebar group
│   └── Each tool → _tool_click() → creates NodeItem on canvas (requires active scheme)
└── Settings (SettingsView)
    └── theme_changed → _on_theme_changed()
```

Signal wiring lives directly in `MainWindow.__init__()` connecting view signals to handler methods. There is no separate `_connect_signals()` method.

### Node system (`core/nodes.py`)

Each processing step implements the `ProcessingNode` protocol:
- `PortDef` (name, label, direction, data_type) — defines input/output ports.
- `ParamDef` (name, label, type, default, choices, min/max) — defines configurable parameters.
- `StepResult` (ok_count, fail_count, output_paths, details) — execution result.
- Concrete nodes: `DataSourceNode`, `QualityCheckNode`, `DedupNode`, `AugmentNode`, `PredictNode`, `SplitNode`, `ExportNode`.
- All registered in global `NODES: dict[str, ProcessingNode]`.

### Scheme persistence (`core/scheme.py`)

Schemes serialize the canvas state (nodes + connections + positions) to JSON in `~/.dataforge/schemes/<name>.json`. Dataclasses: `Scheme`, `SchemeNode`, `SchemeConnection`.

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

**Pipeline-first execution**: Only the canvas "执行流程" button runs processing. Workspace views are for config + result display, not independent execution. `GraphEngine` topologically sorts nodes, executes each, routes data between ports.

**Workspace param sync**: Each workspace view implements `get_params() → dict` and `set_params(dict)`. Params sync to `NodeItem._params` when returning to canvas (`_back_to_canvas`) and before saving (`_on_save_clicked`). When opening a workspace, `NodeItem.params` are pushed into the UI via `set_params()`.

**Worker cleanup**: `clear_workspaces()` must stop `ThumbnailWorker` and `ScanWorker` before `deleteLater()` to avoid segfaults from dangling thread references.

### Adding a new processing node

1. Create or extend `core/<feature>.py` (pure Python).
2. Add a `ProcessingNode` implementation in `core/nodes.py` with ports, params, and `execute()`.
3. Register in the `NODES` dict — it auto-appears in the sidebar tools group.
4. If the node needs a dedicated workspace view, create `gui/views/<feature>_view.py` and register it in the editor's workspace stack.
5. Add a node config builder in `gui/dialogs/node_config_dialog.py` (`_BUILDERS` dict).

### Node canvas internals (`gui/widgets/node_editor.py`)

- `NodeCanvas(QGraphicsView)` — 20px dot grid, zoom controls, context menu, drag-to-connect.
- `NodeItem(QGraphicsItem)` — 160px wide, category-colored header, dynamic ports, states (idle/running/done/error), 20px grid snapping.
- `PortItem(QGraphicsEllipseItem)` — Input (left) / output (right), 15px hit area, visual highlight on hover/connect.
- `ConnectionItem(QGraphicsPathItem)` — Cubic Bézier between ports, 8px hit area, selectable + deletable.

## Gotchas

- **Chinese paths**: Always use `pathlib.Path`, never byte strings.
- **Mismatched image/label pairs**: Flag them, don't crash.
- **Annotation schema drift**: Parser must be tolerant of malformed JSON and record failures.
- **SSL/proxy on this machine**: Unset `HTTP_PROXY`/`HTTPS_PROXY` before pip/conda installs; use Tsinghua mirrors.
- **Config is read-once**: `core/config.load()` is `@lru_cache(maxsize=1)`. Changes need app restart.
- **Tool clicks require active scheme**: Sidebar tool clicks only work when `_scheme_active=True`; otherwise an info bar prompts the user to create a scheme first.
- **Nav rail auto-collapse**: Sidebar collapses/expands at 1100px window width threshold.

## Reference

Full design rationale, data models, and phased feature list in `解决方案.md`. Read sections 三 (directory layout), 六 (data models), and 九 (extensibility) before non-trivial changes.
