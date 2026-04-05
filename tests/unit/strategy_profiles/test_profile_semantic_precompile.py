from __future__ import annotations

import copy
import json
from pathlib import Path

from xtrader.strategy_profiles import StrategyProfilePrecompileEngine


def _payload() -> dict[str, object]:
    return json.loads(
        Path("configs/strategy-profiles/five_min_regime_momentum/v0.3.json").read_text(encoding="utf-8")
    )


def test_semantic_precompile_positive() -> None:
    result = StrategyProfilePrecompileEngine().compile(_payload())
    assert result.status == "SUCCESS"
    assert "f:5m:dmi_14_14:adx" in result.required_feature_refs
    assert "5m" in result.required_indicator_plan_by_tf
    assert "trend_score_v1" in result.resolved_input_bindings
    assert result.resolved_input_bindings["trend_score_v1"]["ema_fast"] == "f:5m:ema_12:value"
    assert len(result.feature_catalog) >= 1


def test_semantic_precompile_rejects_score_fn_arity_mismatch() -> None:
    payload = _payload()
    payload["regime_spec"]["groups"][0]["rules"][0]["input_refs"] = ["f:5m:ema_12:value", "f:5m:ema_48:value"]
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "FAILED"
    assert result.error_code == "SCORE_FN_INPUT_ARITY_MISMATCH"


def test_semantic_precompile_rejects_unused_classifier_input() -> None:
    payload = _payload()
    payload["regime_spec"]["classifier"]["inputs"].append("f:5m:ema_12:value")
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "FAILED"
    assert result.error_code == "UNUSED_CLASSIFIER_INPUT"


def test_semantic_precompile_rejects_duplicate_signal_priority() -> None:
    payload = _payload()
    payload["signal_spec"]["entry_rules"][0]["priority_rank"] = payload["signal_spec"]["exit_rules"][0]["priority_rank"]
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "FAILED"
    assert result.error_code == "SIGNAL_PRIORITY_RANK_DUPLICATE"


def test_semantic_precompile_rejects_missing_reason_code_mapping() -> None:
    payload = _payload()
    broken = copy.deepcopy(payload)
    del broken["signal_spec"]["reason_code_map"]["short_breakout_v1"]
    result = StrategyProfilePrecompileEngine().compile(broken)
    assert result.status == "FAILED"
    assert result.error_code == "MISSING_REASON_CODE_MAPPING"


def test_semantic_precompile_rejects_score_coverage_gap_without_hold() -> None:
    payload = _payload()
    broken = copy.deepcopy(payload)
    broken["signal_spec"]["hold_rules"] = []
    broken["signal_spec"]["entry_rules"][0]["score_range"]["min"] = 0.7
    broken["signal_spec"]["entry_rules"][0]["score_range"]["max"] = None
    broken["signal_spec"]["exit_rules"][0]["score_range"]["min"] = None
    broken["signal_spec"]["exit_rules"][0]["score_range"]["max"] = -0.7
    result = StrategyProfilePrecompileEngine().compile(broken)
    assert result.status == "FAILED"
    assert result.error_code == "SIGNAL_SCORE_RANGE_COVERAGE_GAP"


def _with_tf_points_contract(payload: dict[str, object]) -> dict[str, object]:
    profile = copy.deepcopy(payload)
    group = profile["regime_spec"]["groups"][0]
    group["timeframe"] = "5m"
    rule = group["rules"][0]
    rule["score_fn"] = "tf_points_score_v1"
    rule["input_refs"] = []
    rule["input_map"] = {
        "rsi": "f:5m:atr_pct_rank_252:value",
        "macd_state": "f:5m:macd_12_26_9:hist",
    }
    rule["long_conditions"] = [
        {
            "id": "c_rsi",
            "points": 1.0,
            "expr": {"op": "lt", "left": {"ref": "rsi"}, "right": {"value": 0.5}},
        },
        {
            "id": "c_state",
            "points": 1.0,
            "expr": {"op": "in_set", "left": {"ref": "macd_state"}, "set": [-1.0, 0.0, 1.0]},
        },
    ]
    rule["short_conditions"] = [
        {
            "id": "c_short",
            "points": 1.0,
            "expr": {"op": "gt", "left": {"ref": "rsi"}, "right": {"value": 0.7}},
        }
    ]
    rule["max_abs_points"] = 3.0
    rule["params"] = {}

    profile["regime_spec"]["state_score_adjustments"] = {
        "TREND_CLEAN": {
            "fn": "coherence_adjust_v1",
            "params": {"gain": 0.25},
        }
    }
    profile["signal_spec"]["entry_gate_spec"] = {
        "enabled": True,
        "gates": [
            {
                "id": "standard_long_gate",
                "side": "LONG",
                "level": "STANDARD",
                "mode": "n_of_m",
                "min_hit": 1,
                "conditions": [{"key": "tf.5m.rsi_lt_35", "required": False}],
            }
        ],
    }
    return profile


def test_semantic_precompile_accepts_tf_points_contract() -> None:
    payload = _with_tf_points_contract(_payload())
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "SUCCESS"
    assert "trend_score_v1" in result.resolved_input_bindings
    binding = result.resolved_input_bindings["trend_score_v1"]
    assert binding["rsi"] == "f:5m:atr_pct_rank_252:value"
    assert binding["macd_state"] == "f:5m:macd_12_26_9:hist"


