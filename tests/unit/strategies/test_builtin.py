from __future__ import annotations

import xtrader.strategies.builtin as builtin_module
import xtrader.strategies as strategies_module
from xtrader.strategies.builtin import ProfileActionStrategy


def test_builtin_strategy_does_not_export_threshold_intraday() -> None:
    assert not hasattr(builtin_module, "ThresholdIntradayStrategy")


def test_main_entry_does_not_export_threshold_intraday() -> None:
    assert not hasattr(strategies_module, "ThresholdIntradayStrategy")


def test_builtin_strategy_exports_profile_action() -> None:
    strategy = ProfileActionStrategy()
    assert strategy.strategy_id == "five_min_regime_momentum"
