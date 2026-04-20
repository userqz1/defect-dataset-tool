# 数据工坊（DataForge）整体设计方案

> 版本：**v1.2**（基于 v1.1 修订，纠正定位、落地初期简单原则）
> 定位：**CV 训练数据工坊**，覆盖主流小模型训练任务，并提供 VLM 格式桥接作为差异化能力
> 本文档：纯设计思想与规则，不含代码

---

## 变更记录

**v1.2（当前）** 相对 v1.1 的主要变动：

1. **定位纠偏**——从"VLM 为主"改回"CV 主线 + VLM 差异化"。主要输出是 YOLO / COCO / VOC / ImageFolder / MVTec 等传统 CV 格式（服务 80% 用户），VLM 格式是差异化加分项（服务 20% 用户）
2. **VLM 模块降级**——从独立章节合并进 Schema 系统的一个小节，位置上与其他 Schema 平级
3. **Schema 优先级重排**——CV 格式优先，VLM 格式精简到两个主流（ShareGPT + ms-swift）
4. **"初期简单"原则落地**——新增"v1 功能范围清单"明确拒绝清单；收窄第一层功能（分类建议留 4 种、标注留 2 种）；VLM 只做 template 后端
5. **预置模板重排**——按"训练 CV / 训练 VLM"分组，CV 模板数量占主导
6. **新增分阶段发布策略**（v0.1 → v0.2 → v1.0）

**v1.1** 相对 v1.0 的变动：新增数据整理基础层、预留 3D、弱化对外部模型依赖。

---

## 0. 文档使用说明

这份文档是 DataForge 项目重构与新开发的**设计宪法**。所有模块设计、代码组织、接口规划都必须符合本文档的原则。如果未来发现原则本身有问题，应先修改本文档，再改代码——不是绕过原则。

文档分 16 个部分。前 3 部分（哲学、分层、架构）是必读的决策层；4–10 部分是各子系统的具体规则；11–16 部分是工程支撑与迁移。

---

## 1. 设计哲学与一句话定义

### 1.1 一句话定义

> **DataForge 是把混乱图像变成训练就绪数据集的桌面工坊——覆盖目标检测、分类、分割、异常检测等所有主流 CV 训练任务，并能把 CV 标注桥接到 VLM 微调格式。**

这句话必须出现在：README 第一行、PyPI 描述、官网首页、所有宣传图文的显眼位置。

**关键词解释**：
- "**工坊**"：强调加工能力，不是仓库（区别于 FiftyOne 的"管理"定位）
- "**桌面**"：强调离线、本地、隐私（区别于 CVAT / Label Studio / Roboflow 的 Web 定位）
- "**从混乱图像到训练就绪**"：覆盖完整链路（区别于单一功能工具）
- "**覆盖所有主流 CV 训练任务**"：这是基础盘，服务绝大多数用户
- "**并能桥接到 VLM 微调格式**"：差异化加分项，不是主卖点

### 1.2 定位原则：CV 主线，VLM 差异化

v1.2 重新明确了产品定位，这是全文档最重要的判断：

**主线（80% 用户场景）**：CV 小模型训练数据的整理与生产
- 目标检测（YOLOv8 / YOLO-NAS / RT-DETR）→ YOLO / COCO 格式
- 图像分类（ResNet / ViT / EfficientNet）→ ImageFolder 格式
- 图像分割（U-Net / Mask R-CNN）→ COCO-seg / Mask-PNG
- 异常检测（Anomalib / PaDiM / PatchCore）→ MVTec AD 格式
- 通用数据表达 → CSV / JSON Lines

**差异化（20% 用户场景）**：传统 CV 标注到 VLM 微调的桥梁
- LLaMA-Factory / ms-swift 框架的训练数据
- 从 COCO/YOLO 自动生成图文对话

**这个比例必须反映在产品的每一处**：Schema 优先级、预置模板数量、GUI 布局、文档篇幅、宣传口径。任何让 VLM 显得像主功能的设计都是偏离。

### 1.3 核心设计哲学：格子补齐（Schema-First）

传统工具的思路是"**我有什么数据，能做成什么**"——导入后摸索功能。
DataForge 的思路是"**我要产出什么格式，缺什么就补什么**"——先选目标，工具立刻告诉差在哪。

这个理念用三句话描述：

1. **输出格式是已知的**（格子）——每种训练框架需要什么字段、什么文件、什么目录结构，都能声明式描述
2. **输入数据是未知的**（混乱）——用户给进来的可能是散图、半标注、错格式
3. **工具的职责是"告诉你缺什么 + 怎么补"**——而不是"允许你做任何操作"

这个理念落到代码上，表现为三件套：**Schema 系统 + 合规检查 + 步骤式 Pipeline**。它贯穿 core、cli、gui 三层，是区别于 CVAT / Label Studio / FiftyOne 的品牌资产。

### 1.4 四条设计原则

**原则 A：Core 是王，GUI 可替换**

所有业务逻辑在 `dataforge-core` 里。GUI 和 CLI 是 core 的两个前端。

反例：不准在 GUI 里写"检测布局类型"的逻辑；不准在 CLI 里写"导出 YOLO 格式"的逻辑。

**原则 B：声明式优于命令式**

- 格式定义用 Schema 对象描述
- 管道用 YAML 序列化
- 配置用结构化模型（pydantic）

反例：不准写"if fmt == 'yolo': ... elif fmt == 'coco': ..."；用 Schema 注册表代替。

**原则 C：一切可观测**

