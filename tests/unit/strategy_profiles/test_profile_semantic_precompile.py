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
