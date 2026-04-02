"""Error helpers for XTR-018 feature-engine contracts."""

from __future__ import annotations


def xtr018_error(code: str, detail: str) -> ValueError:
    return ValueError(f"XTR018::{code}::{detail}")


__all__ = ["xtr018_error"]
