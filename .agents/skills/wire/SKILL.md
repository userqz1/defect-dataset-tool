---
name: wire
description: Wires an existing core/ feature into the GUI as a new view registered in the navigation menu. Use when the user asks to "接上 / wire / 暴露" a feature like quality / dedup / transform / split / export.
---

Take one argument: the feature key. Supported keys and their core modules:

- `quality` → `core/quality.py` → 数据处理 / 质量检查
- `dedup` → `core/dedup.py` → 数据处理 / 重复检测
- `transform` → `core/transform.py` + `core/convert.py` → 数据处理 / 批量变换
- `split` → `core/splitter.py` → 数据处理 / 数据集划分
- `export` → `core/exporter/*` → 导出 / 导出向导
- `categories` → `core/fileops.py` → 数据集 / 类别管理
- `settings` → (new) → 设置

If the argument is missing or unknown, print the list above and stop.

# Steps

1. **Read the core module(s)** for the chosen feature to learn its public API: function names, parameters, return type, and whether it takes a `progress_cb`. Use Read / Grep directly — do not spawn an agent for this.

2. **Confirm nav placement** by reading `解决方案.md` §五 信息架构 and matching the feature to its group (数据集 / 数据处理 / 导出 / 设置).

3. **Check the existing view naming convention** by Globbing `gui/views/*.py`. Match the file layout style of an existing view (imports, class structure, setObjectName, QVBoxLayout root, use of T tokens, no inline styles, no color literals).

4. **Create the new view file** under `gui/views/` with:
   - A class that inherits `QWidget`, sets `objectName` and `WA_StyledBackground`.
   - A header section with `SubtitleLabel` (feature name) and `CaptionLabel` (one-sentence description).
   - A body area that surfaces the core module's primary entry point. For operations with parameters, use a form built from qfluentwidgets inputs. For operations that scan or process, use a primary button that runs the work through a worker.
   - A `set_dataset(dataset: Dataset)` method that receives the currently opened dataset. The view must handle the `None` / empty-dataset case gracefully (disable the primary action).
   - No inline `setStyleSheet`, no color literals, no magic spacing. Use `T.*` tokens from `gui.theme`.

5. **Route long-running work through a worker.** Reuse `gui/workers/batch_worker.py` if its signature fits; otherwise, extend it rather than creating a new worker class. Progress goes to a `ProgressDialog` instance from `gui/dialogs/op_dialogs.py`.

6. **Register in the navigation menu.** Open `gui/main_window.py`, locate `_build_views`, and add the new view under the correct nav group using whatever sub-interface API the current nav code uses. If the current nav does not yet support sub-groups (earlier versions used flat `addSubInterface`), flag this and stop — wiring sub-grouped nav is a larger change that belongs to a dedicated task, not a single `/wire` invocation.

7. **Connect the dataset lifecycle.** In `main_window._on_scan_done`, forward the loaded dataset to the new view's `set_dataset`. In the empty state, ensure the view is disabled or shows its own empty-state message.

8. **Verify with compile.** Run `"C:/ProgramData/miniconda3/envs/defect-tool/python.exe" -m compileall -q gui main.py`. If it fails, fix and retry once. If it fails again, revert and report the error — do not leave broken code behind.

9. **Report what was done** in ≤ 10 lines: files created, files edited, nav entry added, what the user should click to reach the feature, and any follow-ups that are out of scope (tests, polish, empty-state copy).

# Rules

- Do not invent core APIs. If the core module doesn't expose what the feature needs, stop and report the gap instead of hacking around it.
- Do not duplicate logic that already exists in another view. Prefer extracting a shared widget into `gui/widgets/` if two views would need the same control.
- Do not touch `core/`. This skill only adds GUI layers on top of core.
- Do not add tests, documentation, or styling polish in this skill — those are follow-ups the user can request separately.
