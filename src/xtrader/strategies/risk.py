"""Risk controls for action-driven BTC intraday strategies."""

from __future__ import annotations

from dataclasses import dataclass

from xtrader.strategies.state_machine import PositionState


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """Configurable risk thresholds."""

    stop_loss: float | None = None
    take_profit: float | None = None
    time_stop_bars: int | None = None
    daily_loss_limit: float | None = None

    def validate(self) -> None:
        if self.stop_loss is not None and self.stop_loss <= 0.0:
            raise ValueError("stop_loss must be > 0")
        if self.take_profit is not None and self.take_profit <= 0.0:
            raise ValueError("take_profit must be > 0")
        if self.time_stop_bars is not None and self.time_stop_bars <= 0:
            raise ValueError("time_stop_bars must be > 0")
        if self.daily_loss_limit is not None and self.daily_loss_limit <= 0.0:
            raise ValueError("daily_loss_limit must be > 0")


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    """Result returned by risk manager checks."""

    should_exit: bool
    reason: str | None
    unrealized_return: float | None


class RiskManager:
    """Evaluate exit conditions for an open position."""

    def __init__(self, config: RiskConfig) -> None:
        config.validate()
        self._config = config

    @property
    def config(self) -> RiskConfig:
        return self._config

    def evaluate_position(
        self,
        *,
        state: PositionState,
        entry_price: float | None,
        current_price: float,
        bars_in_position: int,
        intraday_realized_pnl: float | None = None,
    ) -> RiskCheckResult:
        if state is PositionState.FLAT:
            return RiskCheckResult(should_exit=False, reason=None, unrealized_return=None)
        if entry_price is None:
            raise ValueError("entry_price must be provided when state is not FLAT")
        if entry_price <= 0.0:
            raise ValueError("entry_price must be > 0")
        if current_price <= 0.0:
            raise ValueError("current_price must be > 0")
        if bars_in_position < 0:
            raise ValueError("bars_in_position must be >= 0")

        unrealized_return = _compute_unrealized_return(
            state=state,
            entry_price=entry_price,
            current_price=current_price,
        )

        if self._config.daily_loss_limit is not None and intraday_realized_pnl is not None:
            if intraday_realized_pnl <= -self._config.daily_loss_limit:
                return RiskCheckResult(
                    should_exit=True,
                    reason="daily_loss_limit",
                    unrealized_return=unrealized_return,
                )

        if self._config.stop_loss is not None and unrealized_return <= -self._config.stop_loss:
            return RiskCheckResult(
                should_exit=True,
                reason="stop_loss",
                unrealized_return=unrealized_return,
            )
        if self._config.take_profit is not None and unrealized_return >= self._config.take_profit:
            return RiskCheckResult(
                should_exit=True,
                reason="take_profit",
                unrealized_return=unrealized_return,
            )
        if self._config.time_stop_bars is not None and bars_in_position >= self._config.time_stop_bars:
            return RiskCheckResult(
                should_exit=True,
                reason="time_stop",
                unrealized_return=unrealized_return,
            )
        return RiskCheckResult(
            should_exit=False,
            reason=None,
            unrealized_return=unrealized_return,
        )


def _compute_unrealized_return(
    *,
    state: PositionState,
    entry_price: float,
    current_price: float,
) -> float:
    if state is PositionState.LONG:
        return (current_price - entry_price) / entry_price
    if state is PositionState.SHORT:
        return (entry_price - current_price) / entry_price
    raise ValueError(f"unsupported position state: {state}")


__all__ = [
    "RiskCheckResult",
    "RiskConfig",
    "RiskManager",
]