- 每一次元数据操作进 `history.jsonl`
- 每一次导出留下 `manifest.json`
- 日志分级：DEBUG 进文件、INFO 进文件、WARNING 进 stderr、ERROR 弹用户可见提示

反例：不准静默失败；不准用 print；不准吞异常而不记录。

**原则 D：开箱即用，AI 能力是后续增强**

v1 版本所有核心路径必须在"**只装 `pip install dataforge` 后就能完整使用**"的前提下工作。AI 预标注、AI 分类建议、AI 生成 Q&A 全部作为**后续版本或插件**开放，不是 v1 的先决条件。

**v1 的"简单"边界**：
- ✅ 基于文件名、目录、EXIF、像素统计的规则
- ✅ 基于 PIL + numpy 的图像处理
- ✅ 基于规则模板的文本生成
- ❌ 任何需要下载模型权重的功能
- ❌ 任何需要网络连接的功能
- ❌ 任何需要 GPU 的功能
- ❌ 任何需要 API key 的功能

反例：不准把"需要 OpenAI API key"作为前置条件；不准默认行为依赖网络连接。

### 1.5 Non-Goals（明确不做什么 vs 预留）

**彻底不做（v1 和 v2 都不做）**：
- ❌ 视频标注（让 CVAT 做）
- ❌ 在线协同标注（Web 是 Label Studio 的地盘）
- ❌ 数据版本控制（DVC/lakeFS 已占领）
- ❌ 模型训练（让 LLaMA-Factory / ultralytics 做）
- ❌ 模型部署（Triton、BentoML 的事）
- ❌ Electron / Web GUI（桌面原生是差异化）
- ❌ DataForge 自有模型服务（没服务器、没模型）

**架构预留（v1 不实现但不阻碍未来加入）**：
- ⏸ **3D 点云数据**——TaskType 预留、Schema 系统兼容，但核心 IO/GUI 不改代码
- ⏸ **AI 能力**——插件接口开放，社区可贡献 SAM、Grounding DINO 等，v1 不内置
- ⏸ **团队协作功能**——Project 系统预留多用户字段，v1 不做云同步

### 1.6 v1 功能范围清单（必读）

这是"**对自己说不**"的清单。v1 阶段每次想加功能前先查这个清单，在这上面的一律说 no，留给 v1.1+。

**v1 不做，但 v1.1+ 会做**：
- ❌ 视觉聚类分类（感知哈希聚类）
- ❌ AI 预标注（YOLOv8 / SAM / Grounding DINO 插件）
- ❌ AI 分类建议
- ❌ 多边形 / 点 / 线标注工具
- ❌ 本地 LLM Q&A 后端（Ollama 集成）
- ❌ API Q&A 后端（OpenAI 兼容）
- ❌ 自定义 Jinja2 Q&A 模板
- ❌ 插件系统（v1 只内置 Schema，插件机制 v1.1 开放）
- ❌ 多数据集合并的复杂策略

**v1 只做**：
- ✅ 批量导入、基于文件名/目录/EXIF 的分类建议、手动分类界面
- ✅ 矩形标注 + 图像级标签
- ✅ 质检（模糊/空白/过曝）+ 去重（感知哈希）
- ✅ 主流 CV Schema（YOLO / COCO / VOC / ImageFolder / MVTec AD / CSV / JSONL）
- ✅ 两个 VLM Schema（ShareGPT / ms-swift），仅 template Q&A 后端
- ✅ 基础增强（翻转 / 旋转 / 亮度对比度 / 噪声）
- ✅ 划分（按比例 / 按数量 / 分层）
- ✅ Pipeline YAML + 预置模板
- ✅ CLI + GUI 双前端

---

## 2. 用户起点与能力分层

### 2.1 用户的真实起点

DataForge 的用户不都从"已有干净数据集"出发。真实起点至少有四种：

| 起点 | 场景 | 占比估计 |
|---|---|---|
| **零散图片** | 一个文件夹堆着 3000 张手机拍的产品照 | 40% |
| **半结构化** | 按类别分了文件夹但没标注 / 标注了一部分 | 30% |
| **结构化无标注** | 从公开数据源下载的图，组织规范但未标注 | 15% |
| **完整标注数据** | 已有 COCO/YOLO 数据集想转格式或做增强 | 15% |

一个真正的数据工坊必须服务**所有四种起点**。

### 2.2 三层能力模型

DataForge 的能力按用户数据的"成熟度"自底向上分三层：

```
┌─────────────────────────────────────────────┐
│  第三层(差异化层):VLM 格式桥梁              │
│  能力:Q&A 模板生成、VLM 格式导出、token 校验 │
│  输入:已有标注的数据集                      │
│  输出:ShareGPT / Swift 训练数据              │
│  占比:20% 用户会用到                         │
├─────────────────────────────────────────────┤
│  第二层(主线层):CV 训练数据生产             │
│  能力:格式转换、合规检查、划分、增强、导出   │
│  输入:结构化 + 有标注的数据集                │
│  输出:YOLO / COCO / VOC / ImageFolder /      │
│        MVTec / CSV / JSONL                   │
│  占比:90% 用户会用到(核心功能)              │
├─────────────────────────────────────────────┤
│  第一层(基础层):原始数据整理                │
│  能力:批量导入、分类建议、质检去重、         │
│        基础标注、结构化落地                   │
│  输入:一堆乱图 / 半结构化数据                │
│  输出:标准 DataForge 布局的数据集            │
│  占比:70% 用户会用到(起点不同)              │
└─────────────────────────────────────────────┘
```

