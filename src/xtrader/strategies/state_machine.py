"""Position state transitions for action-driven strategies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from xtrader.strategies.base import TradeAction


class PositionState(str, Enum):
    """Supported position states for single-instrument trading."""

    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """Position snapshot after applying one transition."""

    state: PositionState
    quantity: float
    entry_price: float | None
    entry_time: datetime | None
    bars_in_position: int


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """Transition result details for diagnostics and logging."""

    previous_state: PositionState
    next_state: PositionState
    action: TradeAction
    opened: bool
    closed: bool
    reversed: bool
    reason: str


@dataclass(slots=True)
class PositionStateMachine:
    """State machine handling FLAT/LONG/SHORT transitions."""

    state: PositionState = PositionState.FLAT
    quantity: float = 0.0
    entry_price: float | None = None
    entry_time: datetime | None = None
    bars_in_position: int = 0

    def snapshot(self) -> PositionSnapshot:
        return PositionSnapshot(
            state=self.state,
            quantity=float(self.quantity),
            entry_price=self.entry_price,
            entry_time=self.entry_time,
            bars_in_position=int(self.bars_in_position),
        )

    def advance_bar(self) -> None:
        if self.state is PositionState.FLAT:
            return
        self.bars_in_position += 1

    def apply(
        self,
        action: TradeAction | str,
        *,
        timestamp: datetime,
        price: float,
        size: float = 1.0,
        reason: str = "",
    ) -> TransitionResult:
        action_value = _coerce_action(action)
        if price <= 0.0:
            raise ValueError("price must be > 0")
        if size <= 0.0:
            raise ValueError("size must be > 0")

        previous_state = self.state
        opened = False
        closed = False
        reversed_pos = False
        final_reason = reason

        if action_value is TradeAction.HOLD:
            if not final_reason:
                final_reason = "hold"
            return TransitionResult(
                previous_state=previous_state,
                next_state=self.state,
                action=action_value,
                opened=opened,
                closed=closed,
                reversed=reversed_pos,
                reason=final_reason,
            )

        if self.state is PositionState.FLAT:
            if action_value is TradeAction.EXIT:
                if not final_reason:
                    final_reason = "already_flat"
            elif action_value is TradeAction.ENTER_LONG:
                self._open_long(timestamp=timestamp, price=float(price), size=float(size))
                opened = True
                if not final_reason:
                    final_reason = "enter_long"
            elif action_value is TradeAction.ENTER_SHORT:
                self._open_short(timestamp=timestamp, price=float(price), size=float(size))
                opened = True
                if not final_reason:
                    final_reason = "enter_short"
            elif action_value is TradeAction.REVERSE:
                raise ValueError("cannot REVERSE when state is FLAT")
            else:
                raise ValueError(f"unsupported action for FLAT state: {action_value.value}")
        elif self.state is PositionState.LONG:
            if action_value in (TradeAction.EXIT,):
                self._close()
                closed = True
                if not final_reason:
                    final_reason = "exit_long"
            elif action_value in (TradeAction.ENTER_SHORT, TradeAction.REVERSE):
                self._open_short(timestamp=timestamp, price=float(price), size=float(size))
                closed = True
                opened = True
                reversed_pos = True
                if not final_reason:
                    final_reason = "reverse_to_short"
            elif action_value is TradeAction.ENTER_LONG:
                raise ValueError("cannot ENTER_LONG when state is LONG")
            else:
                raise ValueError(f"unsupported action for LONG state: {action_value.value}")
        elif self.state is PositionState.SHORT:
            if action_value in (TradeAction.EXIT,):
                self._close()
                closed = True
                if not final_reason:
                    final_reason = "exit_short"
            elif action_value in (TradeAction.ENTER_LONG, TradeAction.REVERSE):
                self._open_long(timestamp=timestamp, price=float(price), size=float(size))
                closed = True
                opened = True
                reversed_pos = True
                if not final_reason:
                    final_reason = "reverse_to_long"
            elif action_value is TradeAction.ENTER_SHORT:
                raise ValueError("cannot ENTER_SHORT when state is SHORT")
            else:
                raise ValueError(f"unsupported action for SHORT state: {action_value.value}")
        else:
            raise ValueError(f"unsupported current state: {self.state}")

        return TransitionResult(
            previous_state=previous_state,
            next_state=self.state,
            action=action_value,
            opened=opened,
            closed=closed,
            reversed=reversed_pos,
            reason=final_reason,
        )

    def _open_long(self, *, timestamp: datetime, price: float, size: float) -> None:
        self.state = PositionState.LONG
        self.entry_time = timestamp
        self.entry_price = price
        self.quantity = abs(size)
        self.bars_in_position = 0

    def _open_short(self, *, timestamp: datetime, price: float, size: float) -> None:
        self.state = PositionState.SHORT
        self.entry_time = timestamp
        self.entry_price = price
        self.quantity = abs(size)
        self.bars_in_position = 0

    def _close(self) -> None:
        self.state = PositionState.FLAT
        self.entry_time = None
        self.entry_price = None
        self.quantity = 0.0
        self.bars_in_position = 0


def _coerce_action(action: TradeAction | str) -> TradeAction:
    if isinstance(action, TradeAction):
        return action
    try:
        return TradeAction(str(action))
    except ValueError as exc:
        raise ValueError(f"unsupported action value: {action}") from exc


__all__ = [
    "PositionSnapshot",
    "PositionState",
    "PositionStateMachine",
    "TransitionResult",
]
