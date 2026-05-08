# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
  - Data models: `models.py` (dataclasses: `Dataset`, `Category`, `ImageInfo`, `Annotation`, `Shape`), `unified.py` (unified SampleSet model bridging raw scan + workflow state).
  - Scanning: `dataset.py` (two-phase scan + layout detection), `index_cache.py` (SQLite cache).
  - Annotation: `annotation.py` (LabelMe parser), `annotation_formats.py` (multi-format), `annotation_writer.py` (write-back).
  - Format pipeline: `format_in.py` / `format_out.py` (read/write), `format_rt.py` (round-trip validation), `format_convert.py` / `format_migrate.py` (cross-format migration).
  - Workflow: `workflow.py` (sample-state machine), `workflow_store.py` (per-sample persistence), `inbox.py` (batch staging).
  - Processing: `quality.py`, `dedup.py`, `augment.py`, `transform.py`, `convert.py`, `predictor.py`, `splitter.py`, `task_readiness.py`.
  - Pipeline / ingest / schema: `pipeline/`, `ingest/`, `schema/` packages (run-config, file-ingest rules, per-format compliance).
  - Exporters: `exporter/{yolo,coco,voc,imagefolder,mvtec,subset,report,csv_export,jsonl,llava,sharegpt,swift}.py` — each behind a common interface.
  - Infrastructure: `config.py`, `project.py`, `recent.py`, `user_settings.py`, `fileops.py`, `stats.py`, `thumbnail_cache.py`, `history.py`, `api.py`, `task_types.py`.

