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
    "macd_state": (
        "state_code_num",
        "near_cross_num",
        "near_golden_flag",
        "near_dead_flag",
        "reject_long_flag",
        "reject_short_flag",
        "gap",
        "gap_slope",
        "gap_pct",
        "green_narrow_2_flag",
        "red_narrow_2_flag",
    ),
    "support_proximity": (
        "nearest_support_level",
        "nearest_resistance_level",
        "support_distance_pct",
        "resistance_distance_pct",
        "support_strength_code",
        "resistance_strength_code",
    ),
    "bollinger": ("mid", "up", "low"),
    "kd": ("k", "d", "j"),
    "dmi": ("plus_di", "minus_di", "adx"),
    "mama": ("mama", "fama"),
}

_TF_POINTS_COMPARE_OPS: set[str] = {
    ">",
    ">=",
    "<",
    "<=",
    "==",
    "!=",
    "gt",
    "gte",
    "lt",
    "lte",
    "eq",
    "neq",
    "cross_up",
    "cross_down",
}
_TF_POINTS_LOGIC_OPS: set[str] = {"all_of", "any_of", "not"}
_TF_POINTS_SUPPORTED_OPS: set[str] = _TF_POINTS_COMPARE_OPS | _TF_POINTS_LOGIC_OPS | {"between", "in_set"}
_STATE_SOURCE_FAMILY_MAP: dict[str, str] = {
    "macd_state": "macd",
}
_STATE_FORBIDDEN_MAIN_PARAMS: dict[str, set[str]] = {
    "macd_state": {"fast", "slow", "signal"},
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
        state_source_bindings = self._validate_state_source_bindings(
            resolved=resolved,
            indicator_index=indicator_index,
        )
        required_refs: set[str] = set()

        regime_spec = dict(resolved["regime_spec"])
        signal_spec = dict(resolved["signal_spec"])

        self._validate_classifier_consistency(regime_spec)
        self._validate_state_score_adjustments(regime_spec)
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
                for ref in item.get("input_refs", []):
                    required_refs.add(str(ref))
                for ref in dict(item.get("input_map") or {}).values():
                    required_refs.add(str(ref))

        required_feature_refs = sorted(required_refs)
        feature_catalog = self._build_required_feature_catalog(
            required_feature_refs=required_feature_refs,
            indicator_index=indicator_index,
        )
        required_indicator_plan_by_tf = self._build_required_indicator_plan(
            resolved=resolved,
            required_feature_refs=required_feature_refs,
            indicator_index=indicator_index,
            state_source_bindings=state_source_bindings,
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

    def _validate_state_score_adjustments(self, regime_spec: dict[str, Any]) -> None:
        states = set(str(item) for item in regime_spec["states"])
        payload = dict(regime_spec.get("state_score_adjustments") or {})
        unknown = sorted(set(payload).difference(states))
        if unknown:
            raise StrategyProfileContractError(
                code="STATE_ADJUSTMENT_INVALID",
                stage="profile_precompile",
                path="$.regime_spec.state_score_adjustments",
                message=f"state_score_adjustments contains unknown states: {','.join(unknown)}",
            )
        for state_name, item in payload.items():
            fn = str(dict(item).get("fn") or "").strip()
            if not fn:
                raise StrategyProfileContractError(
                    code="STATE_ADJUSTMENT_INVALID",
                    stage="profile_precompile",
                    path=f"$.regime_spec.state_score_adjustments.{state_name}.fn",
                    message="state_score_adjustments.fn must be non-empty",
                )

    def _validate_state_source_bindings(
        self,
        *,
        resolved: dict[str, Any],
        indicator_index: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[tuple[str, str], tuple[str, str]]:
        bindings: dict[tuple[str, str], tuple[str, str]] = {}
        for timeframe, items in dict(resolved["indicator_plan_by_tf"]).items():
            tf = str(timeframe)
            for idx, item in enumerate(items):
                family = str(item["family"]).strip().lower()
                expected_source_family = _STATE_SOURCE_FAMILY_MAP.get(family)
                if expected_source_family is None:
                    continue

                params = dict(item.get("params") or {})
                source_instance_id = str(params.get("source_instance_id") or "").strip()
                if not source_instance_id:
                    raise StrategyProfileContractError(
                        code="STATE_SOURCE_BINDING_REQUIRED",
                        stage="profile_precompile",
                        path=f"$.indicator_plan_by_tf.{tf}[{idx}].params.source_instance_id",
                        message=f"{family} requires non-empty source_instance_id",
                    )

                forbidden = sorted(set(params).intersection(_STATE_FORBIDDEN_MAIN_PARAMS.get(family, set())))
                if forbidden:
                    key = forbidden[0]
                    raise StrategyProfileContractError(
                        code="STATE_SOURCE_FORBIDDEN_PARAM",
                        stage="profile_precompile",
                        path=f"$.indicator_plan_by_tf.{tf}[{idx}].params.{key}",
                        message=f"{family} forbids main-indicator param '{key}' when source_instance_id is used",
                    )

                source_item = indicator_index.get((tf, source_instance_id))
                if source_item is None:
                    raise StrategyProfileContractError(
                        code="STATE_SOURCE_NOT_FOUND",
                        stage="profile_precompile",
                        path=f"$.indicator_plan_by_tf.{tf}[{idx}].params.source_instance_id",
                        message=f"{family} source_instance_id unresolved in timeframe {tf}: {source_instance_id}",
                    )

                source_family = str(source_item["family"]).strip().lower()
                if source_family != expected_source_family:
                    raise StrategyProfileContractError(
                        code="STATE_SOURCE_FAMILY_MISMATCH",
                        stage="profile_precompile",
                        path=f"$.indicator_plan_by_tf.{tf}[{idx}].params.source_instance_id",
                        message=f"{family} expects source family {expected_source_family}, got {source_family}",
                    )
                state_instance_id = str(item["instance_id"]).strip()
                bindings[(tf, state_instance_id)] = (tf, source_instance_id)
        return bindings

    def _validate_score_rules(self, *, regime_spec: dict[str, Any], required_refs: set[str]) -> dict[str, dict[str, str]]:
        bindings: dict[str, dict[str, str]] = {}
        for gidx, group in enumerate(regime_spec["groups"]):
            if not bool(group.get("enabled", True)):
                continue
            group_tf = str(group.get("timeframe") or "").strip().lower() or None
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
                if score_fn == "tf_points_score_v1":
                    binding = self._validate_tf_points_rule(
                        rule=rule,
                        path=f"$.regime_spec.groups[{gidx}].rules[{ridx}]",
                    )
                    self._validate_group_timeframe_refs(
                        group_timeframe=group_tf,
                        refs=tuple(binding.values()),
                        path=f"$.regime_spec.groups[{gidx}].rules[{ridx}].input_map",
                    )
                    bindings[rule_id] = binding
                    for ref in binding.values():
                        required_refs.add(str(ref))
                    continue

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
                self._validate_group_timeframe_refs(
                    group_timeframe=group_tf,
                    refs=tuple(binding.values()),
                    path=f"$.regime_spec.groups[{gidx}].rules[{ridx}].input_refs",
                )
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

    def _validate_group_timeframe_refs(
        self,
        *,
        group_timeframe: str | None,
        refs: tuple[str, ...],
        path: str,
    ) -> None:
        if not group_timeframe:
            return
        for ref in refs:
            timeframe, _, _ = self._parse_feature_ref(ref=str(ref), path=path)
            if str(timeframe).lower() != str(group_timeframe).lower():
                raise StrategyProfileContractError(
                    code="TF_GROUP_REF_TIMEFRAME_MISMATCH",
                    stage="profile_precompile",
                    path=path,
                    message=f"feature_ref timeframe {timeframe} != group timeframe {group_timeframe}",
                )

    def _validate_tf_points_rule(self, *, rule: dict[str, Any], path: str) -> dict[str, str]:
        input_map = {str(k): str(v) for k, v in dict(rule.get("input_map") or {}).items()}
        if not input_map:
            raise StrategyProfileContractError(
                code="SCORE_FN_INPUT_MAP_REQUIRED",
                stage="profile_precompile",
                path=f"{path}.input_map",
                message="tf_points_score_v1 requires non-empty input_map",
            )
        aliases = set(input_map)
        long_conditions = list(rule.get("long_conditions") or [])
        short_conditions = list(rule.get("short_conditions") or [])
        if not long_conditions and not short_conditions:
            raise StrategyProfileContractError(
                code="TF_POINTS_EXPR_INVALID",
                stage="profile_precompile",
                path=path,
                message="tf_points_score_v1 requires long_conditions or short_conditions",
            )
        max_abs_points = rule.get("max_abs_points")
        if max_abs_points is None or float(max_abs_points) <= 0.0:
            raise StrategyProfileContractError(
                code="TF_POINTS_EXPR_INVALID",
                stage="profile_precompile",
                path=f"{path}.max_abs_points",
                message="tf_points_score_v1 max_abs_points must be > 0",
            )

        self._validate_tf_points_conditions(
            conditions=long_conditions,
            aliases=aliases,
            path=f"{path}.long_conditions",
        )
        self._validate_tf_points_conditions(
            conditions=short_conditions,
            aliases=aliases,
            path=f"{path}.short_conditions",
        )
        return input_map

    def _validate_tf_points_conditions(
        self,
        *,
        conditions: list[dict[str, Any]],
        aliases: set[str],
        path: str,
    ) -> None:
        seen_ids: set[str] = set()
        for idx, item in enumerate(conditions):
            cond = dict(item)
            cond_id = str(cond.get("id") or "").strip()
            if not cond_id:
                raise StrategyProfileContractError(
                    code="TF_POINTS_EXPR_INVALID",
                    stage="profile_precompile",
                    path=f"{path}[{idx}].id",
                    message="condition id must be non-empty",
                )
            if cond_id in seen_ids:
                raise StrategyProfileContractError(
                    code="TF_POINTS_EXPR_INVALID",
                    stage="profile_precompile",
                    path=f"{path}[{idx}].id",
                    message=f"duplicate condition id: {cond_id}",
                )
            seen_ids.add(cond_id)

            points = cond.get("points")
            if points is None or float(points) < 0.0:
                raise StrategyProfileContractError(
                    code="TF_POINTS_EXPR_INVALID",
                    stage="profile_precompile",
                    path=f"{path}[{idx}].points",
                    message="condition points must be >= 0",
                )
            self._validate_tf_points_expr(
                expr=cond.get("expr"),
                aliases=aliases,
                path=f"{path}[{idx}].expr",
            )

    def _validate_tf_points_expr(self, *, expr: Any, aliases: set[str], path: str) -> None:
        if not isinstance(expr, dict):
            raise StrategyProfileContractError(
                code="TF_POINTS_EXPR_INVALID",
                stage="profile_precompile",
                path=path,
                message="expr must be object",
            )
        op = str(expr.get("op") or "").strip()
        if op not in _TF_POINTS_SUPPORTED_OPS:
            raise StrategyProfileContractError(
                code="TF_POINTS_EXPR_INVALID",
                stage="profile_precompile",
                path=f"{path}.op",
                message=f"unsupported expr op: {op}",
            )

        if op in _TF_POINTS_LOGIC_OPS:
            if op == "not":
                self._validate_tf_points_expr(expr=expr.get("arg"), aliases=aliases, path=f"{path}.arg")
                return
            args = expr.get("args")
            if not isinstance(args, list) or not args:
                raise StrategyProfileContractError(
                    code="TF_POINTS_EXPR_INVALID",
                    stage="profile_precompile",
                    path=f"{path}.args",
                    message=f"{op} requires non-empty args",
                )
            for idx, item in enumerate(args):
                self._validate_tf_points_expr(expr=item, aliases=aliases, path=f"{path}.args[{idx}]")
            return

        if op == "between":
            self._validate_tf_points_operand(value=expr.get("value"), aliases=aliases, path=f"{path}.value")
            self._validate_tf_points_operand(value=expr.get("min"), aliases=aliases, path=f"{path}.min")
            self._validate_tf_points_operand(value=expr.get("max"), aliases=aliases, path=f"{path}.max")
            return

        if op == "in_set":
            self._validate_tf_points_operand(value=expr.get("left"), aliases=aliases, path=f"{path}.left")
            value_set = expr.get("set")
            if not isinstance(value_set, list) or not value_set:
                raise StrategyProfileContractError(
                    code="TF_POINTS_EXPR_INVALID",
                    stage="profile_precompile",
                    path=f"{path}.set",
                    message="in_set requires non-empty set array",
                )
            return

        self._validate_tf_points_operand(value=expr.get("left"), aliases=aliases, path=f"{path}.left")
        self._validate_tf_points_operand(value=expr.get("right"), aliases=aliases, path=f"{path}.right")

    def _validate_tf_points_operand(self, *, value: Any, aliases: set[str], path: str) -> None:
        if not isinstance(value, dict):
            raise StrategyProfileContractError(
                code="TF_POINTS_EXPR_INVALID",
                stage="profile_precompile",
                path=path,
                message="operand must be object",
            )
        has_ref = "ref" in value
        has_value = "value" in value
        if has_ref == has_value:
            raise StrategyProfileContractError(
                code="TF_POINTS_EXPR_INVALID",
                stage="profile_precompile",
                path=path,
                message="operand must contain exactly one of ref/value",
            )
        if has_ref:
            ref = str(value.get("ref") or "").strip()
            if ref not in aliases:
                raise StrategyProfileContractError(
                    code="TF_POINTS_EXPR_REF_UNKNOWN",
                    stage="profile_precompile",
                    path=f"{path}.ref",
                    message=f"expr ref is not declared in input_map: {ref}",
                )

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
        self._validate_entry_gate_spec(signal_spec=signal_spec)
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

    def _validate_entry_gate_spec(self, *, signal_spec: dict[str, Any]) -> None:
        gate_spec = signal_spec.get("entry_gate_spec")
        if gate_spec is None:
            return
        payload = dict(gate_spec)
        if not bool(payload.get("enabled", True)):
            return

        gates = list(payload.get("gates") or [])
        seen_ids: set[str] = set()
        for idx, gate in enumerate(gates):
            item = dict(gate)
            gate_id = str(item.get("id") or "").strip()
            if not gate_id:
                raise StrategyProfileContractError(
                    code="ENTRY_GATE_INVALID",
                    stage="profile_precompile",
                    path=f"$.signal_spec.entry_gate_spec.gates[{idx}].id",
                    message="entry gate id must be non-empty",
                )
            if gate_id in seen_ids:
                raise StrategyProfileContractError(
                    code="ENTRY_GATE_INVALID",
                    stage="profile_precompile",
                    path=f"$.signal_spec.entry_gate_spec.gates[{idx}].id",
                    message=f"duplicate entry gate id: {gate_id}",
                )
            seen_ids.add(gate_id)

            mode = str(item.get("mode") or "").strip()
            if mode not in {"all_of", "n_of_m", "cross_tf"}:
                raise StrategyProfileContractError(
                    code="ENTRY_GATE_INVALID",
                    stage="profile_precompile",
                    path=f"$.signal_spec.entry_gate_spec.gates[{idx}].mode",
                    message=f"unsupported entry gate mode: {mode}",
                )
            conditions = list(item.get("conditions") or [])
            if not conditions:
                raise StrategyProfileContractError(
                    code="ENTRY_GATE_INVALID",
                    stage="profile_precompile",
                    path=f"$.signal_spec.entry_gate_spec.gates[{idx}].conditions",
                    message="entry gate conditions must be non-empty",
                )
            min_hit = item.get("min_hit")
            if mode in {"n_of_m", "cross_tf"}:
                if min_hit is None:
                    raise StrategyProfileContractError(
                        code="ENTRY_GATE_INVALID",
                        stage="profile_precompile",
                        path=f"$.signal_spec.entry_gate_spec.gates[{idx}].min_hit",
                        message=f"{mode} requires min_hit",
                    )
                if isinstance(min_hit, bool) or not isinstance(min_hit, int):
                    raise StrategyProfileContractError(
                        code="ENTRY_GATE_INVALID",
                        stage="profile_precompile",
                        path=f"$.signal_spec.entry_gate_spec.gates[{idx}].min_hit",
                        message="min_hit must be integer",
                    )
                min_hit_v = int(min_hit)
                if min_hit_v < 1 or min_hit_v > len(conditions):
                    raise StrategyProfileContractError(
                        code="ENTRY_GATE_INVALID",
                        stage="profile_precompile",
                        path=f"$.signal_spec.entry_gate_spec.gates[{idx}].min_hit",
                        message=f"min_hit must be within [1, {len(conditions)}]",
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
        indicator_index: dict[tuple[str, str], dict[str, Any]],
        state_source_bindings: dict[tuple[str, str], tuple[str, str]],
    ) -> dict[str, list[dict[str, Any]]]:
        required_by_tf: dict[str, set[str]] = {}
        for ref in required_feature_refs:
            timeframe, instance_id, _ = self._parse_feature_ref(ref=ref, path="$.profile")
            required_by_tf.setdefault(timeframe, set()).add(instance_id)

        changed = True
        while changed:
            changed = False
            for (tf, state_instance_id), source_key in state_source_bindings.items():
                needed = required_by_tf.get(tf)
                if needed is None or state_instance_id not in needed:
                    continue
                source_tf, source_instance_id = source_key
                dep_set = required_by_tf.setdefault(source_tf, set())
                if source_instance_id in dep_set:
                    continue
                if (source_tf, source_instance_id) not in indicator_index:
                    continue
                dep_set.add(source_instance_id)
                changed = True

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
