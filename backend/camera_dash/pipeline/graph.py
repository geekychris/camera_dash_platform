"""Pipeline graph: JSON ⇄ in-memory DAG, with validation against the node catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class GraphNode:
    id: str
    type: str            # e.g. "detector.yolo"
    config: dict[str, Any] = field(default_factory=dict)
    position: dict[str, float] | None = None  # x/y for the editor; ignored by engine


@dataclass(slots=True)
class GraphEdge:
    from_node: str
    from_port: str
    to_node: str
    to_port: str

    @classmethod
    def parse(cls, raw: dict[str, str]) -> GraphEdge:
        f_node, f_port = raw["from"].split(".", 1)
        t_node, t_port = raw["to"].split(".", 1)
        return cls(f_node, f_port, t_node, t_port)

    def as_dict(self) -> dict[str, str]:
        return {"from": f"{self.from_node}.{self.from_port}",
                "to": f"{self.to_node}.{self.to_port}"}


@dataclass(slots=True)
class Graph:
    id: str
    name: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    @classmethod
    def from_json(cls, raw: str | dict[str, Any], catalog: dict[str, Any] | None = None) -> Graph:
        data = json.loads(raw) if isinstance(raw, str) else raw
        nodes = [GraphNode(
            id=n["id"],
            type=n["type"],
            config=n.get("config", {}),
            position=n.get("position"),
        ) for n in data["nodes"]]
        edges = [GraphEdge.parse(e) for e in data["edges"]]
        g = cls(id=data["id"], name=data.get("name", data["id"]), nodes=nodes, edges=edges)
        if catalog is not None:
            g.validate(catalog)
        return g

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "nodes": [
                {"id": n.id, "type": n.type, "config": n.config, **({"position": n.position} if n.position else {})}
                for n in self.nodes
            ],
            "edges": [e.as_dict() for e in self.edges],
        }

    def validate(self, catalog: dict[str, Any]) -> None:
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise GraphError("duplicate node ids")
        for n in self.nodes:
            if n.type not in catalog:
                raise GraphError(f"unknown node type: {n.type}")
        for e in self.edges:
            if e.from_node not in ids:
                raise GraphError(f"edge references unknown node {e.from_node}")
            if e.to_node not in ids:
                raise GraphError(f"edge references unknown node {e.to_node}")
            src = next(n for n in self.nodes if n.id == e.from_node)
            dst = next(n for n in self.nodes if n.id == e.to_node)
            src_outs = {p.name: p for p in catalog[src.type].OUTPUTS}
            dst_ins = {p.name: p for p in catalog[dst.type].INPUTS}
            if e.from_port not in src_outs:
                raise GraphError(f"{src.type} has no output port '{e.from_port}'")
            if e.to_port not in dst_ins:
                raise GraphError(f"{dst.type} has no input port '{e.to_port}'")
            if not _port_compatible(src_outs[e.from_port].port_type, dst_ins[e.to_port].port_type):
                raise GraphError(
                    f"type mismatch on edge {e.from_node}.{e.from_port} -> {e.to_node}.{e.to_port}: "
                    f"{src_outs[e.from_port].port_type.value} vs {dst_ins[e.to_port].port_type.value}"
                )
        # Cycle check
        if self._has_cycle():
            raise GraphError("graph contains a cycle")

    def _has_cycle(self) -> bool:
        adj: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for e in self.edges:
            adj[e.from_node].append(e.to_node)
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in adj}

        def dfs(u: str) -> bool:
            color[u] = GRAY
            for v in adj[u]:
                if color[v] == GRAY:
                    return True
                if color[v] == WHITE and dfs(v):
                    return True
            color[u] = BLACK
            return False

        return any(color[u] == WHITE and dfs(u) for u in adj)


class GraphError(ValueError):
    """Raised on invalid pipeline graph definitions."""


def _port_compatible(src: Any, dst: Any) -> bool:
    """Edge type compatibility. Exact match always works; sinks with EVENT input
    also accept DETECTIONS so condition nodes can route detection sets to MQTT/Kafka.
    """
    if src == dst:
        return True
    from .types import PortType  # local to avoid import cycle
    return bool(dst == PortType.EVENT and src in (PortType.DETECTIONS, PortType.TRIGGER))
