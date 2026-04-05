from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from xtrader.strategies.feature_engine.pipeline import FeaturePipeline
from xtrader.strategy_profiles import (
    RegimeScoringEngine,
    SignalEngine,
    StrategyProfilePrecompileEngine,
)


def _bars_5m(rows: int = 420) -> pd.DataFrame:
    ts = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=rows, freq="5min", tz="UTC")
    close = pd.Series([100.0 + (i * 0.23) + ((i % 9) - 4) * 0.11 for i in range(rows)], dtype="float64")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["BTCUSDT"] * rows,
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.3,
            "close": close,
            "volume": [1100.0 + ((i * 13) % 170) for i in range(rows)],
        }
    )


def _payload() -> dict[str, object]:
    return json.loads(
        Path("configs/strategy-profiles/five_min_regime_momentum/v0.3.json").read_text(encoding="utf-8")
    )


def _signal_profile(signal_spec: dict[str, object]) -> dict[str, object]:
    return {"signal_spec": signal_spec}


def _scoring_df(
    scores: list[float],
    states: list[str],
    symbol: str = "BTCUSDT",
    condition_results: list[dict[str, bool]] | None = None,
) -> pd.DataFrame:
    ts = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=len(scores), freq="5min", tz="UTC")
    payload = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": [symbol] * len(scores),
            "score_total": scores,
            "state": states,
        }
    )
    if condition_results is not None:
        payload["condition_results"] = condition_results
    return payload


def test_signal_engine_profile_positive() -> None:
    payload = _payload()
    precompile = StrategyProfilePrecompileEngine().compile(payload)
    assert precompile.status == "SUCCESS"

    bars = _bars_5m()
    model_df = FeaturePipeline().build_profile_model_df(
        bars_by_timeframe={"5m": bars},
        required_indicator_plan_by_tf=precompile.required_indicator_plan_by_tf,
        required_feature_refs=precompile.required_feature_refs,
        decision_timeframe=str(payload["regime_spec"]["decision_timeframe"]),
        alignment_policy=dict(payload["regime_spec"]["alignment_policy"]),
    )
    scoring = RegimeScoringEngine().run(
        resolved_profile=precompile.resolved_profile,
        resolved_input_bindings=precompile.resolved_input_bindings,
        model_df=model_df,
    ).frame

    result = SignalEngine().run(
        resolved_profile=precompile.resolved_profile,
        scoring_df=scoring,
    ).frame
    assert len(result.index) == len(scoring.index)
    assert {"timestamp", "symbol", "action", "reason_code", "reason", "matched_rule_id", "score_total", "state"}.issubset(
        set(result.columns)
    )
    assert set(result["action"].unique()).issubset({"ENTER_LONG", "ENTER_SHORT", "EXIT", "HOLD"})
    assert (result["reason"] == result["reason_code"]).all()


def test_signal_engine_score_range_boundary_positive() -> None:
    signal_spec = {
        "entry_rules": [
            {
                "id": "long_exclusive_upper",
                "action": "ENTER_LONG",
                "priority_rank": 1,
                "score_range": {"min": 0.5, "max": 1.0, "min_inclusive": True, "max_inclusive": False},
                "enabled": True,
            }
        ],
        "exit_rules": [
            {
                "id": "exit_exact_one",
                "action": "EXIT",
                "priority_rank": 2,
                "score_range": {"min": 1.0, "max": 1.0, "min_inclusive": True, "max_inclusive": True},
                "enabled": True,
            }
        ],
        "hold_rules": [
            {
                "id": "hold_default",
                "action": "HOLD",
                "priority_rank": 99,
                "score_range": {"min": -1.0, "max": 1.0, "min_inclusive": True, "max_inclusive": True},
                "enabled": True,
            }
        ],
        "cooldown_bars": 0,
        "cooldown_scope": "symbol_action",
        "reason_code_map": {
            "long_exclusive_upper": "LONG",
            "exit_exact_one": "EXIT",
            "hold_default": "HOLD",
        },
    }
    scoring = _scoring_df([1.0, 0.5], ["S", "S"])
    result = SignalEngine().run(resolved_profile=_signal_profile(signal_spec), scoring_df=scoring).frame
    assert result.loc[0, "action"] == "EXIT"
    assert result.loc[1, "action"] == "ENTER_LONG"


def test_signal_engine_state_deny_precedence_positive() -> None:
    signal_spec = {
        "entry_rules": [
            {
                "id": "deny_wins_rule",
                "action": "ENTER_LONG",
                "priority_rank": 1,
                "score_range": {"min": 0.2, "max": None, "min_inclusive": True, "max_inclusive": False},
                "state_allow": ["TREND_CLEAN"],
                "state_deny": ["TREND_CLEAN"],
                "enabled": True,
            }
        ],
        "exit_rules": [],
        "hold_rules": [
            {
                "id": "hold_default",
                "action": "HOLD",
                "priority_rank": 99,
                "score_range": {"min": -1.0, "max": 1.0, "min_inclusive": True, "max_inclusive": True},
                "enabled": True,
            }
        ],
        "cooldown_bars": 0,
        "cooldown_scope": "symbol_action",
        "reason_code_map": {
            "deny_wins_rule": "LONG",
            "hold_default": "HOLD",
        },
    }
    scoring = _scoring_df([0.8], ["TREND_CLEAN"])
    result = SignalEngine().run(resolved_profile=_signal_profile(signal_spec), scoring_df=scoring).frame
    assert result.loc[0, "action"] == "HOLD"