**注意 v1.2 的重新命名**：第三层从"灵魂层"改为"差异化层"，因为"灵魂"暗示的是主干地位，与实际占比不符。第二层才是真正的主线。

### 2.3 层间关系原则

**原则 1：每一层自成闭环。**

用户可以只用第一层整理数据就停止；可以只用第二层做格式转换；可以直接进第三层导出 VLM 格式。不强制走完整流程。

**原则 2：层间通过标准中间态衔接。**

第一层的输出 = 第二层的输入 = DataForge 标准布局。第二层的输出 = 第三层的输入 = 已校验的结构化数据集。中间态用 Dataset 对象 + `.dataforge/project.json` 表达。

**原则 3：第二层是产品的真正核心，优先保障。**

- 第一层（整理）：决定装机量 —— 所有 CV 用户都需要
- **第二层（CV 格式）：决定产品成败 —— 这是日常主要输出**
- 第三层（VLM 桥梁）：决定声量 —— 吸引 VLM 社区关注和讨论

三层缺一不可，但**优先级是 2 > 1 > 3**。开发精力分配应该反映这个顺序。

### 2.4 用户旅程示例

**场景 A（主线）：工业工程师手里有 500 张缺陷照片**

1. 第一层：拖拽进 DataForge → 用文件名前缀分类建议把正常/缺陷分开 → 质检去模糊 → 用矩形工具框缺陷 → 落地
2. 第二层：选 YOLO Schema → readiness bar 显示"需要划分" → 一键划分 → 导出
3. **第三层不用**

**场景 B（主线）：研究员从网上爬了 2000 张图训练分类模型**

1. 第一层：批量导入 → 按文件名前缀分类建议 → 手动调整 → 去重 → 落地
2. 第二层：选 ImageFolder Schema → 划分 → 导出
3. **第三层不用**

**场景 C（主线）：算法团队已有 YOLO 数据集想改用 COCO**

1. **第一层不用**
2. 第二层：导入 YOLO → 合规检查 → 选 COCO Schema → 导出
3. **第三层不用**

**场景 D（主线）：工业质检团队做 MVTec 异常检测**

1. 第一层：导入工业数据 → 按子目录识别 good/anomaly → 质检 → 落地
2. 第二层：选 MVTec AD Schema → 导出
3. **第三层不用**

**场景 E（差异化）：VLM 从业者想用公开 COCO 微调 Qwen-VL**

1. **第一层不用**
2. 第二层：导入 COCO → 质检 → 合规检查通过
3. 第三层：选 ShareGPT Schema → 配置 Q&A 模板 → 预览 → 导出 LLaMA-Factory 数据

**五个场景里四个完全不用 VLM 模块**——这就是为什么 VLM 不能是主定位。

---

## 3. 整体架构

### 3.1 三层三包

```
用户层:GUI 桌面  │  CLI 终端  │  Python 脚本
              ↓        ↓        ↓
              └────────┴────────┘
                       ↓
核心层:dataforge-core(纯 Python 库)
                       ↓
依赖层:Pillow · numpy · pydantic · diskcache · PyYAML
```

### 3.2 三个包的职责

| 包名 | PyPI 名 | 职责 | 目标用户 |
|---|---|---|---|
| Core | `dataforge-core` | 所有数据逻辑、无 GUI 依赖 | 脚本用户、Jupyter、CI |
| CLI | `dataforge-cli` | 命令行入口 | 服务器用户、自动化 |
| GUI | `dataforge` | 桌面应用（PyQt6） | 标注员、工业工程师 |

**关键约束**：GUI 和 CLI **只依赖 Core 的公开 API**（`dataforge.api`），不直接访问 core 内部模块。

### 3.3 Core 的子模块划分

| 子模块 | 一句话职责 | 不做什么 |
|---|---|---|
| `models` | 定义 Dataset / Shape / ImageInfo 等领域对象 | 不含任何行为 |
| `ingest` | 数据整理入口（批量导入、分类建议、去重） | 不做标注 |
| `scan` | 扫描目录、推断布局、构建 Dataset 对象 | 不解析单个标注文件 |
| `io` | 统一的标注读写入口 | 不关心业务逻辑 |
| `schema` | 每种导出格式的结构定义、槽位、合规检查、writer | 不做 IO 细节 |
| `pipeline` | Pipeline / Step 类、YAML 序列化、执行器 | 不实现具体步骤 |
| `transform` | 增强、几何变换、格式转换 | 不做质量判断 |
| `quality` | 模糊/空白/过曝检测、感知哈希去重 | 不管标注内容 |
| `annotate` | 基础标注能力（矩形、图像级标签） | 不做复杂标注 |
| `cache` | 索引缓存、缩略图缓存 | 不涉及业务 |
| `project` | 项目状态持久化、history.jsonl | 不做 UI 状态 |
| `plugins` | 插件发现、注册、加载（v1.1+） | v1 保留接口不实现 |
| `api` | 对外公开的顶层函数入口 | 只是 re-export |

**注意 v1.2 的调整**：原来独立的 `vlm` 子模块在 v1.2 里**合并进 `schema` 模块**（ShareGPT 和 ms-swift 作为两个 Schema，Q&A 模板生成器是 Schema writer 内部的工具函数）。这反映了 VLM 的地位从"独立模块"降到"Schema 的一种"。

### 3.4 依赖方向铁律

```
所有子模块  → models, plugins     (可以)
schema, io, scan, ingest, annotate, quality, transform
    → 彼此不互相依赖(并列,禁止横向依赖)
pipeline      →  上述所有           (可以)
api           →  上述所有           (可以)
GUI, CLI      →  仅 api             (只通过公开接口)
```

