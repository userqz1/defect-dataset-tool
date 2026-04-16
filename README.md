<p align="center">
  <h1 align="center">数据工坊 / DataForge</h1>
  <p align="center">
    <strong>本地、离线、中文的图像数据集一站式管理工具</strong>
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
</p>

---

## 是什么

打开一个文件夹 → 浏览图片和标注 → 一键导出训练格式。

围绕「浏览器」这一个屏组织：左边类别树，中间缩略图网格，右边详情/标注。
顶部工具栏放质量检查、去重、增强、统计、导出。看到一张图想做什么就点什么——不用学节点连线、不用搭流程。

首期聚焦目标检测，架构预留分类/分割/关键点扩展。

---

## 快速开始

```bash
# 1. 装依赖
pip install -r requirements.txt

# 2. 启动
python main.py

# 3. 在首页点「打开数据集目录」→ 选择任意包含图片的文件夹
#    → 自动识别布局 → 进入浏览器 → 用工具栏导出 YOLO/COCO/...
```

支持的目录布局（自动识别）：

```
A) 标准:    <根>/<类别>/images/*.jpg + <根>/<类别>/labels/*.json
B) 扁平:    <根>/*.jpg + <根>/*.json
C) 单类:    <根>/images/*.jpg + <根>/labels/*.json
D) 递归:    <根>/**/.jpg
```

---

## 主要功能

### 浏览器
- 智能扫描，5 种目录布局自动识别
- 缩略图网格，分页/筛选/搜索/多选/右键批量操作
- SQLite 索引 + 磁盘缩略图缓存，二次打开瞬时
- 类别树支持重命名/合并/拆分
- 顶部 readiness bar 实时显示数据集合规状态

### 单图详情
- 矩形/多边形手动绘制 + 编辑
- 多格式读写：LabelMe / YOLO / VOC / COCO（读什么写什么）

### 工具栏
| 按钮 | 功能 |
|------|------|
| **导出** | 8 种格式向导，自动切分 train/val/test |
| **质量检查** | 模糊/空白/过曝/欠曝/损坏；结果直贴缩略图角标 |
| **去重** | pHash 相似度聚类，可一键删除重复到回收站 |
| **增强** | 几何 + 光度变换组合，支持「全部」或「仅已选中」 |
| **统计** | 类别分布、目标数/图、不平衡比、尺寸范围 |

### 导出格式

| 格式 | 用途 |
|------|------|
| **YOLO** | Ultralytics YOLO 检测/分割 |
| **COCO** | COCO instances JSON |
| **Pascal VOC** | XML + ImageSets |
| **CSV** | Pandas 友好平面表 |
| **JSON Lines** | 流式 JSONL |
| **LLaVA** | 多模态微调 |
| **ShareGPT** | LLaMA-Factory 多模态 |
| **ms-swift** | ModelScope swift VLM |

---

## 架构

```
core/                    # 纯 Python，零 GUI 依赖
  models.py              数据类 (Dataset, Category, ImageInfo, Annotation, Shape)
  dataset.py             两阶段扫描 + 布局检测
  annotation_formats.py  LabelMe / YOLO / VOC / COCO 统一解析
  quality.py             质量检查 (模糊/空白/过曝/欠曝/损坏)
  dedup.py               pHash 重复检测
  augment.py             几何 + 光度增强
  splitter.py            train/val/test 切分（支持分层）
  stats.py               基础 + 扩展统计
  compliance.py          合规检查
  exporter/              8 种导出格式 + 统一注册表

gui/                     # PyQt6 + qfluentwidgets
  main_window.py         FluentWindow：首页 / 浏览器 / 设置
  app_state.py           共享 Dataset/Project 状态
  views/
    dataset_welcome      首页（最近数据集）
    dataset_browser_view 浏览器（顶层视图，含工具栏）
    browser_view         缩略图网格 + 类别树 + 筛选
    detail_view          单图查看 + 标注编辑
    settings_view        主题切换
  widgets/
    thumbnail_grid       delegate 绘制的高性能网格
    category_tree, chips, image_viewer, preview_pane
  dialogs/
    tool_dialogs         质量检查/去重/增强/统计 弹窗
    export_wizard        导出向导
    task_type_dialog     首次打开数据集时选任务类型
  workers/               QThread：扫描 / 缩略图 / 批处理
```

**架构约束：`core/` 禁止 import `PyQt6`** — 便于 CLI/Web 二次封装。

应用数据：`~/.dataforge/` （项目元数据 / 索引缓存 / 缩略图 / 设置）。

---

## 开发

```bash
# 跑测试
python -m pytest tests/ -q

# 单文件 import 检查
python -m py_compile gui/main_window.py
```

测试覆盖：核心数据集扫描、标注解析、所有导出格式端到端、切分、增强等。

---

## 许可证

MIT License
