<p align="center">
  <h1 align="center">DataForge / 数据工坊</h1>
  <p align="center">
    <strong>Local, offline, Chinese-first image dataset manager</strong>
  </p>
</p>

<p align="center">
    English | <a href="./README.md">简体中文</a>
</p>

<p align="center">
    <img src="https://img.shields.io/badge/Python-3.11-blue.svg" alt="Python 3.11">
    <img src="https://img.shields.io/badge/GUI-PyQt6%20%2B%20Fluent-41cd52.svg" alt="PyQt6 Fluent">
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License">
    <img src="https://img.shields.io/badge/Platform-Windows-lightgrey.svg" alt="Platform">
</p>

---

## What it is

Open a folder → browse images and annotations → one-click export to a training format.

The whole tool is built around a single screen: category tree on the left, thumbnail grid in the
middle, detail/annotation on the right. The toolbar on top hosts quality check, dedup, augment,
stats and export. See an image, decide what to do, click — no node graphs, no flow diagrams.

Detection is the focus today; classification / segmentation / keypoint slots are reserved.

---

## Quick start

```bash
# 1. install
pip install -r requirements.txt

# 2. launch
python main.py

# 3. on the home page click "Open dataset directory" → pick any folder of images
#    → layout auto-detected → browser opens → use the toolbar to export YOLO/COCO/...
```

Supported directory layouts (auto-detected):

```
A) standard: <root>/<class>/images/*.jpg + <root>/<class>/labels/*.json
B) flat:     <root>/*.jpg + <root>/*.json
C) single:   <root>/images/*.jpg + <root>/labels/*.json
D) recursive: <root>/**/.jpg
```

---

## Features

### Browser
- Smart scan, 5 directory layouts auto-detected
- Thumbnail grid with paging, filters, search, multi-select, batch right-click ops
- SQLite index + on-disk thumbnail cache; second open is instant
- Category tree with rename / merge / split
- Top readiness bar shows live compliance status

### Detail view
- Manual rectangle / polygon drawing and editing
- Multi-format read/write: LabelMe / YOLO / VOC / COCO (read in, write back the same)

### Toolbar
| Button | Function |
|--------|----------|
| **Export** | Wizard for 8 formats; train/val/test split included |
| **Quality** | Blur / blank / over / under / corrupt; results badge the thumbnails |
| **Dedup** | pHash similarity grouping; one-click move duplicates to recycle bin |
| **Augment** | Geometric + photometric combo; "all" or "selected only" |
| **Stats** | Class distribution, per-image counts, imbalance ratio, size range |

### Export formats

| Format | Use |
|--------|-----|
| **YOLO** | Ultralytics YOLO detection / segmentation |
| **COCO** | COCO instances JSON |
| **Pascal VOC** | XML + ImageSets |
| **CSV** | Pandas-friendly flat table |
| **JSON Lines** | Streaming JSONL |
| **LLaVA** | Multimodal fine-tune |
| **ShareGPT** | LLaMA-Factory multimodal |
| **ms-swift** | ModelScope swift VLM |

---

## Architecture

```
core/                    # Pure Python, zero GUI deps
gui/                     # PyQt6 + qfluentwidgets
  main_window.py         FluentWindow: Home / Browser / Settings
  app_state.py           Shared Dataset/Project state
  views/, widgets/, dialogs/, workers/
```

**Architectural rule: `core/` may not import `PyQt6`** — keeps it reusable from CLI/Web.

App data: `~/.dataforge/` (project metadata / index cache / thumbnails / settings).

---

## Development

```bash
python -m pytest tests/ -q
```

---

## License

MIT License
