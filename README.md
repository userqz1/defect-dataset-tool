<p align="center">
  <h1 align="center">数据坊 / DataForge</h1>
  <p align="center">
    <strong>工业缺陷数据集管理与预处理工具(Python 3.11 + PyQt6 + Fluent)</strong>
  </p>
</p>

<p align="center">
    <a href="./README_EN.md">English</a> | 简体中文
</p>

<p align="center">
    <img src="https://img.shields.io/badge/Python-3.11-blue.svg" alt="Python 3.11">
    <img src="https://img.shields.io/badge/GUI-PyQt6%20%2B%20Fluent-41cd52.svg" alt="PyQt6 Fluent">
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License">
    <img src="https://img.shields.io/badge/Platform-Windows-lightgrey.svg" alt="Platform">
    <img src="https://img.shields.io/badge/Formats-LabelMe%20%7C%20YOLO%20%7C%20VOC%20%7C%20COCO-orange.svg" alt="Formats">
</p>

---

## 项目定位

面向工业缺陷检测场景的**数据集全生命周期工具**:从扫描、浏览、清洗、标注、增强,到划分与多格式导出,一站打通。核心逻辑 (`core/`) 与 GUI (`gui/`) 完全解耦,为未来 Web / CLI 前端复用预留接口。

---

## 核心能力

### 📂 数据集
- **智能扫描**:自动识别 5 种目录布局 (`standard` / `flat` / `single` / `recursive` / `empty`),宽容中文路径与损坏 JSON
- **多格式标注解析**:LabelMe(`*.json`)· YOLO(`*.txt` + `classes.txt`)· Pascal VOC(`*.xml`)· COCO(单个 `instances.json`)
- **多级浏览**:类别树 → 缩略图网格 → 详情页,支持筛选(全部/已标注/未标注)、搜索、分页、多选
- **缓存加速**:SQLite 索引缓存 + 磁盘缩略图缓存,二次打开瞬时完成

### ✏️ 标注编辑
- **矩形 / 多边形**手动标注,拖拽绘制或依次点击顶点,回车闭合
- **按格式回写**:LabelMe / YOLO / VOC 读什么格式写什么格式,YOLO 自动维护 `classes.txt`
- **未保存提示**:切换图片或返回前确认,避免丢失修改
- **快捷键**:`E` 编辑、`R` 矩形、`P` 多边形、`Enter` 闭合、`Del` 删除、`Ctrl+S` 保存

### 🔧 数据处理
| 模块 | 能力 |
|---|---|
| **质量检查** | 检测损坏 / 空白 / 模糊 / 过曝 / 欠曝图像,多选 + 一键删除到回收站 |
| **重复检测** | pHash + Hamming 距离聚类,找出近似重复图片 |
| **AI 预标注** | 本地 YOLOv8 推理自动出框写 LabelMe 草稿待复核(可选依赖 `ultralytics`) |
| **批量变换** | 旋转 / 翻转 / 缩放,标注坐标同步更新,支持**来源选择 + 预览** |
| **数据增强** | 几何(翻转/旋转/随机裁剪)+ 光度(亮度/对比度/色彩/模糊/噪声)+ **Copy-Paste**(多边形 mask 抠图),生成新样本到新目录,多格式标注同步回写 |
| **数据集划分** | 三种模式:按比例 / 按数量 / **手动选择**(浏览页右键加入 Train/Val/Test 桶),支持按类别均衡 |

### 📤 导出
- **YOLO**:`images/{split}` + `labels/{split}` + `classes.txt` + `data.yaml`
- **COCO**:`annotations/instances_{split}.json` + 图片拷贝
- **Pascal VOC**:`JPEGImages` + `Annotations` + `ImageSets/Main`

### 🎨 界面
- **Fluent Design** (qfluentwidgets) + Claude 风格三层配色(tokens → semantic widgets → 单一 QSS)
- **浅色 / 深色**一键切换,通过可视化预览卡选择(QSS 实时重载)
- **响应式侧栏**:窗口变窄自动折叠 nav rail
- **标题栏**:后退/前进按钮 + 当前数据集 chip,最近打开记录

---

## 架构约束(硬性)

**`core/` 禁止 import `PyQt6`**。这是整个项目的架构基石,保证核心逻辑可被未来 Web / CLI 前端复用。

