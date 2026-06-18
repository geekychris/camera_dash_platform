"""Pipeline templates — backwards-compatibility shim that forwards to /api/examples.

The 4 hardcoded templates have been superseded by the file-based ``examples/pipelines/``
library. This module now just re-serves them so existing clients (older frontend cache,
etc.) keep working.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..examples_loader import load_examples

router = APIRouter()


@router.get("")
async def list_templates(request: Request) -> list[dict[str, Any]]:
    return load_examples(request.app.state.settings)
