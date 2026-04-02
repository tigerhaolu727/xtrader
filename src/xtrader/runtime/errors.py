"""Runtime contract errors for XTR-019."""

from __future__ import annotations

from typing import Any


class RuntimeContractError(ValueError):
    """Structured runtime error carrying code/stage/path metadata."""

    def __init__(
        self,
        *,
        code: str,
        stage: str,
        path: str,
        message: str,
        severity: str = "ERROR",
        timeframe: str | None = None,
        instance_id: str | None = None,
        feature_ref: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        self.code = str(code)
        self.stage = str(stage)
        self.path = str(path)
        self.message = str(message)
        self.severity = str(severity)
        self.timeframe = str(timeframe) if timeframe is not None else None
        self.instance_id = str(instance_id) if instance_id is not None else None
        self.feature_ref = str(feature_ref) if feature_ref is not None else None
        self.suggestion = str(suggestion) if suggestion is not None else None
        super().__init__(f"{self.code}::{self.stage}::{self.path}::{self.message}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
            "timeframe": self.timeframe,
            "instance_id": self.instance_id,
            "feature_ref": self.feature_ref,
            "suggestion": self.suggestion,
        }


__all__ = ["RuntimeContractError"]
