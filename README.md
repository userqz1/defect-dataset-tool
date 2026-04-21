# DataForge（数据坊）

Windows 桌面工具，Python 3.11 + PyQt6 + qfluentwidgets。
围绕图像数据集在 **生产生命周期中的三个阶段** 提供对应的加工能力——一个工具覆盖从空目录到可训练数据集的全过程。

---

## 三种输入，三种工作流

| 阶段 | 输入状态 | 典型操作 |
|---|---|---|
| **全新数据集** | 只有图像、无标注 | 逐张 / 批量导入、去重、质量筛查、预标注（模型辅助）、人工标注、分类归档 |
| **半成品数据集** | 部分图像已标注 | 补标、标注一致性检查、类别合并 / 拆分、标注修订 |
| **现成数据集** | 完整已标注 | 增量加入新数据、格式互转、数据增广、重划分、导出训练格式 |

**格式互转**支持 LabelMe JSON ⇄ YOLO / Pascal VOC / COCO。
**训练格式导出**支持目标检测（YOLO / COCO / VOC 目录结构）、分类子集（ImageFolder）、以及面向多模态大模型的 **LLaVA / ShareGPT / Swift / JSONL**。

---

## 运行

项目使用 conda 环境 `defect-tool`（Python 3.11）。conda 不在 PATH，直接用 env 里的 `python.exe`：

```bash
# 启动
C:/ProgramData/miniconda3/envs/defect-tool/python.exe main.py

# 安装依赖（先解除代理再走清华源，避免 SSL 错误）
unset HTTP_PROXY HTTPS_PROXY
C:/ProgramData/miniconda3/envs/defect-tool/python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

应用数据目录：`~/.dataforge/`（缓存、配置、项目元信息）。

---

## 目录约定

默认识别：

```
<root>/
├── <category_a>/
│   ├── images/
│   └── labels/      # LabelMe JSON
├── <category_b>/
│   ...
```

同时兼容 flat 布局、单类目录、递归子目录。标注主格式为 LabelMe JSON；扫描时自动识别 YOLO / Pascal VOC / COCO 并在后续操作中统一处理。

---

## 目录结构

| 路径 | 作用 |
|---|---|
| `core/` | 纯 Python 领域逻辑（扫描、标注、去重、增广、格式转换、导出器） |
| `gui/` | PyQt6 + qfluentwidgets 界面层 |
| `config/default_config.yaml` | 图像后缀、缓存路径、主题 |
| `main.py` | 入口 |

`core/` 不依赖任何 GUI 库，可单独用于 CLI / 脚本场景。

---

## 许可

见 [LICENSE](LICENSE)。
