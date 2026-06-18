"""Branch on detection metadata.

The ``expression`` is a Python expression evaluated against ``d`` (the detection)
and ``dets`` (the full set). Examples::

    d.label == "person" and d.score > 0.7
    any(x.label == "dog" for x in dets)
    d.attrs.get("area", 0) > 1000

If any detection matches (or the set-level expression is True), the input flows
out the ``match`` port; otherwise out ``no_match``. Both ports are typed
DETECTIONS so they can drive recorders or downstream filters.

Security: the expression runs in a restricted namespace (no builtins, no globals).
Only use trusted pipeline definitions.
"""

from __future__ import annotations

import ast
from typing import Any

from ....pipeline.types import DetectionSet, PortType
from ...node import Node, Port

_ALLOWED_NODES = {
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Compare,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.IfExp, ast.Constant, ast.Name, ast.Load, ast.Attribute, ast.Subscript,
    ast.Index, ast.Slice, ast.Tuple, ast.List, ast.Set, ast.Dict,
    ast.Call, ast.GeneratorExp, ast.ListComp, ast.SetComp,
    ast.comprehension, ast.Starred,
}


def _validate(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            raise ValueError(f"disallowed expression node: {type(node).__name__}")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id not in {"any", "all", "len", "min", "max", "sum", "abs"}):
            raise ValueError(f"disallowed call: {node.func.id}")


class MetadataMatchNode(Node):
    TYPE_ID = "condition.metadata_match"
    UI_CATEGORY = "condition"
    INPUTS = (Port("detections", PortType.DETECTIONS),)
    OUTPUTS = (
        Port("match", PortType.DETECTIONS, required=False),
        Port("no_match", PortType.DETECTIONS, required=False),
    )
    CONFIG_SCHEMA = {
        "type": "object",
        "required": ["expression"],
        "properties": {
            "expression": {"type": "string",
                           "description": "Python boolean expr over `d` and `dets`",
                           "examples": ['d.label == "person" and d.score > 0.7']},
            "any": {"type": "boolean", "default": True,
                    "description": "If true, route through `match` when ANY detection matches"},
        },
    }

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._compiled: Any = None

    async def setup(self) -> None:
        src = self.config["expression"]
        tree = ast.parse(src, mode="eval")
        _validate(tree)
        self._compiled = compile(tree, filename="<metadata_match>", mode="eval")

    async def process(self, **inputs: Any) -> dict[str, Any]:
        dets: DetectionSet | None = inputs.get("detections")
        if dets is None:
            return {}
        scope = {"__builtins__": {}, "any": any, "all": all, "len": len,
                 "min": min, "max": max, "sum": sum, "abs": abs}
        if self.config.get("any", True):
            matched = any(eval(self._compiled, scope, {"d": d, "dets": dets.detections})
                          for d in dets.detections)
        else:
            matched = eval(self._compiled, scope, {"d": None, "dets": dets.detections})
        if matched and self.context.event_bus is not None:
            from ....pipeline.types import Event
            self.context.event_bus.publish_nowait(Event(
                pipeline_id=self.context.pipeline_id, node_id=self.node_id,
                camera_id=dets.camera_id, timestamp_ns=dets.timestamp_ns,
                kind="metadata_match",
                payload={"expression": self.config["expression"],
                         "labels": list({d.label for d in dets.detections}),
                         "count": len(dets.detections)},
            ))
        return {"match": dets} if matched else {"no_match": dets}
