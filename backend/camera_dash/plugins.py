"""Plugin loader — discovers nodes/sinks via ``importlib.metadata`` entry-points.

External packages register additional nodes by declaring entry-points under the
groups ``camera_dash.nodes`` and ``camera_dash.sinks``. Built-ins ship in this
repo's ``pyproject.toml`` so they're loaded the same way.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any

from .pipeline.node import Node

log = logging.getLogger(__name__)

ENTRY_POINT_GROUPS = ("camera_dash.nodes", "camera_dash.sinks")


def load_catalog() -> dict[str, type[Node]]:
    """Discover and load all registered node classes.

    Returns a dict mapping ``type_id`` (e.g. ``"detector.yolo"``) to the node class.
    Failures to import a single entry-point are logged and skipped rather than
    crashing the whole catalog.
    """
    catalog: dict[str, type[Node]] = {}
    for group in ENTRY_POINT_GROUPS:
        for ep in entry_points(group=group):
            try:
                cls = ep.load()
            except Exception:
                log.exception("failed to load plugin %s:%s", group, ep.name)
                continue
            if not isinstance(cls, type) or not issubclass(cls, Node):
                log.warning("plugin %s:%s did not resolve to a Node subclass", group, ep.name)
                continue
            if not cls.TYPE_ID:
                cls.TYPE_ID = ep.name  # default to entry-point name
            catalog[cls.TYPE_ID] = cls
    log.info("loaded %d nodes from entry-points: %s",
             len(catalog), ", ".join(sorted(catalog.keys())))
    return catalog


def describe_catalog(catalog: dict[str, type[Node]]) -> list[dict[str, Any]]:
    """Catalog → JSON-serializable list for the editor palette."""
    out: list[dict[str, Any]] = []
    for type_id, cls in sorted(catalog.items()):
        out.append({
            "type_id": type_id,
            "category": cls.UI_CATEGORY,
            "inputs": [{"name": p.name, "port_type": p.port_type.value, "required": p.required}
                       for p in cls.INPUTS],
            "outputs": [{"name": p.name, "port_type": p.port_type.value, "required": p.required}
                        for p in cls.OUTPUTS],
            "config_schema": cls.CONFIG_SCHEMA,
            "doc": (cls.__doc__ or "").strip(),
        })
    return out