```
core/                    # 纯 Python,零 GUI 依赖
  models.py              数据类
  dataset.py             扫描 + 布局检测
  annotation.py          LabelMe 容错解析器
  annotation_formats.py  LabelMe / YOLO / VOC / COCO 统一解析
  annotation_writer.py   多格式回写(含 YOLO classes.txt 同步)
  stats.py               统计
  fileops.py             删除 / 重命名 / 移动
  convert.py             图像格式转换
  transform.py           缩放 / 裁剪 / 旋转 / 翻转(坐标同步 + 内存预览)
  augment.py             数据增强 + Copy-Paste(多格式标注回写)
  quality.py             质量检查(模糊/空白/过曝/欠曝/损坏)
  dedup.py               pHash 去重
  splitter.py            train/val/test 划分(比例/数量/手动)
  predictor.py           本地 AI 预标注后端(可选 ultralytics)
  recent.py              最近打开列表
  index_cache.py         SQLite 索引缓存
  thumbnail_cache.py     缩略图磁盘缓存
  exporter/              子集 / YOLO / COCO / VOC 导出

gui/                     # PyQt6 + qfluentwidgets
  main_window.py         FluentWindow + 导航 + 历史栈 + 响应式侧栏
  theme.py               Tokens + QSS 加载 + 浅深色切换
  styles/app.qss         唯一 QSS 文件
  views/
    overview_view.py     概览 + 统计卡 + 类别分布图
    browser_view.py      类别树 + 筛选 + 缩略图网格 + 右键菜单
    detail_view.py       单图大图 + 编辑工具栏
    quality_view.py      质量检查
    dedup_view.py        重复检测
    transform_view.py    批量变换(来源选择 + 预览)
    augment_view.py      数据增强(来源选择 + 预览 + Copy-Paste)
    predict_view.py      AI 预标注
    split_view.py        数据集划分(三模式)
    export_view.py       YOLO/COCO/VOC 导出
    settings_view.py     主题卡片 + 缓存 + 最近
  widgets/
    category_tree.py
    thumbnail_grid.py
    image_viewer.py      QGraphicsView + 编辑模式
    preview_pane.py      变换/增强 前后对比
    chips.py             Filter chips
  dialogs/op_dialogs.py
  workers/               QThread:scan / thumbnail / batch

config/default_config.yaml
main.py
```

---

## 支持的目录布局

| 布局 | 结构 | 识别结果 |
|------|------|----------|
| `standard` | `<root>/<cat>/images/*.jpg` + `<root>/<cat>/labels/*.json` | 一级子目录作为类别 |
| `flat` | `<root>/<cat>/*.jpg` (+ 同级 `*.json`) | 一级子目录作为类别 |
| `single` | `<root>/*.jpg` | 合成 `(未分类)` 类别 |
| `recursive` | `<root>/train/good/*.jpg` | 递归最多 4 层 |
| `empty` | 无图片 | 显式提示 |

自动忽略 `.git` / `node_modules` / `__pycache__` / `venv` 等目录。

---

## 快速开始

### 环境准备

```bash
# Conda (推荐)
conda create -n defect-tool python=3.11
conda activate defect-tool
pip install -r requirements.txt

# 或 venv
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 可选依赖

AI 预标注功能需要额外安装:

```bash
pip install ultralytics
```

首次运行会自动下载 YOLOv8 权重(~6MB)。

### 运行

```bash
python main.py
```

---

## 工作流示例

```
1. 标题栏「打开…」→ 选数据集根目录,后台扫描并建索引
2. 概览页看统计 → 浏览页按类别筛选查看
3. 质量检查 → 删除损坏 / 模糊样本
4. 重复检测 → 去除近似重复
5. AI 预标注 → 给未标注图自动出草稿
6. 详情页 E 键进入编辑模式 → 矩形/多边形校正 → Ctrl+S
7. 数据增强 → 选择变换类型 → 预览 → 生成新样本
8. 数据集划分 → 比例/数量/手动 三选一 → 预览 → 写 train/val/test.txt
9. 导出向导 → YOLO / COCO / VOC 一键导出
```

---

## 键盘快捷键

| 动作 | 快捷键 |
|---|---|
| 编辑模式切换 | `E` |
| 矩形绘制 | `R` |
| 多边形绘制 | `P` |
| 闭合多边形 | `Enter` |
| 删除选中 shape | `Del` |
| 保存标注 | `Ctrl+S` |
| 上/下一张 | `← / →` |
| 返回浏览 | `Esc` |

---

## 许可证

MIT License
