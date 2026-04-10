"""Node editor integration using OdenGraphQt library.

Wraps OdenGraphQt's NodeGraph as the canvas, defines custom node
classes for each tool (data source, processing, output).

OdenGraphQt provides: zoom/pan, port connections, properties panel,
node search, undo/redo — all out of the box.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_API", "pyqt6")

from OdenGraphQt import BaseNode, NodeGraph

from core.nodes import NODE_REGISTRY, NodeSpec


# ---------- Custom Node Classes ----------

def _make_node_class(spec: NodeSpec) -> type:
    """Dynamically create an OdenGraphQt BaseNode subclass from a NodeSpec."""

    # Build unique class name
    cls_name = f"Node_{spec.node_id}"

    def __init__(self):
        BaseNode.__init__(self)
        # Add input ports
        for port in spec.inputs:
            self.add_input(port.name)
        # Add output ports
        for port in spec.outputs:
            self.add_output(port.name)
        # Add properties (shown in properties panel)
        for param in spec.parameters:
            if param.param_type == "bool":
                self.add_checkbox(param.name, label=param.label, state=bool(param.default))
            elif param.param_type == "choice":
                items = list(param.choices) if param.choices else []
                self.add_combo_menu(param.name, label=param.label, items=items)
            elif param.param_type in ("int", "float"):
                self.add_text_input(param.name, label=param.label, text=str(param.default))
            elif param.param_type == "path":
                self.add_text_input(param.name, label=param.label, text=str(param.default) if param.default else "")
            else:
                self.add_text_input(param.name, label=param.label, text=str(param.default) if param.default else "")

    # Category label for the node palette
    cat_labels = {"input": "输入", "processing": "处理", "output": "输出"}
    category_label = cat_labels.get(spec.category, "其他")

    # Create class dynamically
    node_cls = type(cls_name, (BaseNode,), {
        "__init__": __init__,
        "__identifier__": "dataforge",
        "NODE_NAME": spec.label,
    })

    return node_cls


# ---------- Build & Register ----------

NODE_CLASSES: dict[str, type] = {}

for _nid, _spec in NODE_REGISTRY.items():
    _cls = _make_node_class(_spec)
    NODE_CLASSES[_nid] = _cls


def create_graph() -> NodeGraph:
    """Create a configured NodeGraph with all tool nodes registered."""
    graph = NodeGraph()

    # Register all node classes
    for cls in NODE_CLASSES.values():
        graph.register_node(cls)

    # Style the graph
    viewer = graph.viewer()
    viewer.setStyleSheet("")  # Clear any default styles, let app QSS handle it

    return graph
