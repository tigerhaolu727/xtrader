from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from xtrader.strategies.base import (
    ActionStrategyResult,
    StrategyContext,
    StrategyResult,
    StrategySpec,
    TradeAction,
)


def test_strategy_spec_resolve_params_with_defaults() -> None:
    spec = StrategySpec(
        strategy_id="btc_intraday",
        version="v1",
        required_inputs=("score", "price"),
        params_schema={
            "signal_window": {"type": int, "default": 5, "min": 2, "max": 20},
            "max_turnover": {"type": float, "default": 0.4, "min": 0.0, "max": 1.0},
            "mode": {"type": str, "required": True},
        },
    )
    resolved = spec.resolve_params({"mode": "long_short"})
    assert resolved == {
        "signal_window": 5,
        "max_turnover": 0.4,
        "mode": "long_short",
    }


def test_strategy_spec_resolve_params_rejects_unknown_and_invalid() -> None:
    spec = StrategySpec(
        strategy_id="btc_intraday",
        version="v1",
        required_inputs=("score",),
        params_schema={
            "signal_window": {"type": int, "default": 5, "min": 2, "max": 10},
        },
    )
    with pytest.raises(ValueError, match="unknown parameters"):
        spec.resolve_params({"unknown": 1})
    with pytest.raises(TypeError, match="must be int"):
        spec.resolve_params({"signal_window": True})
    with pytest.raises(ValueError, match="must be <= 10"):
        spec.resolve_params({"signal_window": 12})


def test_strategy_context_require_input() -> None:
    score = pd.DataFrame(
        {
            "timestamp": [datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)],
            "symbol": ["BTCUSDT"],
            "score": [0.12],
        }
    )
    context = StrategyContext(
        as_of_time=datetime(2026, 3, 20, 0, 5, tzinfo=timezone.utc),
        universe=("BTCUSDT",),
        inputs={"score": score},
    )
    loaded = context.require_input("score")
    assert loaded.equals(score)
    with pytest.raises(KeyError, match="missing required input: price"):
        context.require_input("price")


def test_strategy_result_validate_schema() -> None:
    weights = pd.DataFrame(
        {
            "timestamp": [datetime(2026, 3, 20, 0, 5, tzinfo=timezone.utc)],
            "symbol": ["BTCUSDT"],
            "target_weight": [0.5],
        }
    )
    result = StrategyResult(
        strategy_id="rank_ls",
        strategy_version="v1",
        weights=weights,
    )
    result.validate_schema()

    invalid = StrategyResult(
        strategy_id="rank_ls",
        strategy_version="v1",
        weights=weights.drop(columns=["target_weight"]),
    )
    with pytest.raises(ValueError, match="missing required columns"):
        invalid.validate_schema()


def test_action_strategy_result_validate_schema() -> None:
    actions = pd.DataFrame(
        {
            "timestamp": [datetime(2026, 3, 20, 0, 5, tzinfo=timezone.utc)],
            "symbol": ["BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value],
            "size": [1.0],
            "stop_loss": [0.01],
            "take_profit": [0.02],
            "reason": ["signal_entry"],
        }
    )
    result = ActionStrategyResult(
        strategy_id="btc_intraday_v1",
        strategy_version="v1",
        actions=actions,
    )
    result.validate_schema()


def test_action_strategy_result_rejects_invalid_action() -> None:
    actions = pd.DataFrame(
        {
            "timestamp": [datetime(2026, 3, 20, 0, 5, tzinfo=timezone.utc)],
            "symbol": ["BTCUSDT"],
            "action": ["BUY_NOW"],
            "size": [1.0],
            "stop_loss": [0.01],
            "take_profit": [0.02],
            "reason": ["bad_action"],
        }
    )
    result = ActionStrategyResult(
        strategy_id="btc_intraday_v1",
        strategy_version="v1",
        actions=actions,
    )
    with pytest.raises(ValueError, match="invalid action values"):
        result.validate_schema()