- **`gui/`** — PyQt6 + qfluentwidgets.
  - `main_window.py` — `FluentWindow` with Home (`DatasetWelcome`) + Browser (`DatasetBrowserView`) on the nav rail; Settings is a floating popup (`SettingsView`); `OrganizeView` is on the stack but reached only from the 新数据 stage. Brand title bar (`BrandTitleBar`). Nav rail is **locked at 60px icon-only** via collapse + monkey-patched `panel.expand` no-op + `resizeEvent` re-collapse.
  - `views/` — `dataset_welcome.py` (recents + open/create), `organize_view.py` (ingest/organize helper), `dataset_browser_view.py` (3-column workbench shell), `browser_view.py` (grid + filter chips + pagination), `detail_view.py` (single-image shell), `detail_specs.py` (per-task-type pane spec), `panes/` (`image_label_pane.py`, `annotation_pane.py`, `vlm_pane.py`, `status_pane.py` — DetailView's task-typed sub-panes), `settings_view.py` (floating popup).
  - `widgets/` — Reusable components: `workspace_sidebar.py` (slim 5-row vertical stage nav with `StageIndex` constants), `context_panel.py` (right column shell, hosts catalog/inspector pages), `catalog_panel.py` + `category_tree.py` + `distribution_chart.py` (catalog page), `dataset_bar.py` (top strip + global toolbar: refresh/undo), `thumbnail_grid.py` (card grid + delegate), `image_viewer.py` (pan/zoom + shape overlay), `batch_list.py` (新数据 stage body), `review_hub.py` (审核修复 stage body — quality/dedup/stats), `delivery_hub.py` (数据交付 stage body — format/process/LLM/export), `project_manage_hub.py` (项目管理 stage body — meta + history), `llm_data_card.py`, `scope_badge.py`, `chips.py`, `preview_pane.py`, `brand_title_bar.py`.
  - `controllers/` — Browser-shell business logic, extracted from `DatasetBrowserView`: `browser_runtime.py` (shared context: state + bar + hub references + shell), `dataset_session_controller.py` (scan/refresh/worker lifecycle, gates `state.scan_active`), `browser_tool_controller.py` (executes hub `*_requested` signals via `BatchRunner`), `browser_chrome_controller.py` (context-panel page swap + detail drill in/out + sidebar↔stack sync), `workflow_controller.py` (sample-workflow orchestration on `MainWindow`).
  - `workers/` — QThread wrappers: `BatchWorker` (generic `fn(progress_cb)` runner), `BatchRunner` (worker + progress dialog + result handler), `ScanWorker` (dataset scan), `ThumbnailWorker` (lazy thumbnails).
  - `dialogs/` — Parameter-collection + progress dialogs: `op_dialogs.py` (progress, failure detail, move-to-category), `tool_dialogs.py` (quality / stats / dedup config + results), `batch_ops.py`, `history_dialog.py`, `export_wizard.py`, `export_validation_dialog.py`, `category_dialogs.py`, `project_dialogs.py`, `task_type_dialog.py` (task-type picker on first dataset open), `import_annot_dialog.py`, `convert_annot_dialog.py`, `migrate_format_dialog.py`, `llm_format_reference.py`.
  - `theme.py` + `styles/app.qss` + `i18n.py` — Three-layer styling system + minimal i18n.
  - `app_state.py` — Shared `AppState` (dataset + project + derived artifacts + `scan_active` gate), Qt-signal-based.

- **`config/default_config.yaml`** — Externalized config (cache paths, image extensions, theme).
- **`main.py`** — Entry point. App data dir: `~/.dataforge/`.

### Navigation & signal flow (IA v3.1)

```
MainWindow (FluentWindow, 60px icon-only nav rail)
├── Home (DatasetWelcome)
│   ├── Recents list + "open dataset" / "create project"
│   └── open_dataset(path, intent="") → switchTo(browser) → _apply_intent(intent)
├── Browser (DatasetBrowserView)         ← 3-column workbench shell
│   ├── Col 1 — WorkspaceSidebar (slim 168px stage nav, 5 rows)
│   ├── Col 2 — DatasetBar (title, path, stat pills, refresh/undo, catalog toggle, open)
│   │           + 5-stage stack (indexed via StageIndex):
│   │   ├── INBOX     (新数据)        — BatchListPanel
│   │   ├── ANNOTATE  (标注工作台)     — BrowserView ↔ DetailView (browser_stack)
│   │   ├── REVIEW    (审核修复)       — ReviewHub (quality / dedup / stats)
│   │   ├── DELIVERY  (数据交付)       — DeliveryHub (format / process / LLM / export)
│   │   └── MANAGE    (项目管理)       — ProjectManageHub (meta + history)
│   └── Col 3 — ContextPanel (collapsible 340px; catalog page on ANNOTATE, etc.)
└── Settings (SettingsView popup, bottom-left, NOT a route)
    └── theme_changed → _on_theme_changed()

OrganizeView is registered on the stack but NOT on the nav rail —
reached from the INBOX stage's "导入新批次" button (browser emits
request_organize_view → MainWindow switches to organize).
```

Signal wiring lives directly in `MainWindow.__init__()` and `DatasetBrowserView.__init__()` connecting view signals to controller/handler methods. There is no separate `_connect_signals()` method.

`DatasetBrowserView` is an assembly shell that delegates to four collaborators:

- **`BrowserRuntime`** — shared context object (state, dataset_bar, hub refs, shell window).
- **`DatasetSessionController`** — scan/refresh, worker spawning + cleanup, flips `state.set_scan_active(True/False)` around the worker so mutation tools stay disabled for the full Phase 1 + 2 + 3 lifecycle.
- **`BrowserToolController`** — handles each hub's `*_requested` signal; opens the matching config dialog (if any), then runs via `BatchRunner(parent, title).run(task=…, on_done=…)`.
- **`BrowserChromeController`** — context-panel page swap, detail drill-in/out, workspace-sidebar↔stage-stack sync.

`AppState` is the single source of truth for dataset + project + derived artifacts (quality issues, dedup groups, extended stats) plus the `scan_active` gate. Views subscribe via `dataset_changed` / `quality_changed` / `duplicates_changed` / `ext_stats_changed` and re-render from the state. Mutation surfaces (DetailView, hub action buttons) bind their enabled state to `state.can_write` so they don't race the scan worker.

### Key patterns

**Background workers**: All long-running ops go through `gui/workers/`. Pattern: `QThread` subclass with `progress(int, int, str)`, `finished_ok(result)`, `failed(str)` signals. `BatchWorker` is a generic wrapper accepting any `fn(progress_cb)` callable; `BatchRunner(parent, title).run(task=…, on_done=…)` is the one-line caller used by `BrowserToolController`.

**Dialogs don't execute ops**: Dialogs inherit `MessageBoxBase` (qfluentwidgets), expose `.options()` or `.get_values()` returning a dict/dataclass. The caller (a controller method) wraps the actual operation in a `BatchRunner`.

**Three-layer styling** (enforced by `style-cop` agent):
1. `gui/theme.py` — `Tokens` dataclass (colors, spacing, sizes) with LIGHT/DARK instances. Module-level proxy `T` always reflects current theme. `set_theme(name)` swaps the active instance.
2. qfluentwidgets semantic widgets + project custom widgets.
3. `gui/styles/app.qss` — single QSS file with `{TOKEN}` placeholders, substituted at runtime via `load_qss()`.

**Rule**: Never write `setStyleSheet(f"color:#xxx")` in views. All colors come from theme tokens.

**All dialogs/message boxes must use qfluentwidgets** — never native QDialog/QMessageBox.

**Dataset scan**: Two phases — (1) `scan_dataset()` enumerates files via `os.scandir` without parsing JSON, (2) `count_annotations()` optionally parses annotations. Results cached to SQLite via `index_cache.py`. `DatasetSessionController` flips `state.set_scan_active(True/False)` around the full Phase 1+2+3 lifecycle so mutation surfaces stay disabled.

**Thumbnails**: Lazy-loaded via `ThumbnailWorker` with on-disk cache (`diskcache`).

**Worker cleanup**: Before `deleteLater()`ing a view that owns a `ThumbnailWorker` / `ScanWorker`, stop the worker first — otherwise dangling thread references can segfault.

**DetailView is task-templated**: `views/detail_specs.py` holds per-task-type specs; `DetailView` assembles `image_label_pane` + `annotation_pane` + (optional) `vlm_pane` + `status_pane` from `Project.task_type`. Adding a new task type means adding a spec, not editing the view.

**Styling exceptions**: `gui/widgets/image_viewer.py:PALETTE` and `gui/widgets/category_tree.py:_EARTHEN`/`_NAMED` hold hex color literals. These are **category-identity** palettes (same colors must read against both light and dark themes), not theme colors; they are the only allowed hex-literal sites in `gui/`. All other colors must come from `gui.theme.T`.

### Adding a new processing operation

1. Create or extend `core/<feature>.py` (pure Python, `progress_cb` supported for anything > ~100ms).
2. Pick the owning stage hub and add a `<kind>_requested` signal + button:
   - **`ReviewHub`** — read-only quality / dedup / stats analyses.
   - **`DeliveryHub`** — output-producing actions (format conversion, process tools, LLM-data capabilities, dataset export).
   - **`ProjectManageHub`** — project-meta operations (history, settings).
3. Add a matching `run_<kind>` handler on `BrowserToolController`: open any config dialog, then run the core call via `BatchRunner(parent, title).run(task=…, on_done=…)`.
4. Wire the hub signal → controller method in `DatasetBrowserView.__init__()` (signal wiring is inline, not a separate method).
5. If it produces a derived artifact (quality issues, dedup groups, stats), store it on `AppState` via a `set_*` method so other views can subscribe.

## Gotchas

- **中文文字 / 图标控件禁止 `setFixedWidth`** —— 中文字符宽度是英文的 ~1.5×，固定宽度 95% 的情况会截字。`style-cop` agent 会扫这条。规则：
  - 文字按钮：用 `setMinimumWidth(N)` 或纯 `adjustSize()` / `sizeHint()` 自动撑开。**N 取最长 label 像素估算 + 24（icon + padding 余量）**
  - 图标 + 文字按钮：`setIcon(...)` 后**绝不**再 `setFixedWidth` —— icon 会吃掉文字空间
  - 自定义 delegate 在 `paint()` 里 `drawText` 必须留 ≥8px padding，不能贴边
  - QSS 每个 text-bearing 选择器最少 `padding: 4px 8px`；`padding: 0` / `1px` / `2px` 一律警告
  - **`setFixedHeight` 可以**（中英文行高一样），**`setFixedWidth` 几乎一定不行**
  - 违反这条比破坏三层样式严重 —— 用户每次都看见。
- **Chinese paths**: Always use `pathlib.Path`, never byte strings.
- **Mismatched image/label pairs**: Flag them, don't crash.
- **Annotation schema drift**: Parser must be tolerant of malformed JSON and record failures.
- **SSL/proxy on this machine**: Unset `HTTP_PROXY`/`HTTPS_PROXY` before pip/conda installs; use Tsinghua mirrors.
- **Config is read-once**: `core/config.load()` is `@lru_cache(maxsize=1)`. Changes need app restart.
- **Hub buttons require a loaded dataset**: ReviewHub + DeliveryHub + ProjectManageHub action buttons + DatasetBar refresh are gated off `AppState.dataset.total_images > 0`. Capability checkboxes on DeliveryHub gate separately on `project is not None` — a project can be reconfigured before the scan lands.
- **Mutation tools gate on `scan_active`**: `state.can_write` is False while the scan worker runs; DetailView edits and every `*_requested` handler must respect this so we don't race the scan.
- **Window geometry**: Set on the first `showEvent` (deferred one tick) so `screen()` reports the actual landing screen on multi-monitor setups; eagerly sizing in `__init__` always picks primary.
- **Nav rail is icon-only**: Permanently 60px via `panel.collapse()` + monkey-patched `panel.expand` no-op + `resizeEvent` re-collapse. Old auto-expand-at-1100px behavior is gone.
