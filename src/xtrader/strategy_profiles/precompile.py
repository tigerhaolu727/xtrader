"""Precompile entry for strategy profile schema gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xtrader.strategy_profiles.errors import StrategyProfileContractError
from xtrader.strategy_profiles.loader import LoadedStrategyProfile, StrategyProfileLoader
from xtrader.strategy_profiles.score_fn_registry import ParamSpec, SCORE_FN_REGISTRY_V03

_MULTI_OUTPUT_SUFFIXES: dict[str, tuple[str, ...]] = {
    "macd": ("line", "signal", "hist"),
    "bollinger": ("mid", "up", "low"),
    "kd": ("k", "d", "j"),
    "dmi": ("plus_di", "minus_di", "adx"),
}


@dataclass(frozen=True, slots=True)
class StrategyProfilePrecompileResult:
    status: str
    resolved_profile: dict[str, Any] = field(default_factory=dict)
    required_feature_refs: list[str] = field(default_factory=list)
    required_indicator_plan_by_tf: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    resolved_input_bindings: dict[str, dict[str, str]] = field(default_factory=dict)
    feature_catalog: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    error_path: str | None = None


class StrategyProfilePrecompileEngine:
    """Run schema gate before profile execution pipeline."""

    def __init__(self, *, loader: StrategyProfileLoader | None = None) -> None:
        self.loader = loader or StrategyProfileLoader()

    def compile(self, config: dict[str, Any] | str | Path | LoadedStrategyProfile) -> StrategyProfilePrecompileResult:
        try:
            loaded = config if isinstance(config, LoadedStrategyProfile) else self.loader.load(config)
            artifacts = self._compile_semantics(loaded.resolved)
            return StrategyProfilePrecompileResult(
                status="SUCCESS",
                resolved_profile=loaded.resolved,
                required_feature_refs=artifacts["required_feature_refs"],
                required_indicator_plan_by_tf=artifacts["required_indicator_plan_by_tf"],
                resolved_input_bindings=artifacts["resolved_input_bindings"],
                feature_catalog=artifacts["feature_catalog"],
            )
        except StrategyProfileContractError as err:
            return StrategyProfilePrecompileResult(
                status="FAILED",
                resolved_profile={},
                error_code=err.code,
                error_message=err.message,
                error_path=err.path,
            )

    def _compile_semantics(self, resolved: dict[str, Any]) -> dict[str, Any]:
        indicator_index = self._build_indicator_index(resolved)
        required_refs: set[str] = set()

        regime_spec = dict(resolved["regime_spec"])
        signal_spec = dict(resolved["signal_spec"])

        self._validate_classifier_consistency(regime_spec)
        self._validate_signal_rules(regime_spec=regime_spec, signal_spec=signal_spec)
        resolved_input_bindings = self._validate_score_rules(regime_spec=regime_spec, required_refs=required_refs)

        # Collect classifier refs from enabled rules after set-consistency gate.
        classifier = dict(regime_spec["classifier"])
        for rule in classifier["rules"]:
            if not bool(rule.get("enabled", True)):
                continue
            for cond in rule["conditions"]:
                required_refs.add(str(cond["ref"]))
        for rule in regime_spec["groups"]:
            if not bool(rule.get("enabled", True)):
                continue
            for item in rule["rules"]:
                if not bool(item.get("enabled", True)):
                    continue
                for ref in item["input_refs"]:
                    required_refs.add(str(ref))

        required_feature_refs = sorted(required_refs)
        feature_catalog = self._build_required_feature_catalog(
            required_feature_refs=required_feature_refs,
            indicator_index=indicator_index,
        )
        required_indicator_plan_by_tf = self._build_required_indicator_plan(
            resolved=resolved,
            required_feature_refs=required_feature_refs,
        )
        return {
            "required_feature_refs": required_feature_refs,
            "required_indicator_plan_by_tf": required_indicator_plan_by_tf,
            "resolved_input_bindings": resolved_input_bindings,
            "feature_catalog": feature_catalog,
        }

    def _build_indicator_index(self, resolved: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        indicator_plan_by_tf = dict(resolved["indicator_plan_by_tf"])
        index: dict[tuple[str, str], dict[str, Any]] = {}
        for timeframe, items in indicator_plan_by_tf.items():
            seen: set[str] = set()
            for idx, item in enumerate(items):
                instance_id = str(item["instance_id"])
                if instance_id in seen:
                    raise StrategyProfileContractError(
                        code="DUPLICATE_INDICATOR_INSTANCE",
                        stage="profile_precompile",
                        path=f"$.indicator_plan_by_tf.{timeframe}[{idx}].instance_id",
                        message=f"duplicate instance_id in timeframe {timeframe}: {instance_id}",
                    )
                seen.add(instance_id)
                index[(str(timeframe), instance_id)] = dict(item)
        return index

    def _validate_classifier_consistency(self, regime_spec: dict[str, Any]) -> None:
        states = set(regime_spec["states"])
        classifier = dict(regime_spec["classifier"])

        default_state = str(classifier["default_state"])
        if default_state not in states:
            raise StrategyProfileContractError(
                code="CLASSIFIER_DEFAULT_STATE_UNKNOWN",
                stage="profile_precompile",
                path="$.regime_spec.classifier.default_state",
                message=f"default_state is not in regime states: {default_state}",
            )

        declared = {str(item) for item in classifier["inputs"]}
        used: set[str] = set()
        seen_priorities: set[int] = set()
        for idx, rule in enumerate(classifier["rules"]):
            priority = int(rule["priority"])
            if priority in seen_priorities:
                raise StrategyProfileContractError(
                    code="CLASSIFIER_PRIORITY_DUPLICATE",
                    stage="profile_precompile",
                    path=f"$.regime_spec.classifier.rules[{idx}].priority",
                    message=f"duplicate classifier priority: {priority}",
                )
            seen_priorities.add(priority)

            target_state = str(rule["target_state"])
            if target_state not in states:
                raise StrategyProfileContractError(
                    code="CLASSIFIER_TARGET_STATE_UNKNOWN",
                    stage="profile_precompile",
                    path=f"$.regime_spec.classifier.rules[{idx}].target_state",
                    message=f"target_state is not in regime states: {target_state}",
                )

            if bool(rule.get("enabled", True)):
                for cond in rule["conditions"]:
                    used.add(str(cond["ref"]))

        unused = sorted(declared.difference(used))
        if unused:
            raise StrategyProfileContractError(
                code="UNUSED_CLASSIFIER_INPUT",
                stage="profile_precompile",
                path="$.regime_spec.classifier.inputs",
                message=f"classifier inputs are declared but not used: {','.join(unused)}",
            )

        undeclared = sorted(used.difference(declared))
        if undeclared:
            raise StrategyProfileContractError(
                code="UNDECLARED_CLASSIFIER_REF",
                stage="profile_precompile",
                path="$.regime_spec.classifier.rules",
                message=f"classifier refs are used but not declared: {','.join(undeclared)}",
            )

    def _validate_score_rules(self, *, regime_spec: dict[str, Any], required_refs: set[str]) -> dict[str, dict[str, str]]:
        bindings: dict[str, dict[str, str]] = {}
        for gidx, group in enumerate(regime_spec["groups"]):
            if not bool(group.get("enabled", True)):
                continue
            for ridx, rule in enumerate(group["rules"]):
                if not bool(rule.get("enabled", True)):
                    continue
                rule_id = str(rule["rule_id"])
                if rule_id in bindings:
                    raise StrategyProfileContractError(
                        code="DUPLICATE_RULE_ID",
                        stage="profile_precompile",
                        path=f"$.regime_spec.groups[{gidx}].rules[{ridx}].rule_id",
                        message=f"duplicate rule_id across groups: {rule_id}",
                    )

                score_fn = str(rule["score_fn"])
                if score_fn not in SCORE_FN_REGISTRY_V03:
                    raise StrategyProfileContractError(
                        code="UNKNOWN_SCORE_FN",
                        stage="profile_precompile",
                        path=f"$.regime_spec.groups[{gidx}].rules[{ridx}].score_fn",
                        message=f"unsupported score_fn: {score_fn}",
                    )
                spec = SCORE_FN_REGISTRY_V03[score_fn]
                input_refs = [str(item) for item in rule["input_refs"]]
                if len(input_refs) != len(spec.input_roles):
                    raise StrategyProfileContractError(
                        code="SCORE_FN_INPUT_ARITY_MISMATCH",
                        stage="profile_precompile",
                        path=f"$.regime_spec.groups[{gidx}].rules[{ridx}].input_refs",
                        message=f"score_fn={score_fn} expects {len(spec.input_roles)} inputs but got {len(input_refs)}",
                    )

                binding = {role: input_refs[idx] for idx, role in enumerate(spec.input_roles)}
                bindings[rule_id] = binding
                for ref in input_refs:
                    required_refs.add(ref)

                params = dict(rule.get("params") or {})
                unknown = sorted(set(params).difference(spec.params))
                if unknown:
                    raise StrategyProfileContractError(
                        code="SCORE_FN_UNKNOWN_PARAM",
                        stage="profile_precompile",
                        path=f"$.regime_spec.groups[{gidx}].rules[{ridx}].params",
                        message=f"score_fn={score_fn} has unknown params: {','.join(unknown)}",
                    )
                for key, value in params.items():
                    self._validate_score_param(
                        score_fn=score_fn,
                        param_name=str(key),
                        value=value,
                        spec=spec.params[str(key)],
                        path=f"$.regime_spec.groups[{gidx}].rules[{ridx}].params.{key}",
                    )
        return bindings

    def _validate_score_param(
        self,
        *,
        score_fn: str,
        param_name: str,
        value: Any,
        spec: ParamSpec,
        path: str,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StrategyProfileContractError(
                code="SCORE_FN_PARAM_TYPE_INVALID",
                stage="profile_precompile",
                path=path,
                message=f"score_fn={score_fn} param={param_name} must be numeric",
            )
        if spec.kind == "integer" and not isinstance(value, int):
            raise StrategyProfileContractError(
                code="SCORE_FN_PARAM_TYPE_INVALID",
                stage="profile_precompile",
                path=path,
                message=f"score_fn={score_fn} param={param_name} must be integer",
            )
        numeric = float(value)
        if spec.minimum is not None:
            if spec.exclusive_minimum and not (numeric > spec.minimum):
                raise StrategyProfileContractError(
                    code="SCORE_FN_PARAM_OUT_OF_RANGE",
                    stage="profile_precompile",
                    path=path,
                    message=f"score_fn={score_fn} param={param_name} must be > {spec.minimum}",
                )
            if not spec.exclusive_minimum and numeric < spec.minimum:
                raise StrategyProfileContractError(
                    code="SCORE_FN_PARAM_OUT_OF_RANGE",
                    stage="profile_precompile",
                    path=path,
                    message=f"score_fn={score_fn} param={param_name} must be >= {spec.minimum}",
                )
        if spec.maximum is not None:
            if spec.exclusive_maximum and not (numeric < spec.maximum):
                raise StrategyProfileContractError(
                    code="SCORE_FN_PARAM_OUT_OF_RANGE",
                    stage="profile_precompile",
                    path=path,
                    message=f"score_fn={score_fn} param={param_name} must be < {spec.maximum}",
                )
            if not spec.exclusive_maximum and numeric > spec.maximum:
                raise StrategyProfileContractError(
                    code="SCORE_FN_PARAM_OUT_OF_RANGE",
                    stage="profile_precompile",
                    path=path,
                    message=f"score_fn={score_fn} param={param_name} must be <= {spec.maximum}",
                )

    def _validate_signal_rules(self, *, regime_spec: dict[str, Any], signal_spec: dict[str, Any]) -> None:
        states = set(regime_spec["states"])
        enabled_rules: list[dict[str, Any]] = []
        for field in ("entry_rules", "exit_rules", "hold_rules"):
            for idx, rule in enumerate(signal_spec.get(field, []) or []):
                if not bool(rule.get("enabled", True)):
                    continue
                path = f"$.signal_spec.{field}[{idx}]"
                enabled_rules.append({"rule": rule, "path": path})
                for key in ("state_allow", "state_deny"):
                    raw = rule.get(key)
                    if raw is None:
                        continue
                    unknown = sorted(set(raw).difference(states))
                    if unknown:
                        raise StrategyProfileContractError(
                            code="SIGNAL_STATE_UNKNOWN",
                            stage="profile_precompile",
                            path=f"{path}.{key}",
                            message=f"state filter contains unknown states: {','.join(unknown)}",
                        )
                self._validate_score_range(range_payload=dict(rule["score_range"]), path=f"{path}.score_range")

        seen_priority: dict[int, str] = {}
        for item in enabled_rules:
            rule = item["rule"]
            path = item["path"]
            rank = int(rule["priority_rank"])
            prev = seen_priority.get(rank)
            if prev is not None:
                raise StrategyProfileContractError(
                    code="SIGNAL_PRIORITY_RANK_DUPLICATE",
                    stage="profile_precompile",
                    path=f"{path}.priority_rank",
                    message=f"duplicate priority_rank={rank} also used by {prev}",
                )
            seen_priority[rank] = str(rule["id"])

        reason_code_map = dict(signal_spec.get("reason_code_map") or {})
        missing = sorted(
            str(item["rule"]["id"])
            for item in enabled_rules
            if str(item["rule"]["id"]) not in reason_code_map
        )
        if missing:
            raise StrategyProfileContractError(
                code="MISSING_REASON_CODE_MAPPING",
                stage="profile_precompile",
                path="$.signal_spec.reason_code_map",
                message=f"reason_code_map missing enabled rule ids: {','.join(missing)}",
            )

        has_hold_fallback = any(str(item["rule"]["action"]) == "HOLD" for item in enabled_rules)
        if not has_hold_fallback and enabled_rules:
            intervals = [self._normalize_score_range(item["rule"]["score_range"]) for item in enabled_rules]
            if not self._covers_full_score_range(intervals):
                raise StrategyProfileContractError(
                    code="SIGNAL_SCORE_RANGE_COVERAGE_GAP",
                    stage="profile_precompile",
                    path="$.signal_spec",
                    message="enabled rules do not fully cover score range [-1, 1] without HOLD fallback",
                )

    def _validate_score_range(self, *, range_payload: dict[str, Any], path: str) -> None:
        lower = range_payload.get("min")
        upper = range_payload.get("max")
        lower_inc = bool(range_payload.get("min_inclusive", True))
        upper_inc = bool(range_payload.get("max_inclusive", False))
        if lower is None and upper is None:
            raise StrategyProfileContractError(
                code="SIGNAL_SCORE_RANGE_INVALID",
                stage="profile_precompile",
                path=path,
                message="score_range min and max cannot both be null",
            )
        if lower is not None and upper is not None:
            lower_v = float(lower)
            upper_v = float(upper)
            if lower_v > upper_v:
                raise StrategyProfileContractError(
                    code="SIGNAL_SCORE_RANGE_INVALID",
                    stage="profile_precompile",
                    path=path,
                    message="score_range min must be <= max",
                )
            if lower_v == upper_v and not (lower_inc and upper_inc):
                raise StrategyProfileContractError(
                    code="SIGNAL_SCORE_RANGE_INVALID",
                    stage="profile_precompile",
                    path=path,
                    message="score_range is empty at equal bounds without closed interval",
                )

    def _normalize_score_range(self, payload: dict[str, Any]) -> tuple[float, float, bool, bool]:
        lower = float(payload["min"]) if payload.get("min") is not None else -1.0
        upper = float(payload["max"]) if payload.get("max") is not None else 1.0
        lower_inc = bool(payload.get("min_inclusive", True))
        upper_inc = bool(payload.get("max_inclusive", False))
        return lower, upper, lower_inc, upper_inc

    def _covers_full_score_range(self, intervals: list[tuple[float, float, bool, bool]]) -> bool:
        if not intervals:
            return False
        ordered = sorted(intervals, key=lambda item: (item[0], not item[2], item[1]))
        target_min = -1.0
        target_max = 1.0

        cur_upper: float | None = None
        cur_upper_inc = False
        for lower, upper, lower_inc, upper_inc in ordered:
            if cur_upper is None:
                if lower > target_min or (lower == target_min and not lower_inc):
                    return False
                cur_upper = upper
                cur_upper_inc = upper_inc
                if cur_upper > target_max or (cur_upper == target_max and cur_upper_inc):
                    return True
                continue

            assert cur_upper is not None
            has_gap = lower > cur_upper or (lower == cur_upper and not (cur_upper_inc or lower_inc))
            if has_gap:
                return False

            if upper > cur_upper:
                cur_upper = upper
                cur_upper_inc = upper_inc
            elif upper == cur_upper:
                cur_upper_inc = cur_upper_inc or upper_inc

            if cur_upper > target_max or (cur_upper == target_max and cur_upper_inc):
                return True

        return cur_upper is not None and (cur_upper > target_max or (cur_upper == target_max and cur_upper_inc))

    def _build_required_feature_catalog(
        self,
        *,
        required_feature_refs: list[str],
        indicator_index: dict[tuple[str, str], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        for ref in required_feature_refs:
            timeframe, instance_id, output_key = self._parse_feature_ref(ref=ref, path="$.profile")
            item = indicator_index.get((timeframe, instance_id))
            if item is None:
                raise StrategyProfileContractError(
                    code="UNRESOLVED_FEATURE_REF",
                    stage="profile_precompile",
                    path="$.profile",
                    message=f"feature_ref unresolved: {ref}",
                )
            family = str(item["family"]).strip().lower()
            allowed_outputs = _MULTI_OUTPUT_SUFFIXES.get(family, ("value",))
            if output_key not in allowed_outputs:
                raise StrategyProfileContractError(
                    code="UNRESOLVED_FEATURE_REF",
                    stage="profile_precompile",
                    path="$.profile",
                    message=f"invalid output_key '{output_key}' for {timeframe}:{instance_id}",
                )
            catalog.append(
                {
                    "feature_ref": ref,
                    "timeframe": timeframe,
                    "instance_id": instance_id,
                    "output_key": output_key,
                    "family": family,
                }
            )
        return catalog

    def _build_required_indicator_plan(
        self,
        *,
        resolved: dict[str, Any],
        required_feature_refs: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        required_by_tf: dict[str, set[str]] = {}
        for ref in required_feature_refs:
            timeframe, instance_id, _ = self._parse_feature_ref(ref=ref, path="$.profile")
            required_by_tf.setdefault(timeframe, set()).add(instance_id)

        result: dict[str, list[dict[str, Any]]] = {}
        for timeframe, items in dict(resolved["indicator_plan_by_tf"]).items():
            needed = required_by_tf.get(str(timeframe), set())
            if not needed:
                continue
            result[str(timeframe)] = [dict(item) for item in items if str(item["instance_id"]) in needed]
        return result

    def _parse_feature_ref(self, *, ref: str, path: str) -> tuple[str, str, str]:
        parts = str(ref).split(":")
        if len(parts) != 4 or parts[0] != "f":
            raise StrategyProfileContractError(
                code="UNRESOLVED_FEATURE_REF",
                stage="profile_precompile",
                path=path,
                message=f"invalid feature_ref format: {ref}",
            )
        return parts[1], parts[2], parts[3]


__all__ = ["StrategyProfilePrecompileEngine", "StrategyProfilePrecompileResult"]
