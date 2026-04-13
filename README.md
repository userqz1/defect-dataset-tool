<p align="center">
  <h1 align="center">数据坊 / DataForge</h1>
  <p align="center">
    <strong>可视化数据集处理流水线 (Python 3.11 + PyQt6 + Fluent)</strong>
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

n8n / ComfyUI 风格的图像数据集处理工具。打开即画布，从侧栏拖入节点、连线、配参数、一键执行：

```
[数据源] → [质量检查] → [AI 预标注] → [数据增强] → [划分] → [导出 YOLO]
```

支持分类、检测、分割、异常检测等 CV 任务。核心逻辑 (`core/`) 与 GUI (`gui/`) 完全解耦。

---

## 核心能力

### 节点画布

| 节点 | 功能 |
|------|------|
| **数据源** | 选择数据集目录，自动识别 5 种布局，浏览/标注/删除图片 |
| **质量检查** | 检测模糊/空白/过曝/欠曝/损坏，输出合格/不合格两路 |
| **重复检测** | pHash 相似度聚类，输出唯一/重复两路 |
| **AI 预标注** | YOLOv8 本地推理，批量生成 LabelMe 标注 |
| **数据增强** | 翻转/旋转/裁剪/亮度/对比度/Copy-Paste，生成新样本 |
| **数据集划分** | 按比例/按数量/手动，支持分层采样 |
| **导出** | YOLO / COCO / Pascal VOC / CSV 格式 |

- 节点从侧栏拖入画布，端口连线，双击配参数
- 点「执行流程」一键运行整个图，数据按连线流转
- 方案可保存/加载，参数随方案持久化

### 标注编辑

数据源节点内置完整标注编辑器：
- 矩形/多边形手动绘制，快捷键操作
- 多格式读写：LabelMe / YOLO / VOC / COCO
- 读什么格式写什么格式，YOLO 自动维护 `classes.txt`

### 数据集管理

- 智能扫描：自动识别 `standard` / `flat` / `single` / `recursive` / `empty` 布局
- 缓存加速：SQLite 索引 + 磁盘缩略图，二次打开瞬时
- 缩略图网格浏览，支持筛选/搜索/分页/多选/右键批量操作

---

## 架构

```
core/                    # 纯 Python，零 GUI 依赖
  models.py              数据类 (Dataset, Category, ImageInfo, Annotation, Shape)
  nodes.py               ProcessingNode 协议 + 所有节点实现 + NODES 注册表
  pipeline.py            GraphEngine 图执行引擎 (拓扑排序 + 端口路由)
  scheme.py              方案序列化 (画布状态 → JSON)
  dataset.py             两阶段扫描 + 布局检测
  annotation_formats.py  LabelMe / YOLO / VOC / COCO 统一解析
  quality.py / dedup.py / augment.py / splitter.py / predictor.py ...
  exporter/              YOLO / COCO / VOC / CSV / JSONL / LLaVA / ShareGPT ...

gui/                     # PyQt6 + qfluentwidgets
  main_window.py         FluentWindow：首页 + 编辑器 + 设置
  views/
    scheme_welcome_view   首页（方案管理）
    pipeline_view         编辑器（画布 + workspace 栈）
    browser_view          缩略图网格浏览
    detail_view           单图查看 + 标注编辑
    cleaning_view         质量检查 workspace
    augment_view          数据增强 workspace
    predict_view          AI 预标注 workspace
    split_view            划分 workspace
    export_view           导出 workspace
    ...
  widgets/node_editor.py  NodeCanvas / NodeItem / PortItem / ConnectionItem
  workers/                QThread：扫描 / 缩略图 / 批处理
```

**架构约束：`core/` 禁止 import `PyQt6`。**

---

## 快速开始

```bash
# 环境
conda create -n defect-tool python=3.11
conda activate defect-tool
pip install -r requirements.txt

# 可选：AI 预标注
pip install ultralytics

# 运行
python main.py
```

---

## 工作流

1. 启动 → 首页新建方案（或打开已有方案）
2. 从侧栏拖入节点到画布：数据源 → 质量检查 → 导出
3. 连线：拖动输出端口到下游输入端口
4. 双击数据源 → 选择目录 → 浏览/标注图片
5. 双击各节点 → 配置参数（阈值、比例、格式等）
6. 点「执行流程」→ 数据从上到下流转，节点显示结果
7. 保存方案 → 下次打开自动恢复所有配置

---

## 快捷键

| 动作 | 快捷键 |
|---|---|
| 编辑标注 | `E` |
| 矩形 / 多边形 | `R` / `P` |
| 闭合多边形 | `Enter` |
| 删除选中 | `Del` |
| 保存标注 | `Ctrl+S` |
| 前/后一张 | `A` / `D` |
| 返回浏览 | `Esc` |

---

## 许可证

MIT License
