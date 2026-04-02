from __future__ import annotations

from datetime import datetime, timezone

import pytest

from xtrader.strategies import PositionState, PositionStateMachine, TradeAction


def test_state_machine_enter_hold_exit_flow() -> None:
    machine = PositionStateMachine()
    now = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    enter = machine.apply(
        TradeAction.ENTER_LONG,
        timestamp=now,
        price=100.0,
        size=0.5,
    )
    assert enter.previous_state is PositionState.FLAT
    assert enter.next_state is PositionState.LONG
    assert enter.opened is True
    assert machine.state is PositionState.LONG
    assert machine.quantity == pytest.approx(0.5)
    assert machine.entry_price == pytest.approx(100.0)

    machine.advance_bar()
    assert machine.bars_in_position == 1

    hold = machine.apply(
        TradeAction.HOLD,
        timestamp=now,
        price=101.0,
    )
    assert hold.next_state is PositionState.LONG
    assert hold.opened is False
    assert hold.closed is False

    exit_result = machine.apply(
        TradeAction.EXIT,
        timestamp=now,
        price=101.0,
    )
    assert exit_result.previous_state is PositionState.LONG
    assert exit_result.next_state is PositionState.FLAT
    assert exit_result.closed is True
    assert machine.state is PositionState.FLAT
    assert machine.entry_price is None
    assert machine.quantity == 0.0


def test_state_machine_reverse_long_to_short() -> None:
    machine = PositionStateMachine()
    now = datetime(2026, 3, 20, 0, 5, tzinfo=timezone.utc)
    machine.apply(TradeAction.ENTER_LONG, timestamp=now, price=100.0, size=1.0)
    transition = machine.apply(TradeAction.REVERSE, timestamp=now, price=99.5, size=0.8)
    assert transition.reversed is True
    assert transition.closed is True
    assert transition.opened is True
    assert machine.state is PositionState.SHORT
    assert machine.quantity == pytest.approx(0.8)
    assert machine.entry_price == pytest.approx(99.5)


def test_state_machine_rejects_reverse_from_flat() -> None:
    machine = PositionStateMachine()
    now = datetime(2026, 3, 20, 0, 10, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="cannot REVERSE"):
        machine.apply(TradeAction.REVERSE, timestamp=now, price=100.0)


def test_state_machine_rejects_duplicate_entry_direction() -> None:
    machine = PositionStateMachine()
    now = datetime(2026, 3, 20, 0, 10, tzinfo=timezone.utc)
    machine.apply(TradeAction.ENTER_SHORT, timestamp=now, price=100.0, size=1.0)
    with pytest.raises(ValueError, match="cannot ENTER_SHORT"):
        machine.apply(TradeAction.ENTER_SHORT, timestamp=now, price=99.0, size=1.0)
