"""Node editor integration using OdenGraphQt library.

OdenGraphQt provides: zoom/pan, port connections, Tab search,
right-click menu, properties panel, undo/redo — all out of the box.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_API", "pyqt6")

from OdenGraphQt import BaseNode, NodeGraph, NodesTreeWidget

from core.nodes import NODE_REGISTRY


# ---------- Node class definitions ----------
# OdenGraphQt requires real class definitions (not dynamically generated)
# Each class has __identifier__ and NODE_NAME that determine the type string

class DataSourceNode(BaseNode):
    __identifier__ = "dataforge"
    NODE_NAME = "数据源"
    def __init__(self):
        super().__init__()
        self.add_output("输出")
        self.add_text_input("path", "数据集路径", text="", placeholder_text="选择数据集目录...")

class QualityCheckNode(BaseNode):
    __identifier__ = "dataforge"
    NODE_NAME = "质量检查"
    def __init__(self):
        super().__init__()
        self.add_input("输入")
        self.add_output("输出")
        self.add_text_input("blur_threshold", "模糊阈值", text="100")
        self.add_checkbox("check_corrupt", "", text="检测损坏", state=True)
        self.add_checkbox("check_blank", "", text="检测空白", state=True)

class DedupNode(BaseNode):
    __identifier__ = "dataforge"
    NODE_NAME = "重复检测"
    def __init__(self):
        super().__init__()
        self.add_input("输入")
        self.add_output("输出")
        self.add_text_input("threshold", "相似阈值", text="5")

class AugmentNode(BaseNode):
    __identifier__ = "dataforge"
    NODE_NAME = "数据增强"
    def __init__(self):
        super().__init__()
        self.add_input("输入")
        self.add_output("输出")
        self.add_checkbox("flip_h", "", text="水平翻转", state=True)
        self.add_checkbox("flip_v", "", text="垂直翻转", state=False)
        self.add_checkbox("rotate90", "", text="随机旋转", state=True)
        self.add_checkbox("brightness", "", text="亮度抖动", state=True)
        self.add_text_input("n_per_image", "每张生成", text="3")

class SplitNode(BaseNode):
    __identifier__ = "dataforge"
    NODE_NAME = "数据集划分"
    def __init__(self):
        super().__init__()
        self.add_input("输入")
        self.add_output("输出")
        self.add_text_input("train", "训练集", text="0.8")
        self.add_text_input("val", "验证集", text="0.1")
        self.add_text_input("test", "测试集", text="0.1")
        self.add_checkbox("stratified", "", text="分层采样", state=True)

class ExportNode(BaseNode):
    __identifier__ = "dataforge"
    NODE_NAME = "导出"
    def __init__(self):
        super().__init__()
        self.add_input("输入")
        self.add_combo_menu("format", "导出格式",
                            items=["YOLO", "COCO", "Pascal VOC", "ImageFolder", "MVTec", "CSV", "JSON Lines"])
        self.add_text_input("out_dir", "输出目录", text="", placeholder_text="选择输出目录...")
        self.add_checkbox("copy_images", "", text="复制图片", state=True)


# Registry: node_id → class
ALL_NODE_CLASSES = [
    DataSourceNode, QualityCheckNode, DedupNode,
    AugmentNode, SplitNode, ExportNode,
]

# Map our node_id to OdenGraphQt type_ string
NODE_ID_TO_TYPE = {
    "data_source": "dataforge.DataSourceNode",
    "quality_check": "dataforge.QualityCheckNode",
    "dedup": "dataforge.DedupNode",
    "augment": "dataforge.AugmentNode",
    "split": "dataforge.SplitNode",
    "export": "dataforge.ExportNode",
}


def create_graph() -> NodeGraph:
    """Create a configured NodeGraph with all tool nodes registered."""
    graph = NodeGraph()

    # Register all node classes
    graph.register_nodes(ALL_NODE_CLASSES)

    # Match app theme colors
    from gui.theme import T
    def _hex_rgb(h: str) -> tuple:
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    graph.set_background_color(*_hex_rgb(T.CONTENT))
    graph.set_grid_color(*_hex_rgb(T.BORDER))

    return graph