**典型违反**：
- ❌ `models` 里 import schema（反向依赖）
- ❌ `transform` 里 import quality（横向依赖）
- ❌ GUI 里 `from dataforge.schema.yolo import YOLO`（绕过 api）

### 3.5 为什么拆三个包

1. **脚本用户可在 Jupyter 里 `import dataforge`**，不用 GUI
2. **CI 流水线跑 CLI 做数据合规检查**
3. **社区贡献者贡献新 Schema 时不碰 GUI 代码**

---

## 4. 核心领域模型

### 4.1 六个一等公民

| 概念 | 对应类 | 一句话定义 |
|---|---|---|
| **Dataset** | `Dataset` | 数据集的完整元数据视图 |
| **Shape** | `Shape` | 一个标注形状（像素坐标） |
| **Schema** | `Schema` | 一个目标导出格式的完整声明 |
| **Slot** | `Slot` | Schema 中的一个槽位 |
| **Pipeline** | `Pipeline` | 有序的步骤列表 |
| **IngestJob** | `IngestJob` | 一次数据整理任务 |

### 4.2 Dataset 的设计规则

**规则 1：Dataset 是元数据视图，不是数据容器。** shapes 按需 lazy load。

**规则 2：Dataset 几乎是只读的。** 修改通过 fileops 操作磁盘，重新扫描生成新对象。

**规则 3：Dataset 有 fingerprint。** 用于缓存失效。

**规则 4：Dataset 自带 layout 和 detected_format。**
- `layout`：standard / flat / single / coco / mvtec / recursive / **raw**
- `detected_format`：labelme / yolo / coco / voc / mixed / none

### 4.3 Shape / Annotation 的设计规则

**规则 1：Shape 用像素坐标。** 内部只有一种表示，读入时转，导出时转回。

**规则 2：Shape 保留原始属性。** `attributes: dict[str, str]` 保存扩展信息。

**规则 3：Annotation 同时支持传统 shapes 和 VLM conversations。** 但 v1 主要用 shapes，conversations 字段预留给 VLM Schema 使用。

### 4.4 IngestJob 的设计规则

**规则 1：IngestJob 声明"从哪来、怎么分、去哪"。** 三个核心字段：sources / classification_rules / target_layout / target_root。

**规则 2：IngestJob 可预览、可回退。** 执行前 dry run，用户确认后落地。默认复制不移动。

**规则 3：分类规则是可插拔的 strategy。v1 内置规则收窄为 4 种**：
- `by_filename_prefix`（按文件名前缀）
- `by_subdir`（按所在子目录）
- `by_exif_date`（按拍摄日期）
- `manual`（进入 GUI 手动分类界面）

视觉聚类、AI 分类留给 v1.1+。

---

## 5. Schema 系统（最重要的子系统）

### 5.1 为什么 Schema 是核心

一切导出格式——YOLO、COCO、VOC、MVTec、ShareGPT、ms-swift……——本质上都在回答三个问题：

1. 这个格式需要哪些**槽位**（Slot）？
2. 每个槽位的**验收标准**是什么？
3. 怎么把 Dataset **写**成这个格式？

Schema 系统把这三个问题统一结构化，所有格式走同一套接口。

### 5.2 Schema 的组成

每个 Schema 对象声明：
- `key`：机器标识符
- `display_name`：用户可见名称
- `description`：一句话说明
- `task_types`：支持哪些任务
- `slots`：槽位列表
- `writer`：导出函数
- `options_class`：导出选项数据类
- `directory_preview`：目录结构预览
- `docs_url`：外部文档链接

### 5.3 Slot 的设计规则

**规则 1：Slot 必须有 validator。** 返回 SlotStatus（ok / current / required / action / fix_command）。

**规则 2：Slot 分为 required 和 optional。** 只有 required 全部 ok，ComplianceReport 才算 ready。

**规则 3：Slot 的 kind 枚举固定。** `"images"` / `"labels"` / `"split"` / `"meta"` / `"config"` 五类。

### 5.4 ComplianceReport 的语义

ComplianceReport 是 Schema 系统和上层之间的**唯一接口**。
- `ready`：是否全部必填槽位通过
- `missing()`：未通过的 Slot 列表
- `required_count` / `required_filled`：进度数据

**设计约束**：任何 UI 组件想知道"数据集是否可以导出为 X 格式"，**必须**通过 ComplianceReport。

### 5.5 Schema 注册表

所有内置 Schema 在 `schema/__init__.py` 注册到全局 REGISTRY。对外暴露：
- `get(key)`
- `all_schemas()`
- `schemas_for(task_type)`

### 5.6 Schema 优先级（v1.2 重排）

v1 发布时**必须内置**的 Schema，按优先级：

**🔴 基石（P0，必做，决定产品能不能用）**：
| Schema | 用途 | 主要用户 |
|---|---|---|
| **YOLO (Ultralytics)** | 目标检测最主流 | 所有做检测的用户 |
| **COCO (detection)** | 学术/研究标准 | 研究员 |
| **Pascal VOC** | 经典格式，兼容广 | 传统 CV 项目 |
| **ImageFolder** | 分类任务标准 | 做分类的用户 |

**🟠 核心场景（P1，必做，决定产品覆盖面）**：
| Schema | 用途 | 主要用户 |
|---|---|---|
| **MVTec AD** | 工业异常检测 | 工业质检团队 |
| **CSV** | 通用表达、Pandas 友好 | 分析/非标准场景 |
| **JSON Lines** | 流式、HuggingFace 兼容 | 大数据集场景 |

