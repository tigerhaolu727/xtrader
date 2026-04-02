from __future__ import annotations

import pytest

from xtrader.strategies import PositionState, RiskConfig, RiskManager


def test_risk_manager_triggers_stop_loss_for_long() -> None:
    manager = RiskManager(RiskConfig(stop_loss=0.01))
    result = manager.evaluate_position(
        state=PositionState.LONG,
        entry_price=100.0,
        current_price=98.8,
        bars_in_position=3,
    )
    assert result.should_exit is True
    assert result.reason == "stop_loss"
    assert result.unrealized_return == pytest.approx(-0.012)


def test_risk_manager_triggers_take_profit_for_short() -> None:
    manager = RiskManager(RiskConfig(take_profit=0.015))
    result = manager.evaluate_position(
        state=PositionState.SHORT,
        entry_price=100.0,
        current_price=98.4,
        bars_in_position=2,
    )
    assert result.should_exit is True
    assert result.reason == "take_profit"
    assert result.unrealized_return == pytest.approx(0.016)


def test_risk_manager_triggers_time_stop() -> None:
    manager = RiskManager(RiskConfig(time_stop_bars=5))
    result = manager.evaluate_position(
        state=PositionState.LONG,
        entry_price=100.0,
        current_price=100.3,
        bars_in_position=5,
    )
    assert result.should_exit is True
    assert result.reason == "time_stop"


def test_risk_manager_triggers_daily_loss_limit() -> None:
    manager = RiskManager(RiskConfig(stop_loss=0.01, daily_loss_limit=0.02))
    result = manager.evaluate_position(
        state=PositionState.LONG,
        entry_price=100.0,
        current_price=99.8,
        bars_in_position=1,
        intraday_realized_pnl=-0.021,
    )
    assert result.should_exit is True
    assert result.reason == "daily_loss_limit"


def test_risk_manager_flat_state_never_exits() -> None:
    manager = RiskManager(RiskConfig(stop_loss=0.01))
    result = manager.evaluate_position(
        state=PositionState.FLAT,
        entry_price=None,
        current_price=100.0,
        bars_in_position=0,
    )
    assert result.should_exit is False
    assert result.reason is None
    assert result.unrealized_return is None


def test_risk_config_validation() -> None:
    with pytest.raises(ValueError, match="stop_loss must be > 0"):
        RiskConfig(stop_loss=0.0).validate()
    with pytest.raises(ValueError, match="take_profit must be > 0"):
        RiskConfig(take_profit=-0.01).validate()
    with pytest.raises(ValueError, match="time_stop_bars must be > 0"):
        RiskConfig(time_stop_bars=0).validate()
    with pytest.raises(ValueError, match="daily_loss_limit must be > 0"):
        RiskConfig(daily_loss_limit=0.0).validate()
