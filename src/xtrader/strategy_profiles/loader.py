"""Strategy profile v0.3 loading and schema validation."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from xtrader.strategy_profiles.errors import StrategyProfileContractError
from xtrader.strategy_profiles.models import StrategyProfileV03


@dataclass(frozen=True, slots=True)
class LoadedStrategyProfile:
    raw: dict[str, Any]
    resolved: dict[str, Any]


class StrategyProfileLoader:
    """Load and validate strategy profile payload."""

    def load(self, config: dict[str, Any] | str | Path) -> LoadedStrategyProfile:
        raw_payload = self._read_payload(config)
        raw = copy.deepcopy(raw_payload)
        try:
            parsed = StrategyProfileV03.model_validate(raw_payload)
        except ValidationError as exc:
            raise self._to_contract_error(exc) from exc
        resolved = parsed.model_dump(mode="python")
        return LoadedStrategyProfile(raw=raw, resolved=resolved)

    def _read_payload(self, config: dict[str, Any] | str | Path) -> dict[str, Any]:
        if isinstance(config, dict):
            return config
        if isinstance(config, (str, Path)):
            path = Path(config)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise StrategyProfileContractError(
                    code="PC-CFG-003",
                    stage="profile_schema",
                    path="$.config_path",
                    message=f"profile file not found: {path}",
                ) from exc
            except json.JSONDecodeError as exc:
                raise StrategyProfileContractError(
                    code="PC-CFG-003",
                    stage="profile_schema",
                    path="$.config",
                    message=f"profile is not valid JSON: {exc.msg}",
                ) from exc
            if not isinstance(payload, dict):
                raise StrategyProfileContractError(
                    code="PC-CFG-003",
                    stage="profile_schema",
                    path="$.config",
                    message="profile root must be an object",
                )
            return payload
        raise StrategyProfileContractError(
            code="PC-CFG-003",
            stage="profile_schema",
            path="$.config",
            message="profile must be dict or JSON file path",
        )

    def _to_contract_error(self, exc: ValidationError) -> StrategyProfileContractError:
        first = exc.errors(include_url=False)[0]
        path = self._format_loc(first.get("loc") or ())
        message = str(first.get("msg") or "profile schema validation failed")
        return StrategyProfileContractError(
            code="PC-CFG-003",
            stage="profile_schema",
            path=path,
            message=message,
        )

    def _format_loc(self, loc: tuple[Any, ...] | list[Any]) -> str:
        if not loc:
            return "$."
        parts: list[str] = ["$"]
        for item in loc:
            if isinstance(item, int):
                parts.append(f"[{item}]")
            else:
                text = str(item)
                if text:
                    parts.append(f".{text}")
        return "".join(parts)


__all__ = ["LoadedStrategyProfile", "StrategyProfileLoader"]