**🟡 差异化（P2，必做，精简到 2 个）**：
| Schema | 用途 | 主要用户 |
|---|---|---|
| **ShareGPT (LLaMA-Factory)** | VLM 微调最流行 | VLM 从业者 |
| **ms-swift (ModelScope)** | 中文 VLM 主流 | 中文 VLM 社区 |

**🟢 社区贡献（P3，v1 可不内置）**：
- LLaVA、Unsloth、COCO-seg、YOLO-seg、DOTA、KITTI、HuggingFace Datasets……
- 通过插件机制由社区贡献（插件机制本身是 v1.1+ 开放）

**关键观察**：主线 Schema 是 7 个，差异化 Schema 只有 2 个。这个比例说明一切。

### 5.7 VLM 格式的特殊处理（Schema 系统内的一小节）

VLM Schema（ShareGPT / ms-swift）相比其他 Schema 多两个步骤：

**步骤 1：Q&A 生成（将标注转为对话）**

v1 只提供 **template 后端**——基于规则模板从 shapes/类别自动生成对话。内置 5 个模板类别：
- `describe`：图像描述
- `detection_count`：数一下图里有几个 X
- `detection_locate`：X 在图的什么位置
- `classification`：这是不是 X？
- `industrial_defect`：工业缺陷专用

**v1 不做**：本地 LLM 后端、OpenAI 兼容 API 后端、自定义 Jinja2 模板。这些留给 v1.1+。

**步骤 2：Token 校验（导出前合规检查）**

- 每个 sample 的 `<image>` token 数 == images 数组长度
- 第一条 human 消息前必须有 `<image>`
- 角色序列合法：system? → human → gpt → human → gpt …

失败时自动修复（插入 `<image>`、重排对话），用户明确同意后执行。

**步骤 3：dataset_info.json 生成（LLaMA-Factory 专用）**

- 默认生成
- 检测已有文件冲突时 diff 问用户
- 字段自动填充（formatting / columns / tags / stage）

这三个能力实现在 Schema 系统内部（`schema/writers/sharegpt_impl.py` 和 `schema/writers/swift_impl.py`），不是独立模块。

---

## 6. 数据整理模块（第一层能力）

### 6.1 模块定位

这是 DataForge 的**基础盘**。没有这一层，用户手里的一堆乱图根本进不来系统。所有后续能力建立在这一层之上。

设计目标：**让用户在 10 分钟内把一堆乱图变成结构化数据集**。

### 6.2 批量导入规则

**规则 1：支持多种输入源**
- 单个目录（递归扫描）
- 多个目录合并
- zip / tar 压缩包（自动解压）
- 拖拽文件进 GUI

**规则 2：导入时不修改原文件** —— 默认**复制**，用户显式选"移动"才移动。

**规则 3：导入时做三件事** —— 基础扫描、完整性检查、预览。

### 6.3 自动分类建议（v1 简化版）

**核心理念**：不强迫手工分类，提供**建议**供用户采纳或调整。

**v1 内置 4 种规则**：
- **文件名模式**（`IMG_001_good.jpg` → good）
- **子目录结构**（继承原有目录意图）
- **EXIF 日期**（相同日期的可能是同批数据）
- **手动**（直接进 GUI 分类界面）

**v1.1+ 可能加入**：视觉相似聚类、AI 分类。

**规则 1：建议是可编辑的起点，不是终点。** GUI 提供拖动 / 重命名 / 合并 / 拆分 / 删除。

**规则 2：键盘友好。** 方向键浏览、数字键赋类别、Delete 删除。

**规则 3：用户可以"什么建议都不用"直接手动分类。** 不是所有数据都适合规则分类，手动兜底必须流畅。

### 6.4 去重与质检集成

整理阶段调用 `quality` 模块。标准顺序：
1. 导入 → 预览
2. 去重（感知哈希）
3. 质检（模糊/空白/过曝）
4. 分类建议
5. 用户调整
6. 基础标注（可选）
7. 结构化落地

### 6.5 基础标注能力（v1 收窄）

**v1 支持 2 种标注形态**：
- **矩形**（目标检测、缺陷定位）—— 覆盖 80% 工业和研究场景
- **图像级标签**（分类 / 多标签）—— 覆盖所有分类任务

**v1 不支持（留给 v1.1+）**：
- 多边形（分割）
- 点标注（关键点）
- 线段 / 圆 / 旋转框

**键盘优先**：
- `A` / `D`：上一张 / 下一张
- `R`：矩形工具
- `数字键`：快速选择已有标签
- `Delete`：删除 shape
- `Ctrl+S`：保存
- `E`：编辑模式

**内部格式**：基于 LabelMe JSON 扩展的统一表达。导出 YOLO / COCO / VOC 是 Schema 系统的职责。

### 6.6 结构化落地

整理终点 = 标准 DataForge 布局：

```
<root>/
├── <category_1>/
│   ├── images/
│   └── labels/
├── <category_2>/
│   ├── images/
│   └── labels/
└── .dataforge/
    ├── project.json
    ├── history.jsonl
    └── ingest.json
```

所有后续操作基于这个布局。

---

## 7. Pipeline 系统

### 7.1 核心思想

节点编辑器已砍。替代方案：**步骤式管道**——有序 Step 列表，每步可启用/禁用、调参、排序。

一份 YAML = 一次可复现的数据准备流程。

### 7.2 Pipeline 的数据结构规则

