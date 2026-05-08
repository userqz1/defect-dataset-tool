<div align="center">

# 数据坊 · DataForge

**面向计算机视觉的图像数据集生产工具 · 从空目录到可训练数据集，一个工具完成全流程**

[![Python](https://img.shields.io/badge/python-3.11-blue.svg)]()
[![PyQt6](https://img.shields.io/badge/PyQt-6-41cd52.svg)]()
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Style](https://img.shields.io/badge/UI-Fluent%20Design-0078D4.svg)]()

[English](README_EN.md) · 简体中文

</div>

---

## 简介

**数据坊（DataForge）** 是一款面向 CV 任务的桌面级图像数据集管理工具，覆盖**分类 / 目标检测 / 语义分割 / 异常检测**四大任务族。
不论你的数据是「只有图片」「半标半生」还是「已经标注完整」，数据坊都能在同一界面里把它们推进到可训练的状态。

- 🪜 **生命周期闭环**：导入 → 标注 → 审核 → 导出，一站式完成
- 🧠 **任务自适应**：DetailView 按任务类型自动模板化（分类标签、检测框、分割掩码、异常 bbox）
- 🔁 **格式互转**：LabelMe ⇄ YOLO / Pascal VOC / COCO，一键迁移
- 🚀 **多模态就绪**：支持 Caption / Conversations / Grounding，可直接导出 LLaVA / ShareGPT / Swift / JSONL
- 🧱 **干净分层**：`core/` 纯 Python 零 GUI 依赖，可独立用于 CLI / Web / 脚本场景

---

## 📣 最近更新

- **2026.04 · IA v2 主改造完成**
  - 新四阶段导航：**收件箱 / 标注 / 审核 / 项目中心**
  - DetailView 按任务类型模板化
  - 项目能力（Caption / Conversations / Grounding）打通 `project.json` 持久化
  - 顶栏全局动作：刷新 / 撤销
  - 退役 `tool_sidebar`，UI 收口于阶段页
- **2026.03 · 1.0 发布**
  - 统一 SampleSet 模型 + Workflow 状态机
  - 支持 LLaVA / ShareGPT / Swift / JSONL 多模态导出
- **2026.02 · 性能与体验**
  - 扫描两阶段化（filesystem-only → annotation-aware）
  - 缩略图 SQLite + diskcache 双缓存
  - 12 项审查级修复（dedup / 并发 / 一致性）

---

## 🌟 主要特性

### 1. 四阶段工作流

| 阶段 | 页面 | 主要操作 |
|---|---|---|
| 📥 **收件箱** | `BatchListPanel` | 批次导入、按分类提交 |
| ✏️ **标注** | `BrowserView` ↔ `DetailView` | 网格浏览 · 单图标注（按任务模板化） · VLM 描述 / 对话 / 区域文本 |
| 🔍 **审核** | `ReviewHub` | 质量检查 · 重复检测 · 数据统计 |
| 📦 **项目中心** | `ProjectHub` | 项目能力 · 格式中心 · 处理 · 导出 · 历史 |

顶部 `DatasetBar` 常驻：脉动同步点、数据集名 / 路径、统计条（图片数 / 分类 / 标注率 / 最大:最小 / 问题数）、**全局刷新 / 撤销**、catalog 开关、打开按钮。

### 2. 多任务类型模板化

DetailView 根据 `Project.task_type` 自动加载对应的标注组件：

- **分类（classification）** — 单标签 / 多标签
- **检测（detection）** — 矩形框 + 类别
- **分割（segmentation）** — 多边形 / 掩码
- **异常检测（anomaly）** — bbox + 异常 / 正常切换
- **VLM 增强**（Project Capabilities 开启后）— Caption / Conversations / Grounding 区域文本

### 3. 全格式互通

| 标注格式 | 读 | 写 | 互转 |
|---|---|---|---|
| LabelMe JSON | ✅ | ✅ | ✅ |
| YOLO | ✅ | ✅ | ✅ |
| Pascal VOC | ✅ | ✅ | ✅ |
| COCO | ✅ | ✅（导出） | ✅ |

### 4. 训练格式导出

- **目标检测**：YOLO / COCO / VOC 目录结构
- **图像分类**：ImageFolder（子集导出）
- **多模态大模型**：LLaVA / ShareGPT / Swift / JSONL
- 内置划分（ratio / manual / stratified）+ 工作流状态过滤（仅导出 ready）

### 5. 处理工具箱（项目中心 · 处理）

🔍 缩放 · ✂️ 裁剪 · 🔄 旋转 · 🔁 翻转 · 🖼️ 格式转换 · ➕ 数据增强 · 🤖 AI 预标注（YOLO 模型辅助）

### 6. 审核工具箱（审核）

🔎 质量检查（损坏 / 模糊 / 极端尺寸 / 标注异常） · 📑 重复检测（pHash） · 📊 统计分析（类别分布 / 标注密度 / 区域面积）

---

## ⚡ 快速开始

### 环境准备

项目使用 conda 环境 `defect-tool`（Python 3.11）。conda 不在 PATH，直接用 env 里的 `python.exe`：

```bash
# 创建环境（如果还没有）
conda create -n defect-tool python=3.11 -y

# 安装依赖（先解除代理再走清华源，避免 SSL 错误）
unset HTTP_PROXY HTTPS_PROXY
C:/ProgramData/miniconda3/envs/defect-tool/python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 启动

```bash
C:/ProgramData/miniconda3/envs/defect-tool/python.exe main.py
```

应用数据目录：`~/.dataforge/`（项目元信息、缓存、用户设置）。

### 数据集目录约定

```
<root>/
├── <category_a>/
│   ├── images/        # *.jpg / *.png / *.bmp / *.tif / *.webp
│   └── labels/        # LabelMe *.json （或 YOLO *.txt / VOC *.xml）
├── <category_b>/
│   ...
```

同时兼容：扁平布局、单类目录、递归子目录。
扫描时**自动识别**主格式（YOLO / VOC / COCO / LabelMe）并在后续操作中统一处理。

---

## 📚 项目结构

```
defect_dataset_tool/
├── core/                    # 🟢 纯 Python · 零 GUI 依赖
│   ├── models.py            # 数据模型 (Dataset / Category / ImageInfo / Annotation / Shape)
│   ├── dataset.py           # 两阶段扫描 + 布局自动识别
│   ├── index_cache.py       # SQLite 扫描缓存
│   ├── annotation*.py       # LabelMe / 多格式解析 + 写回
│   ├── format_*.py          # 格式互转 / round-trip 校验 / 迁移
│   ├── quality.py           # 质量检查
│   ├── dedup.py             # pHash 去重
│   ├── augment.py           # 数据增强
│   ├── transform.py         # 缩放 / 裁剪 / 旋转 / 翻转
│   ├── convert.py           # 图像格式转换
│   ├── predictor.py         # AI 预标注（YOLO）
│   ├── splitter.py          # 数据集划分
│   ├── exporter/            # YOLO / COCO / VOC / LLaVA / ShareGPT / Swift / JSONL
│   ├── pipeline/            # 导出流水线
│   ├── ingest/              # 文件导入规则
│   ├── schema/              # 任务类型 schema 校验
│   ├── workflow.py          # 工作流状态机
│   └── project.py           # 项目元信息持久化
├── gui/                     # PyQt6 + qfluentwidgets
│   ├── views/               # dataset_browser_view / browser_view / detail_view / settings_view ...
│   ├── widgets/             # dataset_bar / project_hub / review_hub / stage_nav / thumbnail_grid ...
│   ├── controllers/         # session / tool / chrome 三控制器
│   ├── workers/             # ScanWorker / BatchWorker / ThumbnailWorker
│   ├── dialogs/             # 参数 + 进度对话框
│   ├── theme.py             # 三层样式系统：tokens
│   ├── styles/app.qss       # 三层样式系统：QSS
│   └── i18n.py              # 中英双语
├── config/default_config.yaml
└── main.py
```

---

## 🛠️ 开发规范

- **`core/` 永远纯 Python** — 不引入 PyQt / qfluentwidgets，便于 CLI / Web 复用
- **三层样式架构** — tokens（`theme.py`）→ 语义 widget → 单一 QSS 文件，禁止内联 `setStyleSheet(f"color:#xxx")`
- **所有弹窗使用 qfluentwidgets** — 不使用原生 `QDialog` / `QMessageBox`
- **耗时操作走 Worker** — 全部继承 `BatchWorker` / `BatchRunner` 模式，进度弹窗即时显示
- **UI 不写解释性文字** — 只放功能控件，目标用户是专业人士

---

## 💖 致谢

- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — Qt6 Python 绑定
- [qfluentwidgets](https://qfluentwidgets.com/) — Fluent Design 控件库
- [ultralytics](https://github.com/ultralytics/ultralytics) — YOLO 预标注后端
- [imagehash](https://github.com/JohannesBuchner/imagehash) — 感知哈希去重
- [diskcache](https://github.com/grantjenks/python-diskcache) — 缩略图磁盘缓存
- [Pillow](https://python-pillow.org/) — 图像处理
- [LabelMe](https://github.com/wkentaro/labelme) — 标注主格式参考

---

## 📄 许可证

[MIT License](LICENSE) · Copyright (c) 2026 defect-dataset-tool contributors
