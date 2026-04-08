<p align="center">
  <h1 align="center">defect-dataset-tool</h1>
  <p align="center">
    <strong>LabelMe 缺陷标注数据集管理工具（Python 3.11 + PyQt6）</strong>
  </p>
</p>

<p align="center">
    <a href="./README_EN.md">English</a> | 简体中文
</p>

<p align="center">
    <img src="https://img.shields.io/badge/Python-3.11-blue.svg" alt="Python 3.11">
    <img src="https://img.shields.io/badge/GUI-PyQt6-41cd52.svg" alt="PyQt6">
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License">
    <img src="https://img.shields.io/badge/Platform-Windows-lightgrey.svg" alt="Platform">
    <img src="https://img.shields.io/badge/Format-LabelMe-orange.svg" alt="LabelMe">
</p>

---

## 项目定位

面向工业缺陷检测场景的数据集管理工具。支持 LabelMe JSON 格式，提供从"扫描 → 浏览 → 查看 → 批量处理 → 导出"的完整工作流。核心逻辑与 GUI 完全解耦，为后续 Web / CLI 前端复用预留接口。

---

## 核心能力

- **智能扫描**：自动识别 5 种目录布局（`standard` / `flat` / `single` / `recursive` / `empty`），宽容处理中文路径、丢失标签、损坏 JSON
- **多级浏览**：类别树 → 缩略图网格 → 详情页，支持分页、筛选、搜索、多选
- **标注可视化**：在 `QGraphicsView` 上叠加 LabelMe 的 polygon / rectangle / point / line / circle，支持缩放平移
- **批量操作**（右键菜单）：删除（回收站）· 批量重命名 · 移动到类别 · 格式转换 · 缩放 · 裁剪 · 旋转 · 翻转 · 导出子集
- **重复检测**：pHash + Hamming 距离聚类
- **统计分析**：总数 / 标注数 / 类别数 / 未标注数 + 分布条形图
- **缓存加速**：SQLite 索引缓存 + 磁盘缩略图缓存，二次打开瞬时完成
- **国际化预埋**：所有用户可见字符串已 `tr()` 包裹，可随时生成 `.ts` 翻译模板

---

## 架构约束（硬性）

**`core/` 禁止 import `PyQt6`**。这是整个项目的架构基石，保证核心逻辑可被未来的 Web / CLI 前端复用。

```
core/       # 纯 Python
  models.py          数据类
  dataset.py         扫描 + 布局检测
  annotation.py      LabelMe 容错解析器
  stats.py           统计
  fileops.py         删除 / 重命名 / 移动
  convert.py         格式转换（JPG/PNG/BMP/WebP/TIFF）
  transform.py       缩放 / 裁剪 / 旋转 / 翻转（含坐标同步）
  dedup.py           pHash 去重
  index_cache.py     SQLite 索引缓存
  thumbnail_cache.py 缩略图磁盘缓存
  exporter/          子集 / 报告 / 未来 YOLO·COCO·LLaVA·MVTec
  config.py          YAML 配置加载

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

## 支持的目录布局

工具对输入目录非常宽容：

| 布局 | 结构 | 识别结果 |
|------|------|----------|
| `standard` | `<root>/<cat>/images/*.jpg` + `<root>/<cat>/labels/*.json` | 一级子目录作为类别 |
| `flat` | `<root>/<cat>/*.jpg` (+ 同级 `*.json`) | 一级子目录作为类别 |
| `single` | `<root>/*.jpg` | 合成 `(未分类)` 类别 |
| `recursive` | `<root>/train/good/*.jpg` | 递归最多 4 层，按目录名分组 |
| `empty` | 无图片 | 显式提示未发现图片 |

自动忽略 `.git` / `node_modules` / `__pycache__` / `venv` 等目录。

---

## 支持的图像格式

默认白名单（可在 `config/default_config.yaml` 中扩展）：

```
.jpg  .jpeg  .png  .bmp  .webp  .tif  .tiff
```

---

## 快速开始

### 环境准备

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 运行

```bash
python main.py
```

首次打开数据集会走后台扫描，之后通过 SQLite 索引缓存瞬时加载。

---

## 配置

`config/default_config.yaml`：

```yaml
app:
  name: 缺陷数据集管理工具
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

## 路线图

- [ ] 标注编辑（新增 / 删除 / 修改 shape 并写回 JSON）
- [ ] 导出为 YOLO / COCO / LLaVA / MVTec 格式
- [ ] 数据集切分（train / val / test）
- [ ] 质量检查（损坏图片 / 尺寸异常 / 标注越界）
- [ ] 最近打开列表 / 拖拽打开
- [ ] 英文翻译 `.qm` + 语言切换 UI
- [ ] PyInstaller 打包 + Inno Setup 安装器

---

## 许可证

MIT License
