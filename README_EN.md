<p align="center">
  <h1 align="center">defect-dataset-tool</h1>
  <p align="center">
    <strong>A LabelMe defect-annotation dataset manager (Python 3.11 + PyQt6)</strong>
  </p>
</p>

<p align="center">
    English | <a href="./README.md">简体中文</a>
</p>

<p align="center">
    <img src="https://img.shields.io/badge/Python-3.11-blue.svg" alt="Python 3.11">
    <img src="https://img.shields.io/badge/GUI-PyQt6-41cd52.svg" alt="PyQt6">
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License">
    <img src="https://img.shields.io/badge/Platform-Windows-lightgrey.svg" alt="Platform">
    <img src="https://img.shields.io/badge/Format-LabelMe-orange.svg" alt="LabelMe">
</p>

---

## Overview

A dataset management tool for industrial defect-detection workflows. It supports the LabelMe JSON format and covers the full pipeline: **scan → browse → view → batch-process → export**. The core logic is fully decoupled from the GUI so it can be reused by future Web / CLI frontends.

---

## Features

- **Smart scanner** — auto-detects 5 directory layouts (`standard` / `flat` / `single` / `recursive` / `empty`); tolerant of Unicode paths, missing labels and malformed JSON
- **Three-level browsing** — category tree → thumbnail grid → detail view, with paging, filters, search and multi-select
- **Annotation overlay** — LabelMe polygon / rectangle / point / line / circle rendered on a `QGraphicsView`, with zoom / pan
- **Batch operations** (right-click menu) — delete (Recycle Bin) · rename · move to category · format convert · resize · crop · rotate · flip · export subset
- **Deduplication** — pHash + Hamming-distance clustering
- **Statistics** — totals / annotations / categories / unlabeled + distribution chart
- **Cache layer** — SQLite index cache + on-disk thumbnail cache for instant reopen
- **i18n-ready** — every user-visible string wrapped in `tr()`, ready for `.ts` extraction

---

## Architectural invariant (strict)

**`core/` MUST NOT import `PyQt6`.** This is the cornerstone of the project: it keeps the core reusable for future Web / CLI frontends. Violating it defeats the main design goal.

```
core/       # Pure Python
  models.py          dataclasses
  dataset.py         scanner + layout detection
  annotation.py      tolerant LabelMe parser
  stats.py           statistics
  fileops.py         delete / rename / move
  convert.py         format conversion (JPG/PNG/BMP/WebP/TIFF)
  transform.py       resize / crop / rotate / flip (with coord sync)
  dedup.py           pHash deduplication
  index_cache.py     SQLite index cache
  thumbnail_cache.py on-disk thumbnail cache
  exporter/          subset / report / future YOLO·COCO·LLaVA·MVTec
  config.py          YAML config loader

gui/        # PyQt6
  main_window.py
  views/     overview / browser / detail
  widgets/   category_tree / thumbnail_grid / image_viewer / stats_chart
  dialogs/   op_dialogs.py
  workers/   scan_worker / thumbnail_worker / batch_worker

config/default_config.yaml
main.py
```

---

## Supported directory layouts

The scanner is very tolerant of input:

| Layout | Structure | Behaviour |
|--------|-----------|-----------|
| `standard` | `<root>/<cat>/images/*.jpg` + `<root>/<cat>/labels/*.json` | first-level subdir = category |
| `flat` | `<root>/<cat>/*.jpg` (+ sibling `*.json`) | first-level subdir = category |
| `single` | `<root>/*.jpg` | synthetic `(uncategorized)` category |
| `recursive` | `<root>/train/good/*.jpg` | walks up to depth 4, groups by parent dir name |
| `empty` | no images | explicit "no images found" hint |

`.git` / `node_modules` / `__pycache__` / `venv` and similar directories are ignored.

---

## Supported image formats

Default whitelist (extendable via `config/default_config.yaml`):

```
.jpg  .jpeg  .png  .bmp  .webp  .tif  .tiff
```

---

## Quick start

### Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Run

```bash
python main.py
```

The first scan runs in the background; subsequent opens hit the SQLite index cache and are instant.

---

## Configuration

`config/default_config.yaml`:

```yaml
app:
  name: defect-dataset-tool
  version: 0.1.0

cache:
  index_db: ~/.defect_dataset_tool/index.sqlite
  thumbnail_dir: ~/.defect_dataset_tool/thumbnails

ui:
  theme: light
  accent_color: "#c96442"
  thumbnail_size: 170

scan:
  image_exts: [".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"]
  label_subdir: labels
  image_subdir: images
```

---

## Roadmap

- [ ] Annotation editing (add / remove / modify shapes, write back to JSON)
- [ ] Export to YOLO / COCO / LLaVA / MVTec
- [ ] Train / val / test splitter
- [ ] Quality checks (corrupt images, anomalous sizes, out-of-bounds annotations)
- [ ] Recent-files list / drag-and-drop open
- [ ] English `.qm` translations + language switcher UI
- [ ] PyInstaller packaging + Inno Setup installer

---

## License

MIT License