def test_signal_engine_priority_first_match_positive() -> None:
    signal_spec = {
        "entry_rules": [
            {
                "id": "entry_long_low_priority",
                "action": "ENTER_LONG",
                "priority_rank": 2,
                "score_range": {"min": 0.4, "max": None, "min_inclusive": True, "max_inclusive": False},
                "enabled": True,
            }
        ],
        "exit_rules": [
            {
                "id": "exit_high_priority",
                "action": "EXIT",
                "priority_rank": 1,
                "score_range": {"min": 0.4, "max": None, "min_inclusive": True, "max_inclusive": False},
                "enabled": True,
            }
        ],
        "hold_rules": [
            {
                "id": "hold_default",
                "action": "HOLD",
                "priority_rank": 99,
                "score_range": {"min": -1.0, "max": 1.0, "min_inclusive": True, "max_inclusive": True},
                "enabled": True,
            }
        ],
        "cooldown_bars": 0,
        "cooldown_scope": "symbol_action",
        "reason_code_map": {
            "entry_long_low_priority": "LONG",
            "exit_high_priority": "EXIT",
            "hold_default": "HOLD",
        },
    }
    scoring = _scoring_df([0.7], ["S"])
    result = SignalEngine().run(resolved_profile=_signal_profile(signal_spec), scoring_df=scoring).frame
    assert result.loc[0, "action"] == "EXIT"
    assert result.loc[0, "matched_rule_id"] == "exit_high_priority"


def test_signal_engine_cooldown_symbol_action_positive() -> None:
    signal_spec = {
        "entry_rules": [
            {
                "id": "entry_long",
                "action": "ENTER_LONG",
                "priority_rank": 1,
                "score_range": {"min": 0.5, "max": None, "min_inclusive": True, "max_inclusive": False},
                "enabled": True,
            }
        ],
        "exit_rules": [],
        "hold_rules": [
            {
                "id": "hold_default",
                "action": "HOLD",
                "priority_rank": 99,
                "score_range": {"min": -1.0, "max": 1.0, "min_inclusive": True, "max_inclusive": True},
                "enabled": True,
            }
        ],
        "cooldown_bars": 1,
        "cooldown_scope": "symbol_action",
        "reason_code_map": {
            "entry_long": "LONG",
            "hold_default": "HOLD",
        },
    }
    scoring = _scoring_df([0.8, 0.9, 0.95], ["S", "S", "S"])
    result = SignalEngine().run(resolved_profile=_signal_profile(signal_spec), scoring_df=scoring).frame
    assert result.loc[0, "action"] == "ENTER_LONG"
    assert result.loc[1, "action"] == "HOLD"
    assert result.loc[2, "action"] == "ENTER_LONG"


def test_signal_engine_missing_column_negative() -> None:
    payload = _payload()
    precompile = StrategyProfilePrecompileEngine().compile(payload)
    assert precompile.status == "SUCCESS"
    broken = _scoring_df([0.1], ["S"]).drop(columns=["state"])
    with pytest.raises(ValueError, match=r"XTRSP005::MISSING_INPUT_COLUMN::"):
        SignalEngine().run(resolved_profile=precompile.resolved_profile, scoring_df=broken)


def test_signal_engine_missing_reason_mapping_negative() -> None:
    payload = _payload()
    precompile = StrategyProfilePrecompileEngine().compile(payload)
    assert precompile.status == "SUCCESS"
    broken = copy.deepcopy(precompile.resolved_profile)
    del broken["signal_spec"]["reason_code_map"]["long_breakout_v1"]
    scoring = _scoring_df([0.9], ["TREND_CLEAN"])
    with pytest.raises(ValueError, match=r"XTRSP005::MISSING_REASON_CODE_MAPPING::"):
        SignalEngine().run(resolved_profile=broken, scoring_df=scoring)


def test_signal_engine_entry_gate_blocks_and_allows_positive() -> None:
    signal_spec = {
        "entry_rules": [
            {
                "id": "entry_long",
                "action": "ENTER_LONG",
                "priority_rank": 1,
                "score_range": {"min": 0.5, "max": None, "min_inclusive": True, "max_inclusive": False},
                "enabled": True,
            }
        ],
        "exit_rules": [],
        "hold_rules": [
            {
                "id": "hold_default",
                "action": "HOLD",
                "priority_rank": 99,
                "score_range": {"min": -1.0, "max": 1.0, "min_inclusive": True, "max_inclusive": True},
                "enabled": True,
            }
        ],
        "cooldown_bars": 0,
        "cooldown_scope": "symbol_action",
        "reason_code_map": {
            "entry_long": "LONG",
            "hold_default": "HOLD",
        },
        "entry_gate_spec": {
            "enabled": True,
            "gates": [
                {
                    "id": "long_gate_std",
                    "side": "LONG",
                    "level": "STANDARD",
                    "mode": "n_of_m",
                    "min_hit": 1,
                    "conditions": [{"key": "cond_ok", "required": False}],
                }
            ],
        },
    }
    scoring_blocked = _scoring_df([0.8], ["S"], condition_results=[{}])
    blocked = SignalEngine().run(resolved_profile=_signal_profile(signal_spec), scoring_df=scoring_blocked).frame
    assert blocked.loc[0, "action"] == "HOLD"
    assert isinstance(blocked.loc[0, "gate_results"], list)
    assert blocked.loc[0, "selected_gate_id"] is None

    scoring_allowed = _scoring_df([0.8], ["S"], condition_results=[{"cond_ok": True}])
    allowed = SignalEngine().run(resolved_profile=_signal_profile(signal_spec), scoring_df=scoring_allowed).frame
    assert allowed.loc[0, "action"] == "ENTER_LONG"
    assert allowed.loc[0, "selected_gate_id"] == "long_gate_std"
