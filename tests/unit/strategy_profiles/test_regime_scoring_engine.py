from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from xtrader.strategies.feature_engine.pipeline import FeaturePipeline
from xtrader.strategy_profiles import RegimeScoringEngine, StrategyProfilePrecompileEngine, run_score_fn_series


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


def _minimal_profile() -> dict[str, object]:
    return {
        "regime_spec": {
            "states": ["A", "B", "C", "NO_TRADE_EXTREME"],
            "classifier": {
                "inputs": ["f:5m:x:value"],
                "rules": [
                    {
                        "priority": 1,
                        "target_state": "A",
                        "conditions": [{"ref": "f:5m:x:value", "op": ">", "value": 0.0}],
                        "enabled": True,
                    },
                    {
                        "priority": 2,
                        "target_state": "B",
                        "conditions": [{"ref": "f:5m:x:value", "op": ">", "value": -1.0}],
                        "enabled": True,
                    },
                    {
                        "priority": 3,
                        "target_state": "NO_TRADE_EXTREME",
                        "conditions": [{"ref": "f:5m:x:value", "op": "<=", "value": -9.0}],
                        "enabled": True,
                    },
                ],
                "default_state": "C",
            },
            "groups": [
                {
                    "group_id": "trend",
                    "rules": [
                        {
                            "rule_id": "r1",
                            "score_fn": "trend_score",
                            "input_refs": ["f:5m:a:value", "f:5m:b:value", "f:5m:c:value"],
                            "params": {"atr_scale": 1.0},
                            "nan_policy": "neutral_zero",
                            "enabled": True,
                        }
                    ],
                    "rule_weights": {"r1": 1.0},
                    "enabled": True,
                }
            ],
            "state_group_weights": {
                "A": {"trend": 1.0},
                "B": {"trend": 1.0},
                "C": {"trend": 1.0},
                "NO_TRADE_EXTREME": {"trend": 0.0},
            },
        }
    }


def _minimal_model_df() -> pd.DataFrame:
    ts = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=3, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["BTCUSDT"] * 3,
            "f:5m:x:value": [1.0, -2.0, -10.0],
            "f:5m:a:value": [105.0, 99.0, 99.0],
            "f:5m:b:value": [100.0, 100.0, 100.0],
            "f:5m:c:value": [2.0, 2.0, 2.0],
        }
    )


def _minimal_bindings() -> dict[str, dict[str, str]]:
    return {"r1": {"ema_fast": "f:5m:a:value", "ema_slow": "f:5m:b:value", "atr_main": "f:5m:c:value"}}


def test_regime_scoring_engine_profile_positive() -> None:
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
    result = RegimeScoringEngine().run(
        resolved_profile=precompile.resolved_profile,
        resolved_input_bindings=precompile.resolved_input_bindings,
        model_df=model_df,
    )
    out = result.frame
    assert len(out.index) == len(model_df.index)
    assert {"state", "score_total", "group_scores", "group_weights", "rule_scores"}.issubset(set(out.columns))
    assert out["score_total"].between(-1.0, 1.0, inclusive="both").all()
    assert set(out["state"].dropna().unique()).issubset(set(payload["regime_spec"]["states"]))


