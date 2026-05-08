<div align="center">

# DataForge · 数据坊

**An image dataset production tool for computer vision · From an empty folder to a trainable dataset, all in one place**

[![Python](https://img.shields.io/badge/python-3.11-blue.svg)]()
[![PyQt6](https://img.shields.io/badge/PyQt-6-41cd52.svg)]()
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Style](https://img.shields.io/badge/UI-Fluent%20Design-0078D4.svg)]()

[简体中文](README.md) · English

</div>

---

## Introduction

**DataForge (数据坊)** is a desktop image-dataset management tool for CV workflows, covering all four major task families: **classification / object detection / semantic segmentation / anomaly detection**.
Whether your data is "raw images only", "half-labeled", or "fully annotated", DataForge moves it forward to a trainable state from a single interface.

- 🪜 **End-to-end lifecycle** — Import → Annotate → Review → Export, in one place
- 🧠 **Task-aware** — DetailView templates itself per task type (class labels, detection boxes, segmentation masks, anomaly bbox)
- 🔁 **Format interop** — LabelMe ⇄ YOLO / Pascal VOC / COCO, one-click migration
- 🚀 **Multimodal-ready** — Caption / Conversations / Grounding, exportable to LLaVA / ShareGPT / Swift / JSONL
- 🧱 **Clean layering** — `core/` is pure Python with zero GUI deps, reusable for CLI / Web / scripts

---

## 📣 Recent Updates

- **2026.04 · IA v2 main restructure done**
  - New four-stage navigation: **Inbox / Annotate / Review / Project Hub**
  - DetailView templates by task type
  - Project capabilities (Caption / Conversations / Grounding) wired through `project.json` persistence
  - Top-bar global actions: refresh / undo
  - Retired `tool_sidebar`; UI consolidated into stage pages
- **2026.03 · 1.0 release**
  - Unified SampleSet model + Workflow state machine
  - LLaVA / ShareGPT / Swift / JSONL multimodal export
- **2026.02 · Performance & UX**
  - Two-phase scan (filesystem-only → annotation-aware)
  - Thumbnail dual cache (SQLite + diskcache)
  - 12 review-grade fixes (dedup / concurrency / consistency)

---

## 🌟 Key Features

### 1. Four-stage workflow

| Stage | Page | Main actions |
|---|---|---|
| 📥 **Inbox** | `BatchListPanel` | Batch ingestion, commit by category |
| ✏️ **Annotate** | `BrowserView` ↔ `DetailView` | Grid browse · Single-image annotation (templated by task) · VLM caption / chat / region text |
| 🔍 **Review** | `ReviewHub` | Quality check · Duplicate detection · Statistics |
| 📦 **Project Hub** | `ProjectHub` | Capabilities · Format center · Process · Export · History |

The persistent top `DatasetBar` shows: pulsing sync indicator, dataset name / path, stats pills (image count / categories / annotation rate / max:min / issues), **global refresh / undo**, catalog toggle, open button.

### 2. Multi-task-type templating

DetailView automatically loads the right annotation component based on `Project.task_type`:

- **Classification** — single-label / multi-label
- **Detection** — rectangle box + class
- **Segmentation** — polygon / mask
- **Anomaly detection** — bbox + anomaly / normal switch
- **VLM enhancement** (when Project Capabilities enabled) — Caption / Conversations / Grounding region text

### 3. Full-format interop

| Format | Read | Write | Convert |
|---|---|---|---|
| LabelMe JSON | ✅ | ✅ | ✅ |
| YOLO | ✅ | ✅ | ✅ |
| Pascal VOC | ✅ | ✅ | ✅ |
| COCO | ✅ | ✅ (export) | ✅ |

### 4. Training-format export

- **Object detection** — YOLO / COCO / VOC directory layouts
- **Image classification** — ImageFolder (subset export)
- **Multimodal LLMs** — LLaVA / ShareGPT / Swift / JSONL
- Built-in splitting (ratio / manual / stratified) + workflow-state filtering (export only `ready` samples)

### 5. Processing toolbox (Project Hub · Process)

🔍 Resize · ✂️ Crop · 🔄 Rotate · 🔁 Flip · 🖼️ Format convert · ➕ Augment · 🤖 AI pre-annotation (YOLO-assisted)

### 6. Review toolbox (Review)

🔎 Quality check (corrupt / blurry / extreme size / annotation anomalies) · 📑 Duplicate detection (pHash) · 📊 Statistics (class distribution / annotation density / region area)

---

## ⚡ Quick Start

### Environment

The project uses a conda env named `defect-tool` (Python 3.11). Conda is not on PATH; use the env's `python.exe` directly:

```bash
# Create the env (if you haven't yet)
conda create -n defect-tool python=3.11 -y

# Install deps (unset proxy first, use Tsinghua mirror to avoid SSL errors)
unset HTTP_PROXY HTTPS_PROXY
C:/ProgramData/miniconda3/envs/defect-tool/python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Launch

```bash
C:/ProgramData/miniconda3/envs/defect-tool/python.exe main.py
```

App data directory: `~/.dataforge/` (project metadata, cache, user settings).

### Dataset directory convention

```
<root>/
├── <category_a>/
│   ├── images/        # *.jpg / *.png / *.bmp / *.tif / *.webp
│   └── labels/        # LabelMe *.json (or YOLO *.txt / VOC *.xml)
├── <category_b>/
│   ...
```

Also supports: flat layout, single-category folder, recursive subdirectories.
On scan, the **dominant format** (YOLO / VOC / COCO / LabelMe) is auto-detected and unified for downstream operations.

---

## 📚 Project Structure

```
defect_dataset_tool/
├── core/                    # 🟢 Pure Python · zero GUI deps
│   ├── models.py            # Data models (Dataset / Category / ImageInfo / Annotation / Shape)
│   ├── dataset.py           # Two-phase scan + layout detection
│   ├── index_cache.py       # SQLite scan cache
│   ├── annotation*.py       # LabelMe / multi-format parsing + write-back
│   ├── format_*.py          # Format conversion / round-trip / migration
│   ├── quality.py           # Quality check
│   ├── dedup.py             # pHash duplicate detection
│   ├── augment.py           # Data augmentation
│   ├── transform.py         # Resize / crop / rotate / flip
│   ├── convert.py           # Image format conversion
│   ├── predictor.py         # AI pre-annotation (YOLO)
│   ├── splitter.py          # Dataset splitting
│   ├── exporter/            # YOLO / COCO / VOC / LLaVA / ShareGPT / Swift / JSONL
│   ├── pipeline/            # Export pipelines
│   ├── ingest/              # File-ingest rules
│   ├── schema/              # Per-task-type schema validation
│   ├── workflow.py          # Workflow state machine
│   └── project.py           # Project metadata persistence
├── gui/                     # PyQt6 + qfluentwidgets
│   ├── views/               # dataset_browser_view / browser_view / detail_view / settings_view ...
│   ├── widgets/             # dataset_bar / project_hub / review_hub / stage_nav / thumbnail_grid ...
│   ├── controllers/         # session / tool / chrome — three controllers
│   ├── workers/             # ScanWorker / BatchWorker / ThumbnailWorker
│   ├── dialogs/             # Parameter + progress dialogs
│   ├── theme.py             # Three-layer styling: tokens
│   ├── styles/app.qss       # Three-layer styling: QSS
│   └── i18n.py              # zh / en
├── config/default_config.yaml
└── main.py
```

---

## 🛠️ Development Conventions

- **`core/` stays pure Python forever** — no PyQt / qfluentwidgets, so it stays reusable for CLI / Web
- **Three-layer styling** — tokens (`theme.py`) → semantic widgets → single QSS file; no inline `setStyleSheet(f"color:#xxx")`
- **All popups use qfluentwidgets** — never native `QDialog` / `QMessageBox`
- **Long ops go through Workers** — all inherit the `BatchWorker` / `BatchRunner` pattern, with a progress dialog visible from the moment the op starts
- **No explanatory text in UI** — controls only; the target user is a professional

---

## 💖 Acknowledgments

- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — Qt6 Python bindings
- [qfluentwidgets](https://qfluentwidgets.com/) — Fluent Design widget library
- [ultralytics](https://github.com/ultralytics/ultralytics) — YOLO pre-annotation backend
- [imagehash](https://github.com/JohannesBuchner/imagehash) — perceptual-hash dedup
- [diskcache](https://github.com/grantjenks/python-diskcache) — thumbnail disk cache
- [Pillow](https://python-pillow.org/) — image processing
- [LabelMe](https://github.com/wkentaro/labelme) — primary annotation-format reference

---

## 📄 License

[MIT License](LICENSE) · Copyright (c) 2026 defect-dataset-tool contributors
