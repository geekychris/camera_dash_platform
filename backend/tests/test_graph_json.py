from __future__ import annotations

import pytest

from camera_dash.pipeline.graph import Graph, GraphError
from camera_dash.pipeline.nodes.conditions.metadata_match import MetadataMatchNode
from camera_dash.pipeline.nodes.sources import CameraSourceNode
from camera_dash.pipeline.nodes.transforms.crop import CropNode

CATALOG = {
    "source.camera": CameraSourceNode,
    "transform.crop": CropNode,
    "condition.metadata_match": MetadataMatchNode,
}


def _basic_graph(extra: dict | None = None) -> dict:
    g = {
        "id": "p1",
        "name": "test",
        "nodes": [
            {"id": "s", "type": "source.camera", "config": {"camera_id": "c1"}},
            {"id": "c", "type": "transform.crop",
             "config": {"x": 0, "y": 0, "width": 100, "height": 100}},
        ],
        "edges": [{"from": "s.frame", "to": "c.frame"}],
    }
    if extra:
        g.update(extra)
    return g


def test_roundtrip():
    g = Graph.from_json(_basic_graph(), catalog=CATALOG)
    assert g.id == "p1"
    assert len(g.nodes) == 2
    assert g.to_json()["edges"] == [{"from": "s.frame", "to": "c.frame"}]


def test_unknown_node_type_rejected():
    raw = _basic_graph()
    raw["nodes"].append({"id": "bogus", "type": "does.not.exist", "config": {}})
    raw["edges"].append({"from": "c.frame", "to": "bogus.frame"})
    with pytest.raises(GraphError, match="unknown node type"):
        Graph.from_json(raw, catalog=CATALOG)


def test_port_type_mismatch():
    raw = {
        "id": "p", "name": "p",
        "nodes": [
            {"id": "s", "type": "source.camera", "config": {"camera_id": "c"}},
            {"id": "m", "type": "condition.metadata_match",
             "config": {"expression": "d.score > 0"}},
        ],
        "edges": [{"from": "s.frame", "to": "m.detections"}],  # frame -> detections mismatch
    }
    with pytest.raises(GraphError, match="type mismatch"):
        Graph.from_json(raw, catalog=CATALOG)


def test_cycle_detected():
    raw = {
        "id": "p", "name": "p",
        "nodes": [
            {"id": "a", "type": "transform.crop",
             "config": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"id": "b", "type": "transform.crop",
             "config": {"x": 0, "y": 0, "width": 1, "height": 1}},
        ],
        "edges": [
            {"from": "a.frame", "to": "b.frame"},
            {"from": "b.frame", "to": "a.frame"},
        ],
    }
    with pytest.raises(GraphError, match="cycle"):
        Graph.from_json(raw, catalog=CATALOG)
