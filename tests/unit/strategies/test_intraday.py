from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from xtrader.strategies import StrategyContext, TradeAction
from xtrader.strategies.intraday import ThresholdIntradayStrategy


def test_threshold_intraday_strategy_generates_actions() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [
                datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 20, 0, 5, tzinfo=timezone.utc),
                datetime(2026, 3, 20, 0, 10, tzinfo=timezone.utc),
                datetime(2026, 3, 20, 0, 15, tzinfo=timezone.utc),
            ],
            "symbol": ["BTCUSDT", "BTCUSDT", "BTCUSDT", "BTCUSDT"],
            "value": [0.8, 0.02, -0.75, 0.3],
        }
    )
    context = StrategyContext(
        as_of_time=datetime(2026, 3, 20, 0, 20, tzinfo=timezone.utc),
        universe=("BTCUSDT",),
        inputs={"features": frame},
        params={
            "entry_threshold": 0.5,
            "exit_threshold": 0.1,
            "position_size": 2.0,
            "stop_loss": 0.01,
            "take_profit": 0.02,
            "time_stop_bars": 12,
            "daily_loss_limit": 0.05,
        },
    )
    result = ThresholdIntradayStrategy().generate_actions(context)
    assert len(result.actions.index) == 4
    assert result.actions["action"].tolist() == [
        TradeAction.ENTER_LONG.value,
        TradeAction.EXIT.value,
        TradeAction.ENTER_SHORT.value,
        TradeAction.HOLD.value,
    ]
    assert float(result.actions["size"].iloc[0]) == pytest.approx(2.0)


def test_threshold_intraday_strategy_rejects_exit_threshold_gt_entry() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)],
            "symbol": ["BTCUSDT"],
            "value": [0.2],
        }
    )
    context = StrategyContext(
        as_of_time=datetime(2026, 3, 20, 0, 5, tzinfo=timezone.utc),
        universe=("BTCUSDT",),
        inputs={"features": frame},
        params={"entry_threshold": 0.1, "exit_threshold": 0.2},
    )
    with pytest.raises(ValueError, match="exit_threshold must be <="):
        ThresholdIntradayStrategy().generate_actions(context)