**规则 1：Pipeline = input + target + ordered steps**
- `input`：输入数据集
- `target`：目标 Schema
- `steps`：有序列表

**规则 2：步骤有序、可禁用**。

**规则 3：步骤的 kind 是枚举**。

v1 支持的 kind：

| kind | 归属 | 作用 |
|---|---|---|
| `ingest` | 第一层 | 原始数据导入到标准布局 |
| `classify_suggest` | 第一层 | 基于规则的分类建议 |
| `quality_check` | 跨层 | 质量过滤 |
| `dedup` | 跨层 | 去重 |
| `filter` | 跨层 | 按规则筛选 |
| `transform` | 第二层 | 格式转换 |
| `augment` | 第二层 | 数据增强 |
| `split` | 第二层 | 训练集划分 |
| `export` | 第二/三层 | 导出到目标 Schema |

**v1 不支持（v1.1+ 加入）**：
- `annotate_ai`（AI 预标注）
- `qa_generate`（外部 LLM Q&A）

（VLM 格式的 Q&A template 生成合并在 `export` 步骤内部，不单独做 step kind。）

**规则 4：步骤参数强类型** —— pydantic 校验 YAML。

### 7.3 Pipeline YAML 格式规则

- 顶层必须有 `name`、`input`、`target`、`steps`
- `steps` 是列表，每项必须有 `kind`
- 支持 `$var` 变量替换
- 路径支持 `~` 展开和相对路径

### 7.4 执行器规则

**规则 1：可中断** —— 当前步骤完成后优雅停止。

**规则 2：必须报告进度** —— `progress_cb(done, total, name)`。

**规则 3：留下 manifest** —— 输出目录写 `manifest.json`：YAML、输入指纹、每步结果、输出文件。

**规则 4：失败策略每步独立** —— `on_fail: abort | warn | skip`。

### 7.5 预置模板（v1.2 重排）

按"用户目的"分组，CV 模板数量占主导：

**🔴 训练 CV 小模型（P0，主线，5 个）**：
- `raw-to-yolo`：乱图 → 分类 → 标注 → YOLO 训练数据
- `raw-to-classify`：乱图 → 按规则分类 → ImageFolder
- `industrial-defect`：工业散图 → 分 good/anomaly → MVTec AD
- `yolo-migrate`：已有 YOLO → 质检去重 → 重新划分 → 优化导出
- `dataset-merge`：多源数据集合并（基础版）

**🟡 训练 VLM（P1，差异化，2 个）**：
- `coco-to-sharegpt`：COCO → Q&A 模板 → ShareGPT (LLaMA-Factory)
- `yolo-to-swift`：YOLO → Q&A 模板 → ms-swift

**数量比例 5:2** —— 反映产品定位。

用户进应用第一眼看到的模板卡片中，**前 5 个是 CV 训练，后 2 个是 VLM**。这种视觉层级本身就在传达定位。

---

## 8. IO 层（读写统一）

### 8.1 读的规则

**规则 1：统一入口 `parse_annotation(path, image, classes)`**。

**规则 2：parser 必须容错** —— 返回 ParseResult(None, error="...") 而不是抛异常。

**规则 3：坐标统一化** —— 转成像素坐标。

**规则 4：COCO 的特殊性** —— 单文件多图，按 mtime 缓存。

### 8.2 写的规则

**规则 1：写入由 Schema.writer 负责**。

**规则 2：写入前必须校验** —— 调 schema.validate(dataset)。

**规则 3：写入原子化** —— 先临时目录再 move。

**规则 4：写入报告 ExportReport** —— 成功数、失败列表、警告列表。

### 8.3 格式自动检测规则

按**目录特征**判断，启发式。用户可以**显式覆盖**检测结果。

---

## 9. GUI 架构

### 9.1 总体规则

**规则 1：GUI 不碰业务逻辑**。

**规则 2：AppState 是单一数据源**。

**规则 3：视图之间不直接通信** —— 通过 AppState 中转。

### 9.2 视图层次

顶层导航两大区：

**TOP 区：**
- **首页**：欢迎页 + 最近数据集列表 + 模板入口
- **工坊**：整理 + 浏览 + 详情（三个视图通过 stacked widget 切换）
- **导出**：Schema 选择 + readiness bar + 导出

**BOTTOM 区：**
- **设置**：主题、缓存、偏好

### 9.3 三个核心工作台

工坊视图内部三个子工作台：

- **整理台**：拖入原始数据 → 看分类建议 → 调整 → 落地
- **浏览台**：已有结构化数据的缩略图网格 + 类别树
- **标注台**：单图详情 + 矩形工具 + 图像级标签

三个工作台共享 AppState.dataset，用户通过 Tab 切换。

### 9.4 Worker 线程规则

**规则 1：任何 > 200ms 操作必须进 worker**。

**规则 2：统一用 BatchRunner** —— 封装 worker + ProgressDialog。

**规则 3：信号必须在主线程发射** —— QueuedConnection。

**规则 4：Worker 停止要安全** —— 最多等 3 秒。

### 9.5 readiness bar 规则

显示当前 Dataset 对当前目标 Schema 的合规状态。
- 调 `schema.validate(dataset)` 得 ComplianceReport
- 每个 required slot 显示成 pill
- 悬停显示 tooltip
- 点击未通过的 slot 跳转到修复入口

### 9.6 视图设计禁令

**禁令 1：不允许超过三级菜单**。
**禁令 2：不允许模态弹窗嵌套**。
**禁令 3：不允许无进度反馈的长操作**。
**禁令 4：不允许用字面量颜色**。

