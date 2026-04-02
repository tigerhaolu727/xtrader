"""Strategy profile contract errors."""

from __future__ import annotations

from typing import Any


class StrategyProfileContractError(ValueError):
    """Structured profile error carrying code/stage/path metadata."""

    def __init__(
        self,
        *,
        code: str,
        stage: str,
        path: str,
        message: str,
        severity: str = "ERROR",
    ) -> None:
        self.code = str(code)
        self.stage = str(stage)
        self.path = str(path)
        self.message = str(message)
        self.severity = str(severity)
        super().__init__(f"{self.code}::{self.stage}::{self.path}::{self.message}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }


__all__ = ["StrategyProfileContractError"]
