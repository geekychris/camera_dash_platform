"""Loader for built-in pipeline examples (examples/pipelines/*.json + .meta.json).

Walks the repo's ``examples/pipelines/`` directory and pairs each pipeline JSON
with its optional ``.meta.json`` sidecar. Examples are read-only "factory
presets" — installing one creates a real, mutable pipeline in the DB.

Resolution order for the examples directory:
  1. $CAMERA_DASH_EXAMPLES_DIR if set
  2. <config_path>/../examples/pipelines (relative to deploy YAML)
  3. <repo_root>/examples/pipelines (walk up from this file)
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_RE_PLACEHOLDER = re.compile(r"REPLACE_ME")


def _candidates(settings: Any) -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("CAMERA_DASH_EXAMPLES_DIR")
    if env:
        out.append(Path(env))
    cfg = getattr(settings, "config_path", None)
    if cfg:
        out.append(Path(cfg).parent.parent / "examples" / "pipelines")
    # Walk up from this file to find a sibling examples/ dir
    here = Path(__file__).resolve()
    for p in here.parents:
        cand = p / "examples" / "pipelines"
        if cand.is_dir():
            out.append(cand)
            break
    return out


def find_examples_dir(settings: Any) -> Path | None:
    for c in _candidates(settings):
        if c.is_dir():
            return c
    return None


def load_examples(settings: Any) -> list[dict[str, Any]]:
    """Return a list of example dicts: ``{id, name, description, use_case, tags,
    complexity, requires_env, placeholders, definition}``."""
    d = find_examples_dir(settings)
    if d is None:
        log.warning("no examples directory found")
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(d.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        try:
            defn = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            log.warning("skipping %s: invalid JSON (%s)", path.name, exc)
            continue
        meta_path = path.with_suffix("").with_suffix(".meta.json")
        meta: dict[str, Any] = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                log.warning("invalid meta sidecar %s; ignoring", meta_path.name)
        entry = {
            "id": defn.get("id") or path.stem,
            "name": meta.get("name") or defn.get("name") or path.stem,
            "description": meta.get("description", ""),
            "use_case": meta.get("use_case", ""),
            "tags": meta.get("tags") or [],
            "complexity": meta.get("complexity", "medium"),
            "requires_env": meta.get("requires_env") or [],
            "requires_camera_kinds": meta.get("requires_camera_kinds") or [],
            "placeholders": meta.get("placeholders") or _detect_placeholders(defn),
            "definition": defn,
        }
        out.append(entry)
    log.info("loaded %d pipeline examples from %s", len(out), d)
    return out


def _detect_placeholders(defn: dict[str, Any]) -> list[str]:
    """Find any REPLACE_ME literals (or similar) in the definition's camera_ids."""
    found: set[str] = set()
    for node in defn.get("nodes", []):
        cid = (node.get("config") or {}).get("camera_id")
        if isinstance(cid, str) and _RE_PLACEHOLDER.search(cid):
            found.add(cid)
    return sorted(found)


def substitute_placeholders(definition: dict[str, Any],
                             mapping: dict[str, str]) -> dict[str, Any]:
    """Return a deep copy of ``definition`` with each placeholder camera_id
    replaced via ``mapping``. Unmapped placeholders are left untouched."""
    out = json.loads(json.dumps(definition))
    for node in out.get("nodes", []):
        cfg = node.get("config") or {}
        cid = cfg.get("camera_id")
        if isinstance(cid, str) and cid in mapping:
            cfg["camera_id"] = mapping[cid]
    return out
