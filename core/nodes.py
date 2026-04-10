"""Node specification registry — defines all available node types.

Every tool in the app is a node: data source, processing, output format.
Each node declares its ports, parameters, and category.

Pure Python — no PyQt imports.

Usage::

    from core.nodes import NODE_REGISTRY, NodeSpec
    spec = NODE_REGISTRY["data_source"]
    print(spec.label, spec.category, spec.parameters)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Parameter:
    """One configurable parameter on a node."""
    name: str
    label: str
    param_type: str       # "int" | "float" | "bool" | "str" | "choice" | "path"
    default: object
    choices: tuple[str, ...] = ()     # for "choice" type
    min_val: float | None = None
    max_val: float | None = None
    tooltip: str = ""


@dataclass(frozen=True)
class PortSpec:
    """Input or output port definition."""
    name: str
    data_type: str = "dataset"   # "dataset" | "images" | "split"


@dataclass(frozen=True)
class NodeSpec:
    """Complete specification of a node type."""
    node_id: str
    label: str
    category: str             # "input" | "processing" | "output"
    icon: str = ""            # FluentIcon name hint for GUI
    inputs: tuple[PortSpec, ...] = ()
    outputs: tuple[PortSpec, ...] = ()
    parameters: tuple[Parameter, ...] = ()


# =====================================================================
# Node Registry
# =====================================================================

NODE_REGISTRY: dict[str, NodeSpec] = {}


def _reg(spec: NodeSpec) -> None:
    NODE_REGISTRY[spec.node_id] = spec


# ---------- Input nodes ----------

_reg(NodeSpec(
    node_id="data_source",
    label="数据源",
    category="input",
    icon="DATABASE",
    inputs=(),
    outputs=(PortSpec("输出", "dataset"),),
    parameters=(
        Parameter("path", "数据集路径", "path", ""),
    ),
))

# ---------- Processing nodes ----------

_reg(NodeSpec(
    node_id="quality_check",
    label="质量检查",
    category="processing",
    icon="CERTIFICATE",
    inputs=(PortSpec("输入", "dataset"),),
    outputs=(PortSpec("输出", "dataset"),),
    parameters=(
        Parameter("blur_threshold", "模糊阈值", "float", 100.0,
                  min_val=1, max_val=5000, tooltip="Laplacian 方差，越小越模糊"),
        Parameter("check_corrupt", "检测损坏", "bool", True),
        Parameter("check_blank", "检测空白", "bool", True),
    ),
))

_reg(NodeSpec(
    node_id="dedup",
    label="重复检测",
    category="processing",
    icon="COPY",
    inputs=(PortSpec("输入", "dataset"),),
    outputs=(PortSpec("输出", "dataset"),),
    parameters=(
        Parameter("threshold", "相似阈值", "int", 5,
                  min_val=0, max_val=20, tooltip="0=完全相同 5=视觉近似"),
    ),
))

_reg(NodeSpec(
    node_id="augment",
    label="数据增强",
    category="processing",
    icon="ADD",
    inputs=(PortSpec("输入", "dataset"),),
    outputs=(PortSpec("输出", "dataset"),),
    parameters=(
        Parameter("flip_h", "水平翻转", "bool", True),
        Parameter("flip_v", "垂直翻转", "bool", False),
        Parameter("rotate90", "随机旋转", "bool", True),
        Parameter("brightness", "亮度抖动", "bool", True),
        Parameter("n_per_image", "每张生成", "int", 3, min_val=1, max_val=50),
    ),
))

_reg(NodeSpec(
    node_id="split",
    label="数据集划分",
    category="processing",
    icon="TILES",
    inputs=(PortSpec("输入", "dataset"),),
    outputs=(PortSpec("输出", "split"),),
    parameters=(
        Parameter("train", "训练集比例", "float", 0.8, min_val=0, max_val=1),
        Parameter("val", "验证集比例", "float", 0.1, min_val=0, max_val=1),
        Parameter("test", "测试集比例", "float", 0.1, min_val=0, max_val=1),
        Parameter("stratified", "分层采样", "bool", True),
    ),
))

# ---------- Output nodes ----------

_reg(NodeSpec(
    node_id="export_yolo",
    label="YOLO 导出",
    category="output",
    icon="SEND",
    inputs=(PortSpec("输入", "split"),),
    outputs=(),
    parameters=(
        Parameter("out_dir", "输出目录", "path", ""),
        Parameter("copy_images", "复制图片", "bool", True),
    ),
))

_reg(NodeSpec(
    node_id="export_coco",
    label="COCO 导出",
    category="output",
    icon="SEND",
    inputs=(PortSpec("输入", "split"),),
    outputs=(),
    parameters=(
        Parameter("out_dir", "输出目录", "path", ""),
        Parameter("copy_images", "复制图片", "bool", True),
    ),
))

_reg(NodeSpec(
    node_id="export_imagefolder",
    label="ImageFolder 导出",
    category="output",
    icon="SEND",
    inputs=(PortSpec("输入", "dataset"),),
    outputs=(),
    parameters=(
        Parameter("out_dir", "输出目录", "path", ""),
    ),
))


# ---------- Helpers ----------

def nodes_by_category(cat: str) -> list[NodeSpec]:
    """Return all nodes in a category, ordered by registration."""
    return [s for s in NODE_REGISTRY.values() if s.category == cat]
