"""Position side enum models."""

from __future__ import annotations

from enum import Enum


class PositionSide(str, Enum):
    """Direction of a derivatives position."""

    LONG = "long"
    SHORT = "short"
    NET = "net"  # for exchanges that only expose aggregated positions


__all__ = ["PositionSide"]
