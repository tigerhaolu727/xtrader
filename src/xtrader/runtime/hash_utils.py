"""Canonical hash utilities shared by runtime and precompile."""

from __future__ import annotations

import json
import math
from hashlib import sha256
from typing import Any


def normalize_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): normalize_for_hash(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [normalize_for_hash(v) for v in value]
    if isinstance(value, tuple):
        return [normalize_for_hash(v) for v in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        rounded = round(float(value), 2)
        if float(rounded).is_integer():
            return int(rounded)
        return float(f"{rounded:.2f}")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(payload: Any) -> str:
    canonical = canonical_json(normalize_for_hash(payload))
    return sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["normalize_for_hash", "canonical_json", "sha256_hex"]