def test_semantic_precompile_rejects_tf_points_unknown_ref() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["regime_spec"]["groups"][0]["rules"][0]["long_conditions"][0]["expr"]["left"]["ref"] = "missing_alias"
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "FAILED"
    assert result.error_code == "TF_POINTS_EXPR_REF_UNKNOWN"


def test_semantic_precompile_rejects_invalid_entry_gate() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["signal_spec"]["entry_gate_spec"]["gates"][0]["min_hit"] = 3
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "FAILED"
    assert result.error_code == "ENTRY_GATE_INVALID"


def test_semantic_precompile_rejects_unknown_state_adjustment() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["regime_spec"]["state_score_adjustments"]["UNKNOWN_STATE"] = {"fn": "coherence_adjust_v1"}
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "FAILED"
    assert result.error_code == "STATE_ADJUSTMENT_INVALID"


def test_semantic_precompile_accepts_macd_state_suffix_feature_ref() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["indicator_plan_by_tf"]["5m"].append(
        {
            "instance_id": "macd_state_main",
            "family": "macd_state",
            "params": {"source_instance_id": "macd_12_26_9"},
        }
    )
    rule = payload["regime_spec"]["groups"][0]["rules"][0]
    rule["input_map"]["macd_state"] = "f:5m:macd_state_main:near_golden_flag"
    rule["long_conditions"][1]["expr"]["set"] = [0.0, 1.0]
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "SUCCESS"
    assert result.resolved_input_bindings["trend_score_v1"]["macd_state"] == "f:5m:macd_state_main:near_golden_flag"


def test_semantic_precompile_accepts_support_proximity_suffix_feature_ref() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["indicator_plan_by_tf"]["5m"].append(
        {
            "instance_id": "sp_main",
            "family": "support_proximity",
            "params": {"lookback": 20, "round_step": 100.0},
        }
    )
    rule = payload["regime_spec"]["groups"][0]["rules"][0]
    rule["input_map"]["macd_state"] = "f:5m:sp_main:support_strength_code"
    rule["long_conditions"][1]["expr"]["set"] = [0.0, 1.0, 2.0, 3.0]
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "SUCCESS"
    assert result.resolved_input_bindings["trend_score_v1"]["macd_state"] == "f:5m:sp_main:support_strength_code"


def test_semantic_precompile_accepts_mama_suffix_feature_ref() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["indicator_plan_by_tf"]["5m"].append(
        {
            "instance_id": "mama_main",
            "family": "mama",
            "params": {"fast_limit": 0.5, "slow_limit": 0.05},
        }
    )
    rule = payload["regime_spec"]["groups"][0]["rules"][0]
    rule["input_map"]["macd_state"] = "f:5m:mama_main:mama"
    rule["long_conditions"][1]["expr"]["set"] = [0.0, 1.0]
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "SUCCESS"
    assert result.resolved_input_bindings["trend_score_v1"]["macd_state"] == "f:5m:mama_main:mama"


def test_semantic_precompile_accepts_ai_multi_tf_signal_v2_profile() -> None:
    payload = json.loads(
        Path("configs/strategy-profiles/ai_multi_tf_signal_v1/v0.2.json").read_text(encoding="utf-8")
    )
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "SUCCESS"
    assert len(result.required_feature_refs) >= 1


def test_semantic_precompile_rejects_state_missing_source_binding() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["indicator_plan_by_tf"]["5m"].append(
        {
            "instance_id": "macd_state_main",
            "family": "macd_state",
            "params": {},
        }
    )
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "FAILED"
    assert result.error_code == "STATE_SOURCE_BINDING_REQUIRED"


def test_semantic_precompile_rejects_state_forbidden_main_params() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["indicator_plan_by_tf"]["5m"].append(
        {
            "instance_id": "macd_state_main",
            "family": "macd_state",
            "params": {"source_instance_id": "macd_12_26_9", "fast": 12},
        }
    )
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "FAILED"
    assert result.error_code == "STATE_SOURCE_FORBIDDEN_PARAM"


def test_semantic_precompile_rejects_state_missing_source_instance() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["indicator_plan_by_tf"]["5m"].append(
        {
            "instance_id": "macd_state_main",
            "family": "macd_state",
            "params": {"source_instance_id": "macd_missing"},
        }
    )
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "FAILED"
    assert result.error_code == "STATE_SOURCE_NOT_FOUND"


def test_semantic_precompile_rejects_state_source_family_mismatch() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["indicator_plan_by_tf"]["5m"].append(
        {
            "instance_id": "macd_state_main",
            "family": "macd_state",
            "params": {"source_instance_id": "ema_12"},
        }
    )
    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "FAILED"
    assert result.error_code == "STATE_SOURCE_FAMILY_MISMATCH"


def test_semantic_precompile_auto_includes_state_source_dependency() -> None:
    payload = _with_tf_points_contract(_payload())
    payload["indicator_plan_by_tf"]["5m"].append(
        {
            "instance_id": "macd_state_main",
            "family": "macd_state",
            "params": {"source_instance_id": "macd_12_26_9"},
        }
    )
    rule = payload["regime_spec"]["groups"][0]["rules"][0]
    rule["input_map"]["macd_state"] = "f:5m:macd_state_main:near_golden_flag"
    rule["long_conditions"][1]["expr"]["set"] = [0.0, 1.0]

    result = StrategyProfilePrecompileEngine().compile(payload)
    assert result.status == "SUCCESS"
    required_ids = {str(item["instance_id"]) for item in result.required_indicator_plan_by_tf["5m"]}
    assert "macd_state_main" in required_ids
    assert "macd_12_26_9" in required_ids
