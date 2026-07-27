# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

> Kept in sync with `CLAUDE.md` — the two files describe the same architecture. If you
> change one, change the other. Only the "Git / GitHub uploads" section below is
> Codex-specific.

## Project

**数据坊 (DataForge)** — A Windows desktop tool (Python 3.11 + PyQt6 + qfluentwidgets) for managing image datasets across CV task types. The tool covers three dataset lifecycle stages: **fresh** (raw images, no labels), **semi-finished** (partial labels), **existing** (fully labeled — format conversion, augmentation, re-split, LLM-dataset export).

`core/task_types.py:TASK_REGISTRY` is the authoritative task list — **9 task types**, not the 4 the README's feature table implies: classification, multi_label, anomaly_detection, object_detection, **oriented_detection**, semantic_segmentation, instance_segmentation, keypoint_detection, image_pair. Each `TaskTypeInfo` declares `annotation_level` / `needs_shapes` / `needs_image_label` / `valid_shape_types` / `export_formats` / `augment_updates_shapes`; downstream code branches on those fields rather than on the enum member, so adding a task type is a registry entry plus a `detail_specs.py` spec.

Annotation formats: LabelMe JSON (primary), YOLO, Pascal VOC, COCO. Expected disk layout: `<root>/<category>/images/` + `<root>/<category>/labels/` (auto-detected; also handles flat, single-category, and recursive layouts).

App data lives in `~/.dataforge/` (project metadata, cache, settings).

## Commands

The project uses a conda env named `defect-tool` (Python 3.11), with conda on PATH (`condabin`). Use `conda run -n defect-tool` — portable, no hardcoded path (`--no-capture-output` streams output live, which matters for the GUI app and pytest):

```bash
# Run the app
conda run --no-capture-output -n defect-tool python main.py

# Install deps (unset proxy first to avoid SSL errors)
unset HTTP_PROXY HTTPS_PROXY
conda run -n defect-tool python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Run the test suite (pytest config lives in pyproject.toml: testpaths=tests, pythonpath=.)
conda run --no-capture-output -n defect-tool python -m pytest

# Run a single test file / test
conda run --no-capture-output -n defect-tool python -m pytest tests/test_splitter.py
conda run --no-capture-output -n defect-tool python -m pytest tests/test_splitter.py::test_name -q

# Lint (ruff config in pyproject.toml: line-length 100, py311 target)
# NOTE: ruff ships in the `dev` extra and is NOT installed in the env by default —
# `python -m ruff` fails with "No module named ruff" until you install it:
conda run -n defect-tool python -m pip install -e ".[dev]"
conda run -n defect-tool python -m ruff check .
```

