"""Schema asset helpers for strategy profile v0.3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def schema_root_dir() -> Path:
    return Path(__file__).resolve().parent / "schemas"


def load_schema_file(filename: str) -> dict[str, Any]:
    path = schema_root_dir() / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"schema file must be an object: {path}")
    return payload


__all__ = ["load_schema_file", "schema_root_dir"]