def test_score_fn_registry_runtime_math_positive() -> None:
    idx = pd.RangeIndex(0, 140)

    trend = run_score_fn_series(
        score_fn="trend_score",
        inputs_by_role={
            "ema_fast": pd.Series(110.0, index=idx),
            "ema_slow": pd.Series(100.0, index=idx),
            "atr_main": pd.Series(2.0, index=idx),
        },
        params={"atr_scale": 1.5},
    )
    assert float(trend.iloc[-1]) > 0.0
    assert float(trend.max()) <= 1.0
    assert float(trend.min()) >= -1.0

    momentum = run_score_fn_series(
        score_fn="momentum_score",
        inputs_by_role={"macd_hist": pd.Series([float(i) for i in range(140)], index=idx)},
        params={"std_window": 20},
    )
    momentum_last = momentum.dropna().iloc[-1]
    assert float(momentum_last) > 0.0
    assert float(momentum.dropna().max()) <= 1.0
    assert float(momentum.dropna().min()) >= -1.0

    direction = run_score_fn_series(
        score_fn="direction_score",
        inputs_by_role={
            "plus_di": pd.Series(40.0, index=idx),
            "minus_di": pd.Series(10.0, index=idx),
            "adx": pd.Series(30.0, index=idx),
        },
        params={"adx_floor": 18.0, "adx_span": 12.0},
    )
    assert float(direction.iloc[-1]) > 0.0
    assert float(direction.max()) <= 1.0
    assert float(direction.min()) >= -1.0

    volume = run_score_fn_series(
        score_fn="volume_score",
        inputs_by_role={
            "volume_variation": pd.Series([0.2 + (i * 0.01) for i in range(140)], index=idx),
            "ema_fast": pd.Series(110.0, index=idx),
            "ema_slow": pd.Series(100.0, index=idx),
            "atr_main": pd.Series(2.0, index=idx),
            "macd_hist": pd.Series([float(i) for i in range(140)], index=idx),
        },
        params={"trend_mix": 0.6, "vol_scale": 0.8, "atr_scale": 1.5},
    )
    volume_last = volume.dropna().iloc[-1]
    assert float(volume_last) > 0.0
    assert float(volume.dropna().max()) <= 1.0
    assert float(volume.dropna().min()) >= -1.0

    pullback = run_score_fn_series(
        score_fn="pullback_score",
        inputs_by_role={
            "close": pd.Series(98.0, index=idx),
            "ema_fast": pd.Series(100.0, index=idx),
            "ema_slow": pd.Series(90.0, index=idx),
            "atr_main": pd.Series(2.0, index=idx),
        },
        params={"dev_scale": 1.2},
    )
    assert float(pullback.iloc[-1]) > 0.0
    assert float(pullback.max()) <= 1.0
    assert float(pullback.min()) >= -1.0


def test_classifier_first_match_priority_positive() -> None:
    profile = _minimal_profile()
    model_df = _minimal_model_df()
    result = RegimeScoringEngine().run(
        resolved_profile=profile,
        resolved_input_bindings=_minimal_bindings(),
        model_df=model_df,
    )
    out = result.frame
    assert out.loc[0, "state"] == "A"
    assert out.loc[1, "state"] == "C"


def test_state_weight_zero_sum_positive() -> None:
    profile = _minimal_profile()
    model_df = _minimal_model_df()
    result = RegimeScoringEngine().run(
        resolved_profile=profile,
        resolved_input_bindings=_minimal_bindings(),
        model_df=model_df,
    )
    out = result.frame
    row = out.iloc[2]
    assert row["state"] == "NO_TRADE_EXTREME"
    assert float(row["score_total"]) == pytest.approx(0.0)
    assert row["group_weights"]["trend"] == pytest.approx(0.0)


def test_missing_feature_ref_negative() -> None:
    profile = _minimal_profile()
    model_df = _minimal_model_df().drop(columns=["f:5m:a:value"])
    with pytest.raises(ValueError, match=r"XTRSP004::MISSING_FEATURE_REF::"):
        RegimeScoringEngine().run(
            resolved_profile=profile,
            resolved_input_bindings=_minimal_bindings(),
            model_df=model_df,
        )


def test_classifier_priority_applies_before_second_rule() -> None:
    profile = _minimal_profile()
    profile_2 = copy.deepcopy(profile)
    profile_2["regime_spec"]["classifier"]["rules"][1]["priority"] = 1
    profile_2["regime_spec"]["classifier"]["rules"][0]["priority"] = 2

    model_df = _minimal_model_df()
    result = RegimeScoringEngine().run(
        resolved_profile=profile_2,
        resolved_input_bindings=_minimal_bindings(),
        model_df=model_df,
    )
    out = result.frame
    assert out.loc[0, "state"] == "B"