---

## 10. CLI 设计

### 10.1 CLI 与 GUI 的对等原则

**任何 GUI 里能做的事，CLI 都能做。反之亦然。**

### 10.2 命令结构（v1 范围）

| 命令 | 对象 | 作用 |
|---|---|---|
| `ingest` | 源目录 | 整理原始数据到标准布局 |
| `scan` | 目录 | 扫描并显示摘要 |
| `check` | 目录 + --format | 对 schema 做合规检查 |
| `convert` | 目录 + --from + --to | 格式转换 |
| `export` | 目录 + --format + --out | 导出到 schema |
| `split` | 目录 + --ratio | 划分 |
| `augment` | 目录 + --out | 数据增强 |
| `quality` | 目录 | 质量检查 |
| `dedup` | 目录 | 去重 |
| `run` | pipeline.yaml | 执行管道 |
| `init` | --template | 创建新 pipeline 模板 |
| `schemas` | — | 列出所有 schema |

**v1 不做（v1.1+ 加入）**：
- `annotate`（AI 预标注命令）
- `plugins`（插件管理命令）

### 10.3 交互质量规则

- `rich` 做进度、表格、彩色输出
- 错误信息必须**可操作**
- 成功后打印关键指标
- 非交互场景用 `--json`

### 10.4 命令行规范

遵守 POSIX：短选项单字母、长选项蛇形、布尔用 `--xxx/--no-xxx`、路径参数放最后。

---

## 11. 扩展点（v1.1+ 开放）

### 11.1 v1 的扩展策略

**v1 不开放插件系统**。所有 Schema / 功能在 core 内部实现并发布。

**原因**：
- 插件 API 稳定需要产品本身先稳定
- v1 首要任务是验证核心假设，不是建生态
- 过早开放插件会锁死不成熟的接口

**但 v1 在架构上预留扩展**：
- Schema 注册表设计支持 `register()` 调用
- Pipeline Step 系统支持新 kind 注册
- 代码组织不假设"只有内置模块"

### 11.2 v1.1+ 的插件类型

| 类型 | 用途 |
|---|---|
| Schema 插件 | 新增导出格式 |
| Q&A 后端插件 | 新增 VLM 对话生成后端（Ollama / OpenAI） |
| 预标注插件 | 新增 AI 预标注模型 |
| 分类建议插件 | 新增自动分类策略 |

### 11.3 预期的社区插件方向

提前告诉社区哪些方向有价值：
- `dataforge-plugin-sam`：Segment Anything 预标注
- `dataforge-plugin-grounding-dino`：文本 prompt 预标注
- `dataforge-plugin-3d`：KITTI / nuScenes 3D 格式
- `dataforge-plugin-huggingface`：HF Datasets 导入导出
- `dataforge-plugin-llm`：本地 LLM / OpenAI 后端

---

## 12. 错误处理、日志、配置

### 12.1 错误分类

| 类型 | 处理 |
|---|---|
| **用户错误** | 清晰中文提示 + 建议 |
| **数据错误** | 跳过该文件 + 汇总报告 |
| **程序错误** | 全栈记录到日志 + 用户侧通用提示 |

### 12.2 异常层次

`DataForgeError`（根）
- `UserError` / `DataError` / `ConfigError` / `PluginError`

### 12.3 日志规则

- 所有模块用 `logging.getLogger(__name__)`
- 级别语义固定（DEBUG / INFO / WARNING / ERROR）
- 日志去敏感
- 文件滚动（1MB × 5 份）

### 12.4 配置规则

三层配置（低到高）：
1. 内置默认值
2. `~/.dataforge/config.yaml`
3. `<dataset>/.dataforge/project.json`
4. 命令行 / UI 输入

所有配置用 pydantic 校验。

---

## 13. 测试策略

### 13.1 分层测试

| 层 | 工具 | 覆盖率目标 |
|---|---|---|
| Core 单元测试 | pytest | ≥ 80% |
| Core 属性测试 | hypothesis | 关键算法必备 |
| Schema 往返 | pytest | 所有内置 schema 100% |
| CLI 端到端 | pytest + subprocess | 核心命令全覆盖 |
| GUI 冒烟 | pytest-qt | 关键视图能打开 |
| 真实数据回归 | 手工 | 发布前必跑 |

### 13.2 关键测试场景

1. **格式往返**：LabelMe → YOLO → COCO → LabelMe，shapes 不变
2. **扫描所有布局**：raw / standard / flat / single / coco / mvtec 各一个 fixture
3. **合规检查**：每个 Schema 对完美 / 残缺数据集报告正确
4. **Pipeline 执行**：所有预置模板能跑通
5. **坏数据容错**：不崩溃，只 warning
6. **整理流程**：raw → ingest → 标准布局
7. **零外部依赖场景**：只装 dataforge、不连网、不装任何 AI 模型，完整跑通 CV 训练数据准备

### 13.3 Fixture 数据集

- `tiny_labelme/`（5 图）
- `tiny_yolo/`（5 图）
- `tiny_coco/`（5 图）
- `broken_mixed/`（含坏文件）
- `mvtec_sample/`（工业场景）
- `raw_unorganized/`（20 张杂乱图）

### 13.4 CI 规则

GitHub Actions 跑 lint / type check / 单元测试 / 构建三包。PR 必须绿灯。

---

## 14. 打包与发布

### 14.1 三包版本策略

三个包共享版本号。

### 14.2 版本号

遵守 SemVer。v0.x 允许破坏性变更。