If a long-lived shell (e.g. the agent's) doesn't recognize `conda` — a stale PATH snapshot from before conda was added — reload PATH from the registry first (portable, no hardcoded path):
`$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`

CI (`.github/workflows/ci.yml`, windows-latest, push + PR to `main`) installs via `pip install -e ".[dev]"` then runs `python -m compileall -q core gui main.py` and `pytest tests/ -v`. **CI does not run ruff** — lint locally or it never gets checked.

### Tests

Tests live in `tests/`, are almost all `core/` unit tests (e.g. `test_splitter.py`, `test_exporters.py`, `test_format_migrate.py`, `*_roundtrip.py` for the LLM-dataset formats), and new `core/` modules should ship a matching `tests/test_<module>.py`.

Two things about the suite that aren't obvious:

- **A GUI module *can* be tested when the code under test is pure.** `tests/test_shape_conventions.py` imports `gui.views.detail_view` for its `_region_to_shape` / `_shape_to_region` bridge — dataclasses in, dataclasses out, no display needed. The recipe is `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` + `pytest.importorskip("PyQt6", …)` before the `gui` import, so the file skips cleanly where PyQt is absent. Widget behaviour is still untested; only pure functions that happen to live under `gui/` are fair game.
- **`tests/conftest.py` owns the dataset fixtures** — `synthetic_dataset` (6 images / 2 categories / fully labeled, real files on disk), `empty_dataset`, `unlabeled_dataset`. Use them instead of rolling a new builder. The same file carries a large Windows tmpdir-hardening block (patches pytest's `make_numbered_dir` / `find_prefixed` / cleanup hooks, probes a project-local `.pytest_tmp/<pid>` basetemp) to survive antivirus / OneDrive / search-indexer file locks. It is load-bearing on this machine — don't "simplify" it.

### Git / GitHub uploads

When the user asks to upload, push, or submit code to GitHub, use the local
Windows PowerShell CLI explicitly instead of relying on the sandboxed Git
network path. The user's local PowerShell has working GitHub connectivity while
the sandbox may not.

```powershell
C:\windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command "git status --short --branch"
C:\windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command "git push origin main"
```

Use the same local PowerShell pattern for related Git commands such as
`git add`, `git commit`, and `git push`.

## Architecture (must follow)

### Core invariant

**`core/` is pure Python — no PyQt, no GUI imports.** This enables reuse for CLI/Web frontends. Nothing in CI checks this — Claude Code has a `core-guardian` agent for it, so under Codex verify by hand after any `core/` change.

### Layers

- **`core/`** — Domain logic, zero GUI dependencies.
  - Data models: `models.py` (dataclasses: `Dataset`, `Category`, `ImageInfo`, `Annotation`, `Shape`), `unified.py` (unified SampleSet model bridging raw scan + workflow state).
  - Scanning: `dataset.py` (two-phase scan + layout detection), `index_cache.py` (SQLite cache).
  - Annotation: `annotation.py` (LabelMe parser), `annotation_formats.py` (multi-format), `annotation_writer.py` (write-back), `annotation_fix.py` (clamp out-of-bounds geometry, drop strays — the *fix* to `quality.py`'s `oob` *report*), `labels.py` (`normalize_label`, see Gotchas).
  - Geometry: `oriented_box.py` — OBB helpers (quad ↔ bbox, shoelace area, corner ordering, clamping). OBBs are stored internally as **LabelMe-style four-point polygons**; the DOTA / YOLO-OBB readers and writers stay small by going through here.
  - Format pipeline: `format_in.py` / `format_out.py` (read/write), `format_rt.py` (round-trip validation), `format_convert.py` / `format_migrate.py` (cross-format migration), `pairing.py` (image/label pairing), `annotation_preset.py` (label preset schemes).
  - Workflow: `workflow.py` (sample-state machine), `workflow_store.py` (per-sample persistence), `inbox.py` (batch staging).
  - Processing: `quality.py`, `dedup.py`, `augment.py`, `transform.py`, `convert.py`, `predictor.py`, `splitter.py`, `grounding_bulk.py` (bulk VLM grounding), `task_readiness.py` / `target_readiness.py` (per-task / per-target-format readiness checks), `version_builder.py` (training-version assembly).
  - Pipeline / ingest: `pipeline/` (run-config), `ingest/` (file-ingest rules).
  - **`schema/` is the export-format registry** — see "Export formats" below. `exporter/` holds the writers: `{yolo,yolo_obb,dota,coco,voc,labelme,imagefolder,pairedfolder,mvtec,subset,report,csv_export,jsonl,llava,sharegpt,swift}.py`. Note `core/exporter/__init__.py` is deliberately **empty**: the old `core.exporter.registry` table was retired in favour of `core/schema`.
  - Infrastructure: `config.py`, `project.py`, `recent.py`, `user_settings.py`, `fileops.py`, `stats.py`, `thumbnail_cache.py`, `history.py`, `api.py`, `task_types.py`.

- **`gui/`** — PyQt6 + qfluentwidgets.
  - `main_window.py` — `FluentWindow` with Home (`DatasetWelcome`) + Browser (`DatasetBrowserView`) on the nav rail; Settings is a floating popup (`SettingsView`); `OrganizeView` is on the stack but reached only from the 新数据 stage. Brand title bar (`BrandTitleBar`). Nav rail is **locked at 60px icon-only** via collapse + monkey-patched `panel.expand` no-op + `resizeEvent` re-collapse.
  - `views/` — `dataset_welcome.py` (recents + open/create), `organize_view.py` (ingest/organize helper), `dataset_browser_view.py` (3-column workbench shell), `browser_view.py` (grid + filter chips + pagination), `detail_view.py` (single-image shell), `detail_specs.py` (per-task-type pane spec), `panes/` (`image_label_pane.py`, `annotation_pane.py`, `vlm_pane.py`, `status_pane.py` — DetailView's task-typed sub-panes), `settings_view.py` (floating popup).
  - `widgets/` — Reusable components: `workspace_sidebar.py` (slim vertical stage nav with `StageIndex` constants — the authoritative stage list), `context_panel.py` (right column shell, hosts catalog/inspector pages), `catalog_panel.py` + `category_tree.py` + `distribution_chart.py` (catalog page), `dataset_bar.py` (top strip + global toolbar: refresh/undo), `thumbnail_grid.py` (card grid + delegate), `image_viewer.py` (pan/zoom + shape overlay). **Stage bodies** (one per `StageIndex`): `project_overview_hub.py` (项目概览), `batch_list.py` (新数据), `browser_view.py`↔`detail_view.py` (标注工作台), `review_hub.py` (审核修复 — quality/dedup/stats), `delivery_hub.py` (导出 — direct export + LLM data + read-only cleanup of legacy versions). `project_manage_hub.py` holds project-meta/history surfaces hosted outside the stage stack. Plus `llm_data_card.py`, `scope_badge.py`, `chips.py`, `preview_pane.py`, `brand_title_bar.py`. Orphaned after dataset-versioning was de-scoped (kept, unwired): `training_version_hub.py`, `split_slider.py`.
  - `controllers/` — Browser-shell business logic, extracted from `DatasetBrowserView`: `browser_runtime.py` (shared context: state + bar + hub references + shell), `dataset_session_controller.py` (scan/refresh/worker lifecycle, gates `state.scan_active`), `browser_tool_controller.py` (executes hub `*_requested` signals via `BatchRunner`), `browser_chrome_controller.py` (context-panel page swap + detail drill in/out + sidebar↔stack sync), `workflow_controller.py` (sample-workflow orchestration on `MainWindow`).
  - `workers/` — QThread wrappers: `BatchWorker` (generic `fn(progress_cb)` runner), `BatchRunner` (worker + progress dialog + result handler), `ScanWorker` (dataset scan), `ThumbnailWorker` (lazy thumbnails).
  - `dialogs/` — Parameter-collection + progress dialogs: `op_dialogs.py` (progress, failure detail, move-to-category), `tool_dialogs.py` (quality / stats / dedup config + results), `batch_ops.py`, `history_dialog.py`, `export_wizard.py`, `export_validation_dialog.py`, `category_dialogs.py`, `project_dialogs.py`, `task_type_dialog.py` (task-type picker on first dataset open), `import_annot_dialog.py`, `convert_annot_dialog.py`, `migrate_format_dialog.py`, `llm_format_reference.py`, `preset_picker_dialog.py`, `bulk_region_text_dialog.py`, `vlm_start_dialog.py`.
  - `theme.py` + `styles/app.qss` + `i18n.py` — Three-layer styling system + minimal i18n.
  - `app_state.py` — Shared `AppState` (dataset + project + derived artifacts + `scan_active` gate), Qt-signal-based.

- **`config/default_config.yaml`** — Externalized config (cache paths, image extensions, theme).
- **`main.py`** — Entry point. App data dir: `~/.dataforge/`.

### Navigation & signal flow

`StageIndex` in `gui/widgets/workspace_sidebar.py` is the authoritative stage list — read it before touching navigation. As of this writing it has **5 stages**, wired to the stage stack in `DatasetBrowserView.__init__` (`insertWidget(StageIndex.X, …)`):

```
MainWindow (FluentWindow, 60px icon-only nav rail)
├── Home (DatasetWelcome)
│   ├── Recents list + "open dataset" / "create project"
│   └── open_dataset(path, intent="") → switchTo(browser) → _apply_intent(intent)
├── Browser (DatasetBrowserView)         ← 3-column workbench shell
│   ├── Col 1 — WorkspaceSidebar (slim vertical stage nav)
│   ├── Col 2 — DatasetBar (title, path, stat pills, refresh/undo, catalog toggle, open)
│   │           + stage stack (indexed via StageIndex):
│   │   ├── OVERVIEW  (项目概览)        — ProjectOverviewHub          [default on open]
│   │   ├── INBOX     (新数据)         — BatchListPanel
│   │   ├── ANNOTATE  (标注工作台)      — BrowserView ↔ DetailView (browser_stack)
│   │   ├── REVIEW    (审核修复)        — ReviewHub (quality / dedup / stats)
│   │   └── DELIVERY  (导出)           — DeliveryHub (export-first: direct export + legacy-version cleanup)
│   └── Col 3 — ContextPanel (collapsible; catalog page on ANNOTATE, etc.)
└── Settings (SettingsView popup, bottom-left, NOT a route)
    └── theme_changed → _on_theme_changed()

Dataset-versioning was intentionally de-scoped: there is no PROCESS/数据处理 stage and no
in-app "generate version" entry. Export (DeliveryHub) is the single delivery path. The
pure-core builder (`core/version_builder.py`) and the now-orphaned `TrainingVersionHub` /
`split_slider.py` widgets are kept for reversibility; DeliveryHub still lists any
already-generated `<project>/versions/` snapshots read-only so they can be opened or deleted.

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

**Three-layer styling** (Claude Code enforces this with a `style-cop` agent; not CI-checked, so verify by hand under Codex):
1. `gui/theme.py` — `Tokens` dataclass (colors, spacing, sizes) with LIGHT/DARK instances. Module-level proxy `T` always reflects current theme. `set_theme(name)` swaps the active instance.
2. qfluentwidgets semantic widgets + project custom widgets.
3. `gui/styles/app.qss` — single QSS file with `{TOKEN}` placeholders, substituted at runtime via `load_qss()`.

**Rule**: Never write `setStyleSheet(f"color:#xxx")` in views. All colors come from theme tokens.

**All dialogs/message boxes must use qfluentwidgets** — never native QDialog/QMessageBox.

**Dataset scan**: Two phases — (1) `scan_dataset()` enumerates files via `os.scandir` without parsing JSON, (2) `count_annotations()` optionally parses annotations. Results cached to SQLite via `index_cache.py`. `DatasetSessionController` flips `state.set_scan_active(True/False)` around the full Phase 1+2+3 lifecycle so mutation surfaces stay disabled.

**Thumbnails**: Lazy-loaded via `ThumbnailWorker` with on-disk cache (`diskcache`).

**Worker cleanup**: Before `deleteLater()`ing a view that owns a `ThumbnailWorker` / `ScanWorker`, stop the worker first — otherwise dangling thread references can segfault.

**DetailView is task-templated**: `views/detail_specs.py` holds per-task-type specs; `DetailView` assembles `image_label_pane` + `annotation_pane` + (optional) `vlm_pane` + `status_pane` from `Project.task_type`. Adding a new task type means adding a spec, not editing the view.

**Two geometry models, translated per shape type**: core's `Region` (`core/unified.py`) and the viewer/LabelMe `Shape` (`core/models.py`) describe the same shape differently, and the bridge — `_region_to_shape` / `_shape_to_region` in `gui/views/detail_view.py` — must branch on `shape_type` rather than on whichever geometry field happens to be populated:

| shape type | core `Region` | viewer / LabelMe `Shape` |
|---|---|---|
| `rectangle` | `bbox` | `[tl, br]` |
| `ellipse` | `bbox` | `[tl, br]` (its bbox) |
| `circle` | `bbox` | `[centre, edge]` |
| `point` | `keypoints` | exactly one `(x, y)` |
| `polygon` / `linestrip` | `polygon` (+ derived `bbox`) | the points |

Guessing here has shipped real bugs: a circle passed through as bbox corners rendered at the top-left with a ≈2.8× radius and then *saved that back* on the next edit; `point` matching the bbox branch first came back as two duplicated points, which defeated the `len(points) < 2` guards in the YOLO/VOC writers. `tests/test_shape_conventions.py` locks all of this down — run it after touching either model or the bridge.

**Styling exceptions**: `gui/widgets/image_viewer.py:PALETTE` and `gui/widgets/category_tree.py:_EARTHEN`/`_NAMED` hold hex color literals. These are **category-identity** palettes (same colors must read against both light and dark themes), not theme colors; they are the only allowed hex-literal sites in `gui/`. All other colors must come from `gui.theme.T`.

### Export formats live in one registry

`core/schema/__init__.py` is the **single source of truth for export formats** (14 registered: YOLO, YOLO-OBB, DOTA, COCO, VOC, LabelMe, ImageFolder, MVTec, PairedFolder, CSV, JSONL, ShareGPT, LLaVA, Swift). Any surface that needs "the list of formats" or "the schema for format X" goes through `get(key)` / `all_schemas()` / `schemas_for_task(task_type)` — **never** import a `core/schema/<fmt>.py` module directly, and never hand-maintain a parallel format list in the GUI.

A `Schema` declares its `key`, the `task_types` it supports, and its `Slot`s; `ComplianceReport` (`base.py`) is what `target_readiness.py` and the export-validation dialog render. Registration order matters only for UI enumeration — CV mainline first, generic tabular middle, VLM specialties last.

Adding a format = write `core/schema/<fmt>.py` (the `Schema` + slots), write `core/exporter/<fmt>.py` (the writer), add the import + `register(<FMT>_SCHEMA)` in `core/schema/__init__.py`, and extend `export_formats` on the relevant `TASK_REGISTRY` entries. The GUI picks it up with no further change.

### Adding a new processing operation

1. Create or extend `core/<feature>.py` (pure Python, `progress_cb` supported for anything > ~100ms).
2. Pick the owning stage hub and add a `<kind>_requested` signal + button:
   - **`ReviewHub`** (审核修复) — read-only quality / dedup / stats analyses.
   - **`DeliveryHub`** (导出) — output-producing actions (format conversion, LLM-data capabilities, dataset export).
   - **`ProjectOverviewHub`** (项目概览) — landing dashboard.
3. Add a matching `run_<kind>` handler on `BrowserToolController`: open any config dialog, then run the core call via `BatchRunner(parent, title).run(task=…, on_done=…)`.
4. Wire the hub signal → controller method in `DatasetBrowserView.__init__()` (signal wiring is inline, not a separate method).
5. If it produces a derived artifact (quality issues, dedup groups, stats), store it on `AppState` via a `set_*` method so other views can subscribe.

## Gotchas

- **中文文字 / 图标控件禁止 `setFixedWidth`** —— 中文字符宽度是英文的 ~1.5×，固定宽度 95% 的情况会截字。规则：
  - 文字按钮：用 `setMinimumWidth(N)` 或纯 `adjustSize()` / `sizeHint()` 自动撑开。**N 取最长 label 像素估算 + 24（icon + padding 余量）**
  - 图标 + 文字按钮：`setIcon(...)` 后**绝不**再 `setFixedWidth` —— icon 会吃掉文字空间
  - 自定义 delegate 在 `paint()` 里 `drawText` 必须留 ≥8px padding，不能贴边
  - QSS 每个 text-bearing 选择器最少 `padding: 4px 8px`；`padding: 0` / `1px` / `2px` 一律警告
  - **`setFixedHeight` 可以**（中英文行高一样），**`setFixedWidth` 几乎一定不行**
  - 违反这条比破坏三层样式严重 —— 用户每次都看见。
- **Chinese paths**: Always use `pathlib.Path`, never byte strings.
- **Every label goes through `normalize_label`**: `core/labels.py:normalize_label()` strips BOMs and collapses whitespace runs so `"fastener_core\n"` matches the project class `"fastener_core"`. It is called on ~10 modules' worth of import / edit / export paths (`annotation*.py`, `format_in/out.py`, `models.py`, `project.py`, `unified.py`, `detail_view.py`); any new path that reads a class name from disk or user input must call it too, or labels silently fail to match and split into phantom classes. `tests/test_label_normalization.py` covers it.
- **Don't inject the directory category as an image label on region-bearing samples**: it adds a phantom class (including the synthetic `(未分类)`) to the export class registry and **shifts every real class id**. Regression-tested in `tests/test_shape_conventions.py`.
- **Mismatched image/label pairs**: Flag them, don't crash.
- **Annotation schema drift**: Parser must be tolerant of malformed JSON and record failures.
- **Never hardcode an interpreter or install path**: always `conda run -n defect-tool python …`, never an absolute `C:/…/python.exe`. This applies to docs, `.agents/skills/*/SKILL.md`, and agent definitions — stale absolute paths silently break every tool that carries them (the env has already moved once, from `C:/ProgramData/miniconda3` to the per-user install). A bare `python` is *also* wrong here: it resolves to Python312 / WindowsApps and fails on imports. Resolve package locations at runtime (`python -c "import pkg, os; print(os.path.dirname(pkg.__file__))"`) rather than writing a site-packages path into a file.
- **SSL/proxy on this machine**: Unset `HTTP_PROXY`/`HTTPS_PROXY` before pip/conda installs; use Tsinghua mirrors.
- **Config is read-once**: `core/config.load()` is `@lru_cache(maxsize=1)`. Changes need app restart.
- **Hub buttons require a loaded dataset**: ReviewHub + DeliveryHub action buttons + DatasetBar refresh are gated off `AppState.dataset.total_images > 0`. Capability checkboxes on DeliveryHub gate separately on `project is not None` — a project can be reconfigured before the scan lands.
- **Mutation tools gate on `scan_active`**: `state.can_write` is False while the scan worker runs; DetailView edits and every `*_requested` handler must respect this so we don't race the scan.
- **Window geometry**: Set on the first `showEvent` (deferred one tick) so `screen()` reports the actual landing screen on multi-monitor setups; eagerly sizing in `__init__` always picks primary.
- **Nav rail is icon-only**: Permanently 60px via `panel.collapse()` + monkey-patched `panel.expand` no-op + `resizeEvent` re-collapse. Old auto-expand-at-1100px behavior is gone.
