# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

This repository currently contains only the design document (`解决方案.md`). No code, dependencies, or build system exists yet — the project is pre-implementation. When starting work, scaffold according to the structure in `解决方案.md` rather than inventing a different layout.

## Project

A Windows desktop tool (Python 3.11 + PyQt6) for managing defect-annotation datasets: scan a dataset directory, browse images by category, view LabelMe annotations overlaid on images, compute statistics, and (later) convert to YOLO/COCO/LLaVA/MVTec formats.

Primary input format is **LabelMe JSON**. Expected on-disk layout is `<root>/<category>/images/` + `<root>/<category>/labels/`. The tool must NOT hardcode any dataset path — the user picks it at runtime.

## Architecture (must follow)

The single most important architectural rule: **`core/` is pure Python and must not import PyQt or any GUI module.** This is the key invariant that makes the codebase reusable for future Web/CLI frontends. Violating it defeats the main design goal.

Layering:
- `core/` — domain logic: `models.py` (dataclasses: `Dataset`, `Category`, `ImageInfo`, `Annotation`, `Shape`), `dataset.py` (filesystem scan + SQLite index cache), `annotation.py` (LabelMe parser, must be tolerant of malformed JSON and record failures), `stats.py`, and later `quality.py`, `dedup.py`, `splitter.py`, `exporter/{yolo,coco,llava,mvtec}.py`. Each exporter is a separate file behind a common interface so adding a format doesn't touch the others.
- `gui/` — PyQt6 only. `main_window.py`, `views/{overview,browser,detail}_view.py`, `widgets/{thumbnail_grid,image_viewer,category_tree,stats_chart}.py`, `workers/` for QThread-wrapped background tasks. All long-running work (scan, thumbnail generation) goes through a worker — never block the UI thread.
- `config/default_config.yaml` — externalized config (cache locations, etc.). Don't hardcode paths.
- `main.py` — entry point.

Performance-critical flows to keep in mind when implementing:
- **Dataset scan** caches its index to local SQLite so reopens are instant. First-scan goes through `scan_worker`.
- **Thumbnails** are lazy-loaded with on-disk cache (diskcache is the intended library).
- **Detail view** loads originals on demand; never read all images into memory.

Watch out for: Chinese paths/filenames (use `pathlib`, not byte strings); mismatched image/label pairs (flag, don't crash); LabelMe schema drift (tolerant parsing).

## Commands

No build system exists yet. When set up per the design doc:
- Env: `python -m venv venv && venv\Scripts\activate && pip install -r requirements.txt`
- Run: `python main.py`
- Tests live under `tests/` (framework not yet chosen — pytest is the natural fit given the dataclass-based core).

## Reference

Full design rationale, data models, UI sketch, and phased feature list (v1 P0 / v2 P1 / v3 P2) are in `解决方案.md`. Read it before making non-trivial changes — especially sections 三 (directory layout), 六 (data models), and 九 (extensibility constraints).