### 14.3 分阶段发布策略（v1.2 新增）

**v0.1（最小可用，目标 8-10 周）**：
- 第二层主线 Schema（YOLO / COCO / VOC / ImageFolder / MVTec）
- 第一层基础功能（批量导入 + 文件名分类 + 质检 + 矩形标注）
- 第三层 ShareGPT Schema（template Q&A）
- 不做 Pipeline YAML、不做 CLI，只有 GUI

**v0.2（完整 v1，再 8-10 周）**：
- 补齐第一层其余功能（子目录分类、EXIF 分类、去重集成）
- 补齐 Schema（CSV / JSONL / ms-swift）
- 补齐 CLI 所有命令
- Pipeline 系统 + 7 个预置模板

**v1.0（稳定发布，再 4-6 周）**：
- 修 v0.2 bug
- 完善文档、打包分发（.exe / .app）
- 首发 PyPI + GitHub Release

总周期约 **5-6 个月到 v1.0**。

### 14.4 发布节奏

v1.0 之后：
- **开发期（6-12 月）**：每 2-3 周 MINOR
- **稳定期（12-24 月）**：每月 MINOR + 随时 PATCH

### 14.5 桌面分发

- Windows：PyInstaller 的 `.exe` + 可选 MSI
- macOS：Briefcase 的 `.app` + DMG
- Linux：AppImage（可选）

### 14.6 许可证

**Apache-2.0，三个包一致**。

---

## 15. 从现有代码迁移的原则

### 15.1 迁移顺序（按依赖拓扑）

1. **删除**：节点编辑器、过度复杂的标注编辑器代码
2. **models 层**：加 fingerprint / VLM conversations 字段 / raw layout
3. **schema 层**：重构 `exporter/*.py` 成 Schema 对象（**优先处理 CV 格式**，VLM 格式最后）
4. **io 层**：统一 annotation_formats 和 writer
5. **ingest 层（新）**：批量导入、4 种分类规则、结构化落地
6. **annotate 层（新）**：从现有代码抽取矩形标注 + 图像级标签
7. **pipeline 层**：Step 和 Pipeline
8. **api 层**：对外接口 facade
9. **cli 层**：新包
10. **gui 层**：重构只依赖 api、新增整理台
11. **plugins 层**：v1.1+ 再做

### 15.2 每一步的完成标准

三条缺一不可：
1. 有对应的测试
2. 有文档
3. 所有已有测试仍然绿灯

### 15.3 迁移优先级原则（重要）

**第二层 > 第一层 > 第三层**：
- 先保证主线 CV 格式稳定（这是产品能用的底线）
- 再做整理功能（这是装机量基础）
- 最后做 VLM 桥梁（这是差异化加分）

这个顺序意味着：**v0.1 发布时哪怕整理台还很简单、VLM 只有 ShareGPT 一个 Schema，只要主线 CV 格式稳定，产品已经可用**。

### 15.4 允许"脏操作"的情况

commit 必须标 `TODO(cleanup)`：
- 解 bug 急需发版
- 实验性功能（`experimental/` 子模块）
- 平台特定代码

---

## 16. 对开发者的三条自我约束

这是给你自己看的铁律。

### 约束 1：不要被"还差一点"骗

每次想加功能前先问：这在 v1 功能清单里吗？不在就拒绝。v1.1 的功能放进 v1 就是延期的开始。

### 约束 2：每周对齐一次定位

每周检查一次：这周做的事，是给 80% CV 用户还是 20% VLM 用户？如果连续两周都在服务后者，停下来先做前者。

### 约束 3：发布节奏优先于功能数量

**8-10 周发出 v0.1** 比"12 周发出更完整的版本"重要得多。真实用户反馈比设想的功能清单有价值 10 倍。

---

## 附录 A：术语表

| 术语 | 定义 |
|---|---|
| **格子补齐** | 声明目标格式的槽位，由工具告知缺什么 |
| **三层能力** | 基础整理 / CV 训练数据（主线）/ VLM 桥梁（差异化） |
| **Schema** | 一种目标导出格式的完整声明 |
| **Slot** | Schema 中的一个槽位 |
| **ComplianceReport** | `schema.validate(dataset)` 的结果 |
| **Pipeline** | 有序的 Step 列表 |
| **IngestJob** | 一次数据整理任务的声明 |
| **主线 / 差异化** | 主线是 CV 训练数据，差异化是 VLM 桥梁 |
| **AppState** | GUI 全局状态单一数据源 |

## 附录 B：设计方案的版本与演进

**v1.2（当前）** 核心变更：
- 定位纠偏（CV 主线，VLM 差异化）
- VLM 模块降级（合并进 Schema 系统）
- 初期简单原则落地（v1 功能清单）
- 分阶段发布策略（v0.1 → v0.2 → v1.0）

**v1.3（暂定，基于 v0.1 用户反馈）**：
- 根据真实反馈决定是深化 CV 能力（多边形标注、更多增强）还是补齐 VLM（本地 LLM、自定义模板）

**v2.0（暂定 2026 下半年）** 基于 v1 实际运行数据：
- 插件系统正式开放
- 社区贡献的 Schema / 预标注后端集成
- 3D 点云支持（如果需求验证）
- Web 前端（如果远程协作需求明确）

**不会做的方向**：视频标注、在线协同、模型训练、模型部署、DataForge 自有 AI 服务。

---

**文档结束。**

本设计方案是活文档。实际开发中发现原则需要修订时，先改本文档、讨论、合并，再改代码。
