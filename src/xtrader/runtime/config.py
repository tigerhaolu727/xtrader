"""Runtime v1 config loading and validation."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xtrader.runtime.errors import RuntimeContractError

_SCHEMA_VERSION = "xtr_runtime_v1"
_TOP_LEVEL_REQUIRED: tuple[str, ...] = (
    "schema_version",
    "strategy_id",
    "execution_timeframe",
    "timeframes",
    "indicator_plan_by_tf",
    "signal_rules",
    "risk_rules",
)
_TOP_LEVEL_ALLOWED: tuple[str, ...] = (
    "schema_version",
    "strategy_id",
    "execution_timeframe",
    "timeframes",
    "indicator_plan_by_tf",
    "signal_rules",
    "risk_rules",
    "scoring_rules",
    "fusion_rules",
    "trial_config",
    "warn_policy",
    "metadata",
)
_PLAN_ITEM_REQUIRED: tuple[str, ...] = ("instance_id", "family", "params")
_PLAN_ITEM_ALLOWED: tuple[str, ...] = ("instance_id", "family", "params")
_WARN_POLICY_ALLOWED: tuple[str, ...] = ("record_only", "error")


@dataclass(frozen=True, slots=True)
class LoadedRuntimeConfig:
    raw: dict[str, Any]
    resolved: dict[str, Any]


class ConfigLoader:
    """Load and validate runtime configuration for v1."""

    def load(self, config: dict[str, Any] | str | Path) -> LoadedRuntimeConfig:
        raw_payload = self._read_payload(config)
        raw = copy.deepcopy(raw_payload)
        resolved = copy.deepcopy(raw_payload)

        self._validate_top_level(resolved)
        self._apply_defaults(resolved)
        self._validate_types_and_consistency(resolved)
        self._validate_indicator_plan(resolved)
        self._validate_risk_rules(resolved)
        self._validate_trial_config(resolved)

        return LoadedRuntimeConfig(raw=raw, resolved=resolved)

    def resolve_trials(self, config: LoadedRuntimeConfig | dict[str, Any] | str | Path) -> list[dict[str, Any]]:
        """Build a stable trial list from runtime config."""
        loaded = config if isinstance(config, LoadedRuntimeConfig) else self.load(config)
        trial_config = loaded.resolved.get("trial_config", {"mode": "single"})
        mode = str(trial_config.get("mode", "single"))
        if mode == "single":
            return [
                {
                    "trial_id": "baseline",
                    "changes": [],
                    "resolved_config": copy.deepcopy(loaded.resolved),
                }
            ]
        scenarios = trial_config.get("scenarios")
        if not isinstance(scenarios, list):
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.trial_config.scenarios",
                message="trial_config.scenarios must be an array when mode=scenarios",
            )
        return self._resolve_scenario_trials(loaded.resolved, scenarios)

    def _read_payload(self, config: dict[str, Any] | str | Path) -> dict[str, Any]:
        if isinstance(config, dict):
            return config
        if isinstance(config, (str, Path)):
            path = Path(config)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise RuntimeContractError(
                    code="PC-CFG-001",
                    stage="config",
                    path="$.config_path",
                    message=f"config file not found: {path}",
                ) from exc
            except json.JSONDecodeError as exc:
                raise RuntimeContractError(
                    code="PC-CFG-003",
                    stage="config",
                    path="$.config",
                    message=f"config is not valid JSON: {exc.msg}",
                ) from exc
            if not isinstance(payload, dict):
                raise RuntimeContractError(
                    code="PC-CFG-003",
                    stage="config",
                    path="$.config",
                    message="config root must be an object",
                )
            return payload
        raise RuntimeContractError(
            code="PC-CFG-003",
            stage="config",
            path="$.config",
            message="config must be dict or JSON file path",
        )

    def _validate_top_level(self, payload: dict[str, Any]) -> None:
        missing = sorted(set(_TOP_LEVEL_REQUIRED).difference(payload))
        if missing:
            raise RuntimeContractError(
                code="PC-CFG-001",
                stage="config",
                path="$.",
                message=f"missing required top-level fields: {','.join(missing)}",
            )
        unknown = sorted(set(payload).difference(_TOP_LEVEL_ALLOWED))
        if unknown:
            raise RuntimeContractError(
                code="PC-CFG-002",
                stage="config",
                path="$.",
                message=f"unknown top-level fields: {','.join(unknown)}",
            )

    def _apply_defaults(self, payload: dict[str, Any]) -> None:
        if "warn_policy" not in payload:
            payload["warn_policy"] = "record_only"
        if "trial_config" not in payload:
            payload["trial_config"] = {"mode": "single"}

    def _validate_types_and_consistency(self, payload: dict[str, Any]) -> None:
        schema_version = payload.get("schema_version")
        if schema_version != _SCHEMA_VERSION:
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.schema_version",
                message=f"unsupported schema_version: {schema_version}",
            )
        strategy_id = payload.get("strategy_id")
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.strategy_id",
                message="strategy_id must be non-empty string",
            )
        execution_tf = payload.get("execution_timeframe")
        if not isinstance(execution_tf, str) or not execution_tf.strip():
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.execution_timeframe",
                message="execution_timeframe must be non-empty string",
            )
        timeframes = payload.get("timeframes")
        if not isinstance(timeframes, list) or not timeframes:
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.timeframes",
                message="timeframes must be non-empty array",
            )
        normalized_timeframes: list[str] = []
        for idx, value in enumerate(timeframes):
            if not isinstance(value, str) or not value.strip():
                raise RuntimeContractError(
                    code="PC-CFG-003",
                    stage="config",
                    path=f"$.timeframes[{idx}]",
                    message="timeframe must be non-empty string",
                )
            item = value.strip()
            if item not in normalized_timeframes:
                normalized_timeframes.append(item)
        payload["timeframes"] = normalized_timeframes
        if execution_tf not in normalized_timeframes:
            raise RuntimeContractError(
                code="PC-TFM-001",
                stage="config",
                path="$.execution_timeframe",
                message="execution_timeframe must be one of timeframes",
            )
        indicator_plan_by_tf = payload.get("indicator_plan_by_tf")
        if not isinstance(indicator_plan_by_tf, dict):
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.indicator_plan_by_tf",
                message="indicator_plan_by_tf must be an object",
            )
        unknown_tf = sorted(set(indicator_plan_by_tf).difference(normalized_timeframes))
        if unknown_tf:
            raise RuntimeContractError(
                code="PC-TFM-002",
                stage="config",
                path="$.indicator_plan_by_tf",
                message=f"indicator_plan_by_tf contains unknown timeframes: {','.join(unknown_tf)}",
            )
        if not isinstance(payload.get("signal_rules"), dict):
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.signal_rules",
                message="signal_rules must be an object",
            )
        for optional in ("scoring_rules", "fusion_rules", "metadata"):
            if optional in payload and payload[optional] is not None and not isinstance(payload[optional], dict):
                raise RuntimeContractError(
                    code="PC-CFG-003",
                    stage="config",
                    path=f"$.{optional}",
                    message=f"{optional} must be an object when provided",
                )
        warn_policy = payload.get("warn_policy")
        if not isinstance(warn_policy, str) or warn_policy not in _WARN_POLICY_ALLOWED:
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.warn_policy",
                message=f"warn_policy must be one of: {','.join(_WARN_POLICY_ALLOWED)}",
            )

    def _validate_indicator_plan(self, payload: dict[str, Any]) -> None:
        indicator_plan_by_tf = payload["indicator_plan_by_tf"]
        for timeframe, plan in indicator_plan_by_tf.items():
            if not isinstance(plan, list):
                raise RuntimeContractError(
                    code="PC-CFG-003",
                    stage="config",
                    path=f"$.indicator_plan_by_tf.{timeframe}",
                    message="indicator plan must be an array",
                )
            for idx, item in enumerate(plan):
                if not isinstance(item, dict):
                    raise RuntimeContractError(
                        code="PC-CFG-003",
                        stage="config",
                        path=f"$.indicator_plan_by_tf.{timeframe}[{idx}]",
                        message="indicator plan item must be an object",
                    )
                missing = sorted(set(_PLAN_ITEM_REQUIRED).difference(item))
                if missing:
                    raise RuntimeContractError(
                        code="PC-CFG-001",
                        stage="config",
                        path=f"$.indicator_plan_by_tf.{timeframe}[{idx}]",
                        message=f"missing required fields: {','.join(missing)}",
                    )
                unknown = sorted(set(item).difference(_PLAN_ITEM_ALLOWED))
                if unknown:
                    raise RuntimeContractError(
                        code="PC-CFG-002",
                        stage="config",
                        path=f"$.indicator_plan_by_tf.{timeframe}[{idx}]",
                        message=f"unknown fields: {','.join(unknown)}",
                    )
                instance_id = item.get("instance_id")
                family = item.get("family")
                params = item.get("params")
                if not isinstance(instance_id, str) or not instance_id.strip():
                    raise RuntimeContractError(
                        code="PC-CFG-003",
                        stage="config",
                        path=f"$.indicator_plan_by_tf.{timeframe}[{idx}].instance_id",
                        message="instance_id must be non-empty string",
                    )
                if not isinstance(family, str) or not family.strip():
                    raise RuntimeContractError(
                        code="PC-CFG-003",
                        stage="config",
                        path=f"$.indicator_plan_by_tf.{timeframe}[{idx}].family",
                        message="family must be non-empty string",
                    )
                if not isinstance(params, dict):
                    raise RuntimeContractError(
                        code="PC-CFG-003",
                        stage="config",
                        path=f"$.indicator_plan_by_tf.{timeframe}[{idx}].params",
                        message="params must be an object",
                    )

    def _validate_risk_rules(self, payload: dict[str, Any]) -> None:
        risk_rules = payload.get("risk_rules")
        if not isinstance(risk_rules, dict):
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.risk_rules",
                message="risk_rules must be an object",
            )
        required = {"position_size", "stop_loss", "take_profit"}
        missing = sorted(required.difference(risk_rules))
        if missing:
            raise RuntimeContractError(
                code="PC-CFG-001",
                stage="config",
                path="$.risk_rules",
                message=f"missing required fields: {','.join(missing)}",
            )
        unknown = sorted(set(risk_rules).difference(required))
        if unknown:
            raise RuntimeContractError(
                code="PC-CFG-002",
                stage="config",
                path="$.risk_rules",
                message=f"unknown fields: {','.join(unknown)}",
            )

        self._validate_position_size(risk_rules["position_size"])
        self._validate_stop_loss(risk_rules["stop_loss"])
        self._validate_take_profit(risk_rules["take_profit"])

    def _validate_position_size(self, payload: Any) -> None:
        path = "$.risk_rules.position_size"
        if not isinstance(payload, dict):
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=path, message="must be an object")
        allowed = {"mode", "value"}
        missing = sorted({"mode", "value"}.difference(payload))
        if missing:
            raise RuntimeContractError(code="PC-CFG-001", stage="config", path=path, message=f"missing required fields: {','.join(missing)}")
        unknown = sorted(set(payload).difference(allowed))
        if unknown:
            raise RuntimeContractError(code="PC-CFG-002", stage="config", path=path, message=f"unknown fields: {','.join(unknown)}")
        if payload.get("mode") != "fixed_fraction":
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=f"{path}.mode", message="mode must be fixed_fraction")
        value = payload.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=f"{path}.value", message="value must be numeric")
        value_f = float(value)
        if value_f <= 0.0 or value_f > 1.0:
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=f"{path}.value", message="value must be in (0,1]")

    def _validate_stop_loss(self, payload: Any) -> None:
        path = "$.risk_rules.stop_loss"
        if not isinstance(payload, dict):
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=path, message="must be an object")
        allowed = {"mode", "n", "k"}
        missing = sorted({"mode", "n", "k"}.difference(payload))
        if missing:
            raise RuntimeContractError(code="PC-CFG-001", stage="config", path=path, message=f"missing required fields: {','.join(missing)}")
        unknown = sorted(set(payload).difference(allowed))
        if unknown:
            raise RuntimeContractError(code="PC-CFG-002", stage="config", path=path, message=f"unknown fields: {','.join(unknown)}")
        if payload.get("mode") != "atr_multiple":
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=f"{path}.mode", message="mode must be atr_multiple")
        n = payload.get("n")
        k = payload.get("k")
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=f"{path}.n", message="n must be integer >= 1")
        if not isinstance(k, (int, float)) or isinstance(k, bool) or float(k) <= 0.0:
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=f"{path}.k", message="k must be numeric > 0")

    def _validate_take_profit(self, payload: Any) -> None:
        path = "$.risk_rules.take_profit"
        if not isinstance(payload, dict):
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=path, message="must be an object")
        allowed = {"mode", "rr"}
        missing = sorted({"mode", "rr"}.difference(payload))
        if missing:
            raise RuntimeContractError(code="PC-CFG-001", stage="config", path=path, message=f"missing required fields: {','.join(missing)}")
        unknown = sorted(set(payload).difference(allowed))
        if unknown:
            raise RuntimeContractError(code="PC-CFG-002", stage="config", path=path, message=f"unknown fields: {','.join(unknown)}")
        if payload.get("mode") != "rr_multiple":
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=f"{path}.mode", message="mode must be rr_multiple")
        rr = payload.get("rr")
        if not isinstance(rr, (int, float)) or isinstance(rr, bool) or float(rr) <= 0.0:
            raise RuntimeContractError(code="PC-CFG-003", stage="config", path=f"{path}.rr", message="rr must be numeric > 0")

    def _validate_trial_config(self, payload: dict[str, Any]) -> None:
        trial_config = payload.get("trial_config")
        if not isinstance(trial_config, dict):
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.trial_config",
                message="trial_config must be an object",
            )
        mode = trial_config.get("mode", "single")
        if not isinstance(mode, str) or not mode.strip():
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.trial_config.mode",
                message="trial_config.mode must be non-empty string",
            )
        if mode == "single":
            unknown = sorted(set(trial_config).difference({"mode"}))
            if unknown:
                raise RuntimeContractError(
                    code="PC-CFG-002",
                    stage="config",
                    path="$.trial_config",
                    message=f"unknown fields: {','.join(unknown)}",
                )
            payload["trial_config"] = {"mode": "single"}
            return
        if mode != "scenarios":
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.trial_config.mode",
                message="trial_config.mode must be one of: single,scenarios",
            )

        unknown = sorted(set(trial_config).difference({"mode", "scenarios"}))
        if unknown:
            raise RuntimeContractError(
                code="PC-CFG-002",
                stage="config",
                path="$.trial_config",
                message=f"unknown fields: {','.join(unknown)}",
            )
        scenarios = trial_config.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.trial_config.scenarios",
                message="trial_config.scenarios must be non-empty array when mode=scenarios",
            )

        instance_index: dict[str, set[str]] = {}
        for timeframe, items in payload.get("indicator_plan_by_tf", {}).items():
            current: set[str] = set()
            for item in items:
                current.add(str(item["instance_id"]).strip())
            instance_index[str(timeframe)] = current

        seen_trial_ids: set[str] = set()
        normalized_scenarios: list[dict[str, Any]] = []
        for sidx, scenario in enumerate(scenarios):
            scenario_path = f"$.trial_config.scenarios[{sidx}]"
            if not isinstance(scenario, dict):
                raise RuntimeContractError(
                    code="PC-CFG-003",
                    stage="config",
                    path=scenario_path,
                    message="scenario must be an object",
                )
            missing = sorted({"trial_id", "changes"}.difference(scenario))
            if missing:
                raise RuntimeContractError(
                    code="PC-CFG-001",
                    stage="config",
                    path=scenario_path,
                    message=f"missing required fields: {','.join(missing)}",
                )
            unknown_scenario = sorted(set(scenario).difference({"trial_id", "changes"}))
            if unknown_scenario:
                raise RuntimeContractError(
                    code="PC-CFG-002",
                    stage="config",
                    path=scenario_path,
                    message=f"unknown fields: {','.join(unknown_scenario)}",
                )

            trial_id = scenario.get("trial_id")
            if not isinstance(trial_id, str) or not trial_id.strip():
                raise RuntimeContractError(
                    code="PC-CFG-003",
                    stage="config",
                    path=f"{scenario_path}.trial_id",
                    message="trial_id must be non-empty string",
                )
            trial_id = trial_id.strip()
            if trial_id in seen_trial_ids:
                raise RuntimeContractError(
                    code="PC-TRI-002",
                    stage="config",
                    path=f"{scenario_path}.trial_id",
                    message=f"duplicate trial_id: {trial_id}",
                )
            seen_trial_ids.add(trial_id)

            changes = scenario.get("changes")
            if not isinstance(changes, list):
                raise RuntimeContractError(
                    code="PC-CFG-003",
                    stage="config",
                    path=f"{scenario_path}.changes",
                    message="changes must be an array",
                )
            normalized_changes: list[dict[str, Any]] = []
            seen_targets: set[tuple[str, str]] = set()
            for cidx, change in enumerate(changes):
                change_path = f"{scenario_path}.changes[{cidx}]"
                if not isinstance(change, dict):
                    raise RuntimeContractError(
                        code="PC-CFG-003",
                        stage="config",
                        path=change_path,
                        message="change must be an object",
                    )
                if "risk_rules" in change:
                    raise RuntimeContractError(
                        code="PC-TRI-001",
                        stage="config",
                        path=f"{change_path}.risk_rules",
                        message="scenario changes cannot override risk_rules in v1",
                    )
                required = {"timeframe", "instance_id", "params"}
                missing_change = sorted(required.difference(change))
                if missing_change:
                    raise RuntimeContractError(
                        code="PC-CFG-001",
                        stage="config",
                        path=change_path,
                        message=f"missing required fields: {','.join(missing_change)}",
                    )
                unknown_change = sorted(set(change).difference(required))
                if unknown_change:
                    raise RuntimeContractError(
                        code="PC-CFG-002",
                        stage="config",
                        path=change_path,
                        message=f"unknown fields: {','.join(unknown_change)}",
                    )

                timeframe = change.get("timeframe")
                instance_id = change.get("instance_id")
                params = change.get("params")
                if not isinstance(timeframe, str) or not timeframe.strip():
                    raise RuntimeContractError(
                        code="PC-CFG-003",
                        stage="config",
                        path=f"{change_path}.timeframe",
                        message="timeframe must be non-empty string",
                    )
                if not isinstance(instance_id, str) or not instance_id.strip():
                    raise RuntimeContractError(
                        code="PC-CFG-003",
                        stage="config",
                        path=f"{change_path}.instance_id",
                        message="instance_id must be non-empty string",
                    )
                if not isinstance(params, dict):
                    raise RuntimeContractError(
                        code="PC-CFG-003",
                        stage="config",
                        path=f"{change_path}.params",
                        message="params must be an object",
                    )
                timeframe = timeframe.strip()
                instance_id = instance_id.strip()
                target = (timeframe, instance_id)
                if target in seen_targets:
                    raise RuntimeContractError(
                        code="PC-TRI-002",
                        stage="config",
                        path=change_path,
                        message=f"duplicate scenario target: {timeframe}+{instance_id}",
                    )
                seen_targets.add(target)
                valid_instances = instance_index.get(timeframe)
                if valid_instances is None or instance_id not in valid_instances:
                    raise RuntimeContractError(
                        code="PC-TRI-001",
                        stage="config",
                        path=change_path,
                        message=f"scenario target not found: {timeframe}+{instance_id}",
                    )
                normalized_changes.append(
                    {
                        "timeframe": timeframe,
                        "instance_id": instance_id,
                        "params": copy.deepcopy(params),
                    }
                )

            normalized_scenarios.append(
                {
                    "trial_id": trial_id,
                    "changes": normalized_changes,
                }
            )

        payload["trial_config"] = {
            "mode": "scenarios",
            "scenarios": normalized_scenarios,
        }

    def _resolve_scenario_trials(
        self,
        base_resolved: dict[str, Any],
        scenarios: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        trials: list[dict[str, Any]] = []
        for sidx, scenario in enumerate(scenarios):
            scenario_path = f"$.trial_config.scenarios[{sidx}]"
            trial_id = str(scenario["trial_id"])
            scenario_config = copy.deepcopy(base_resolved)
            for cidx, change in enumerate(scenario["changes"]):
                self._apply_change(
                    resolved=scenario_config,
                    change=change,
                    change_path=f"{scenario_path}.changes[{cidx}]",
                )
            trials.append(
                {
                    "trial_id": trial_id,
                    "changes": copy.deepcopy(scenario["changes"]),
                    "resolved_config": scenario_config,
                }
            )
        return trials

    def _apply_change(self, *, resolved: dict[str, Any], change: dict[str, Any], change_path: str) -> None:
        timeframe = str(change["timeframe"])
        instance_id = str(change["instance_id"])
        params = change["params"]
        indicator_plan_by_tf = resolved.get("indicator_plan_by_tf")
        if not isinstance(indicator_plan_by_tf, dict):
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="config",
                path="$.indicator_plan_by_tf",
                message="indicator_plan_by_tf must be an object",
            )
        plan = indicator_plan_by_tf.get(timeframe)
        if not isinstance(plan, list):
            raise RuntimeContractError(
                code="PC-TRI-001",
                stage="config",
                path=change_path,
                message=f"scenario target not found: {timeframe}+{instance_id}",
            )
        for item in plan:
            if str(item.get("instance_id", "")).strip() == instance_id:
                item["params"] = copy.deepcopy(params)
                return
        raise RuntimeContractError(
            code="PC-TRI-001",
            stage="config",
            path=change_path,
            message=f"scenario target not found: {timeframe}+{instance_id}",
        )


__all__ = ["ConfigLoader", "LoadedRuntimeConfig"]
