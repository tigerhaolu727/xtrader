"""Event-driven single-symbol backtesting for action strategies."""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from xtrader.strategies import PositionState, PositionStateMachine, RiskConfig, RiskManager, TradeAction


@dataclass(frozen=True, slots=True)
class EventDrivenBacktestConfig:
    """Execution and cost config for event-driven backtests."""

    symbol: str = "BTCUSDT"
    interval_ms: int = 300_000
    execution_lag_bars: int = 1
    taker_fee_bps: float = 6.0
    maker_fee_bps: float = 2.0
    slippage_bps: float = 0.0
    initial_equity: float = 1.0
    default_stop_loss: float | None = 0.01
    default_take_profit: float | None = 0.02
    default_time_stop_bars: int | None = 24
    default_daily_loss_limit: float | None = 0.03


@dataclass(frozen=True, slots=True)
class EventDrivenBacktestSummary:
    """Summary metrics for one event-driven run."""

    sample_count: int
    trade_count: int
    skipped_signal_count: int
    net_return: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    expectancy: float
    total_fee_cost: float
    total_slippage_cost: float
    total_funding_cost: float


@dataclass(frozen=True, slots=True)
class EventDrivenBacktestResult:
    """Backtest outputs: trade ledger, equity curve, and summary."""

    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    summary: EventDrivenBacktestSummary
    diagnostics: dict[str, Any]
    price_input_snapshot: pd.DataFrame = field(default_factory=pd.DataFrame)
    action_input_snapshot: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass(slots=True)
class _OpenPosition:
    symbol: str
    side: PositionState
    quantity: float
    entry_time: datetime
    entry_mark_price: float
    entry_fill_price: float
    entry_fee_cost: float
    entry_slippage_cost: float
    funding_cost: float
    stop_loss: float | None
    take_profit: float | None
    time_stop_bars: int | None
    daily_loss_limit: float | None
    entry_reason: str


def run_event_driven_backtest(
    *,
    actions: pd.DataFrame,
    price_frame: pd.DataFrame,
    config: EventDrivenBacktestConfig,
) -> EventDrivenBacktestResult:
    """Run single-symbol event-driven backtest with action and risk handling."""
    _validate_config(config)
    symbol = str(config.symbol).upper()
    prices = _prepare_prices(price_frame=price_frame, symbol=symbol)
    scheduled, action_snapshot = _prepare_scheduled_actions(actions=actions, symbol=symbol, config=config)
    executed_execution_times: set[pd.Timestamp] = set()
    price_timestamps = pd.to_datetime(prices["timestamp"], utc=True, errors="coerce").dropna()
    action_snapshot, skipped_signal_count = _finalize_action_snapshot(
        action_snapshot=action_snapshot,
        executed_execution_times=executed_execution_times,
        price_timestamps=price_timestamps,
    )
    if prices.empty:
        summary = EventDrivenBacktestSummary(
            sample_count=0,
            trade_count=0,
            skipped_signal_count=int(skipped_signal_count),
            net_return=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            expectancy=0.0,
            total_fee_cost=0.0,
            total_slippage_cost=0.0,
            total_funding_cost=0.0,
        )
        return EventDrivenBacktestResult(
            trades=pd.DataFrame(columns=_trade_columns()),
            equity_curve=pd.DataFrame(columns=["timestamp", "equity"]),
            summary=summary,
            diagnostics={
                "scheduled_actions": int(len(scheduled)),
                "skipped_signals": int(skipped_signal_count),
            },
            price_input_snapshot=prices.copy(),
            action_input_snapshot=action_snapshot.copy(),
        )

    fee_rate = float(config.taker_fee_bps) / 10_000.0
    slip_rate = float(config.slippage_bps) / 10_000.0
    machine = PositionStateMachine()
    open_position: _OpenPosition | None = None
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    equity = float(config.initial_equity)
    daily_realized: dict[date, float] = {}
    forced_risk_exits = 0

    for row in prices.itertuples(index=False):
        timestamp = row.timestamp
        mark_price = float(row.close)
        execution_price = float(row.open)
        funding_rate = float(getattr(row, "funding_rate", 0.0))
        day_key = timestamp.date()
        intraday_realized = float(daily_realized.get(day_key, 0.0))

        if machine.state is not PositionState.FLAT and open_position is not None:
            machine.advance_bar()
            direction = 1.0 if machine.state is PositionState.LONG else -1.0
            open_position.funding_cost += direction * open_position.quantity * mark_price * funding_rate
            risk_result = _evaluate_risk(
                machine=machine,
                open_position=open_position,
                mark_price=mark_price,
                intraday_realized=intraday_realized,
            )
            if risk_result is not None:
                forced_risk_exits += 1
                open_position, closed_trade = _apply_action(
                    machine=machine,
                    open_position=open_position,
                    action=TradeAction.EXIT,
                    symbol=symbol,
                    timestamp=timestamp,
                    mark_price=mark_price,
                    size=machine.quantity or 1.0,
                    reason=risk_result,
                    fee_rate=fee_rate,
                    slip_rate=slip_rate,
                    stop_loss=None,
                    take_profit=None,
                    time_stop_bars=None,
                    daily_loss_limit=None,
                )
                if closed_trade is not None:
                    trade_rows.append(closed_trade)
                    realized = float(closed_trade["net_pnl"])
                    equity += realized
                    daily_realized[day_key] = float(daily_realized.get(day_key, 0.0)) + realized

        action_row = scheduled.get(timestamp)
        if action_row is not None:
            executed_execution_times.add(pd.Timestamp(timestamp))
            open_position, closed_trade = _apply_action(
                machine=machine,
                open_position=open_position,
                action=TradeAction(str(action_row["action"])),
                symbol=symbol,
                timestamp=timestamp,
                mark_price=execution_price,
                size=float(action_row["size"]),
                reason=str(action_row["reason"]),
                fee_rate=fee_rate,
                slip_rate=slip_rate,
                stop_loss=_coalesce_float(action_row.get("stop_loss"), config.default_stop_loss),
                take_profit=_coalesce_float(action_row.get("take_profit"), config.default_take_profit),
                time_stop_bars=_coalesce_int(action_row.get("time_stop_bars"), config.default_time_stop_bars),
                daily_loss_limit=_coalesce_float(action_row.get("daily_loss_limit"), config.default_daily_loss_limit),
            )
            if closed_trade is not None:
                trade_rows.append(closed_trade)
                realized = float(closed_trade["net_pnl"])
                equity += realized
                daily_realized[day_key] = float(daily_realized.get(day_key, 0.0)) + realized

        equity_rows.append({"timestamp": timestamp, "equity": equity})

    if machine.state is not PositionState.FLAT and open_position is not None:
        last = prices.iloc[-1]
        close_ts = pd.Timestamp(last["timestamp"])
        close_mark = float(last["close"])
        open_position, closed_trade = _apply_action(
            machine=machine,
            open_position=open_position,
            action=TradeAction.EXIT,
            symbol=symbol,
            timestamp=close_ts,
            mark_price=close_mark,
            size=machine.quantity or 1.0,
            reason="end_of_test",
            fee_rate=fee_rate,
            slip_rate=slip_rate,
            stop_loss=None,
            take_profit=None,
            time_stop_bars=None,
            daily_loss_limit=None,
        )
        if closed_trade is not None:
            trade_rows.append(closed_trade)
            equity += float(closed_trade["net_pnl"])
            equity_rows.append({"timestamp": close_ts, "equity": equity})

    trades = pd.DataFrame(trade_rows, columns=_trade_columns())
    equity_curve = pd.DataFrame(equity_rows, columns=["timestamp", "equity"])
    action_snapshot, skipped_signal_count = _finalize_action_snapshot(
        action_snapshot=action_snapshot,
        executed_execution_times=executed_execution_times,
        price_timestamps=price_timestamps,
    )
    summary = _build_summary(
        trades=trades,
        equity_curve=equity_curve,
        initial_equity=float(config.initial_equity),
        skipped_signal_count=int(skipped_signal_count),
    )
    _validate_result_consistency(
        trades=trades,
        summary=summary,
        action_snapshot=action_snapshot,
        diagnostics={
            "scheduled_actions": int(len(scheduled)),
            "forced_risk_exits": int(forced_risk_exits),
            "skipped_signals": int(skipped_signal_count),
        },
    )
    return EventDrivenBacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        summary=summary,
        diagnostics={
            "scheduled_actions": int(len(scheduled)),
            "forced_risk_exits": int(forced_risk_exits),
            "skipped_signals": int(skipped_signal_count),
        },
        price_input_snapshot=prices.copy(),
        action_input_snapshot=action_snapshot.copy(),
    )


def _validate_config(config: EventDrivenBacktestConfig) -> None:
    if config.interval_ms <= 0:
        raise ValueError("interval_ms must be > 0")
    if config.execution_lag_bars < 1:
        raise ValueError("execution_lag_bars must be >= 1")
    if config.taker_fee_bps < 0.0:
        raise ValueError("taker_fee_bps must be >= 0")
    if config.maker_fee_bps < 0.0:
        raise ValueError("maker_fee_bps must be >= 0")
    if config.slippage_bps < 0.0:
        raise ValueError("slippage_bps must be >= 0")
    if config.initial_equity <= 0.0:
        raise ValueError("initial_equity must be > 0")


def _prepare_prices(*, price_frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = {"timestamp", "symbol", "close"}
    if not required.issubset(price_frame.columns):
        missing = ", ".join(sorted(required.difference(price_frame.columns)))
        raise ValueError(f"price_frame missing required columns: {missing}")
    prices = price_frame.copy()
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], utc=True, errors="coerce")
    prices["symbol"] = prices["symbol"].astype(str).str.upper()
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    for optional in ("open", "high", "low"):
        if optional in prices.columns:
            prices[optional] = pd.to_numeric(prices[optional], errors="coerce")
        else:
            prices[optional] = np.nan
    prices["open"] = prices["open"].fillna(prices["close"])
    prices["high"] = prices["high"].fillna(prices[["open", "close"]].max(axis=1))
    prices["low"] = prices["low"].fillna(prices[["open", "close"]].min(axis=1))
    prices["high"] = prices[["high", "open", "close"]].max(axis=1)
    prices["low"] = prices[["low", "open", "close"]].min(axis=1)
    if "funding_rate" in prices.columns:
        prices["funding_rate"] = pd.to_numeric(prices["funding_rate"], errors="coerce").fillna(0.0)
    else:
        prices["funding_rate"] = 0.0
    prices = (
        prices[(prices["symbol"] == symbol)]
        .dropna(subset=["timestamp", "close", "open", "high", "low"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    return prices[["timestamp", "symbol", "open", "high", "low", "close", "funding_rate"]]


def _prepare_scheduled_actions(
    *,
    actions: pd.DataFrame,
    symbol: str,
    config: EventDrivenBacktestConfig,
) -> tuple[dict[pd.Timestamp, dict[str, Any]], pd.DataFrame]:
    snapshot_columns = [
        "signal_time",
        "execution_time",
        "symbol",
        "action",
        "size",
        "stop_loss",
        "take_profit",
        "time_stop_bars",
        "daily_loss_limit",
        "reason",
        "status",
        "skip_reason",
    ]
    if actions.empty:
        return {}, pd.DataFrame(columns=snapshot_columns)
    required = {"timestamp", "symbol", "action", "size", "stop_loss", "take_profit", "reason"}
    if not required.issubset(actions.columns):
        missing = ", ".join(sorted(required.difference(actions.columns)))
        raise ValueError(f"actions missing required columns: {missing}")
    frame = actions.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["action"] = frame["action"].astype(str)
    frame["size"] = pd.to_numeric(frame["size"], errors="coerce")
    frame["stop_loss"] = pd.to_numeric(frame["stop_loss"], errors="coerce")
    frame["take_profit"] = pd.to_numeric(frame["take_profit"], errors="coerce")
    frame["reason"] = frame["reason"].astype(str)
    for optional in ("time_stop_bars", "daily_loss_limit"):
        if optional in frame.columns:
            frame[optional] = pd.to_numeric(frame[optional], errors="coerce")
        else:
            frame[optional] = np.nan
    frame = frame[(frame["symbol"] == symbol)].dropna(subset=["timestamp", "size"]).copy()
    frame["signal_time"] = frame["timestamp"]
    frame["execution_time"] = frame["timestamp"] + pd.to_timedelta(config.execution_lag_bars * config.interval_ms, unit="ms")
    frame = frame.sort_values(["execution_time", "timestamp"]).drop_duplicates(subset=["execution_time"], keep="last")
    scheduled: dict[pd.Timestamp, dict[str, Any]] = {}
    snapshot_rows: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        payload = {
            "action": row.action,
            "size": float(row.size),
            "stop_loss": float(row.stop_loss) if pd.notna(row.stop_loss) else None,
            "take_profit": float(row.take_profit) if pd.notna(row.take_profit) else None,
            "time_stop_bars": int(row.time_stop_bars) if pd.notna(row.time_stop_bars) else None,
            "daily_loss_limit": float(row.daily_loss_limit) if pd.notna(row.daily_loss_limit) else None,
            "reason": row.reason,
        }
        execution_time = pd.Timestamp(row.execution_time)
        scheduled[execution_time] = payload
        snapshot_rows.append(
            {
                "signal_time": pd.Timestamp(row.signal_time),
                "execution_time": execution_time,
                "symbol": str(row.symbol),
                "action": str(payload["action"]),
                "size": float(payload["size"]),
                "stop_loss": payload["stop_loss"],
                "take_profit": payload["take_profit"],
                "time_stop_bars": payload["time_stop_bars"],
                "daily_loss_limit": payload["daily_loss_limit"],
                "reason": str(payload["reason"]),
                "status": "PENDING",
                "skip_reason": None,
            }
        )
    snapshot_frame = pd.DataFrame(snapshot_rows, columns=snapshot_columns)
    return scheduled, snapshot_frame


def _finalize_action_snapshot(
    *,
    action_snapshot: pd.DataFrame,
    executed_execution_times: set[pd.Timestamp],
    price_timestamps: pd.Series,
) -> tuple[pd.DataFrame, int]:
    frame = action_snapshot.copy()
    if frame.empty:
        return frame, 0
    frame["signal_time"] = pd.to_datetime(frame["signal_time"], utc=True, errors="coerce")
    frame["execution_time"] = pd.to_datetime(frame["execution_time"], utc=True, errors="coerce")
    executed = {pd.Timestamp(item) for item in executed_execution_times}
    min_exec = pd.Timestamp(price_timestamps.iloc[0]) if not price_timestamps.empty else None
    max_exec = pd.Timestamp(price_timestamps.iloc[-1]) if not price_timestamps.empty else None

    statuses: list[str] = []
    reasons: list[str | None] = []
    for row in frame.itertuples(index=False):
        exec_time = pd.Timestamp(getattr(row, "execution_time"))
        if pd.isna(exec_time):
            statuses.append("SKIPPED")
            reasons.append("DATA_GAP")
            continue
        if exec_time in executed:
            statuses.append("FILLED")
            reasons.append(None)
            continue
        statuses.append("SKIPPED")
        reasons.append(_classify_skip_reason(exec_time=exec_time, min_exec=min_exec, max_exec=max_exec))

    frame["status"] = statuses
    frame["skip_reason"] = reasons
    skipped_signal_count = int((frame["status"] == "SKIPPED").sum())
    return frame, skipped_signal_count


def _classify_skip_reason(*, exec_time: pd.Timestamp, min_exec: pd.Timestamp | None, max_exec: pd.Timestamp | None) -> str:
    if min_exec is None or max_exec is None:
        return "NO_NEXT_BAR"
    if exec_time > max_exec:
        return "NO_NEXT_BAR"
    if exec_time < min_exec:
        return "MARKET_CLOSED"
    return "DATA_GAP"


def _evaluate_risk(
    *,
    machine: PositionStateMachine,
    open_position: _OpenPosition,
    mark_price: float,
    intraday_realized: float,
) -> str | None:
    config = RiskConfig(
        stop_loss=open_position.stop_loss,
        take_profit=open_position.take_profit,
        time_stop_bars=open_position.time_stop_bars,
        daily_loss_limit=open_position.daily_loss_limit,
    )
    manager = RiskManager(config=config)
    result = manager.evaluate_position(
        state=machine.state,
        entry_price=machine.entry_price,
        current_price=mark_price,
        bars_in_position=machine.bars_in_position,
        intraday_realized_pnl=intraday_realized,
    )
    if result.should_exit:
        return str(result.reason)
    return None


def _apply_action(
    *,
    machine: PositionStateMachine,
    open_position: _OpenPosition | None,
    action: TradeAction,
    symbol: str,
    timestamp: pd.Timestamp,
    mark_price: float,
    size: float,
    reason: str,
    fee_rate: float,
    slip_rate: float,
    stop_loss: float | None,
    take_profit: float | None,
    time_stop_bars: int | None,
    daily_loss_limit: float | None,
) -> tuple[_OpenPosition | None, dict[str, Any] | None]:
    prev = machine.snapshot()
    normalized_action = _normalize_action_for_state(action=action, state=prev.state)
    if normalized_action is TradeAction.HOLD:
        return open_position, None
    fill_price = _resolve_fill_price(
        mark_price=mark_price,
        action=normalized_action,
        state=prev.state,
        slippage_rate=slip_rate,
    )
    transition = machine.apply(
        normalized_action,
        timestamp=timestamp.to_pydatetime(),
        price=fill_price,
        size=max(float(size), 1e-12),
        reason=reason,
    )

    closed_trade: dict[str, Any] | None = None
    if transition.closed and open_position is not None:
        exit_quantity = float(prev.quantity)
        exit_fee = exit_quantity * fill_price * fee_rate
        exit_slippage_cost = abs(fill_price - mark_price) * exit_quantity
        gross_pnl = _compute_gross_pnl(
            state=prev.state,
            entry_mark_price=open_position.entry_mark_price,
            exit_mark_price=mark_price,
            quantity=exit_quantity,
        )
        fee_cost = open_position.entry_fee_cost + exit_fee
        slippage_cost = open_position.entry_slippage_cost + exit_slippage_cost
        funding_cost = open_position.funding_cost
        net_pnl = gross_pnl - fee_cost - slippage_cost - funding_cost
        closed_trade = {
            "symbol": open_position.symbol,
            "side": prev.state.value,
            "quantity": exit_quantity,
            "entry_time": pd.Timestamp(open_position.entry_time),
            "exit_time": timestamp,
            "entry_price": float(open_position.entry_fill_price),
            "exit_price": float(fill_price),
            "entry_mark_price": float(open_position.entry_mark_price),
            "exit_mark_price": float(mark_price),
            "gross_pnl": float(gross_pnl),
            "fee_cost": float(fee_cost),
            "slippage_cost": float(slippage_cost),
            "funding_cost": float(funding_cost),
            "net_pnl": float(net_pnl),
            "holding_bars": int(prev.bars_in_position),
            "exit_reason": str(transition.reason),
        }
        open_position = None

    if transition.opened:
        open_quantity = float(machine.quantity)
        entry_fee = open_quantity * fill_price * fee_rate
        entry_slippage_cost = abs(fill_price - mark_price) * open_quantity
        open_position = _OpenPosition(
            symbol=symbol,
            side=machine.state,
            quantity=open_quantity,
            entry_time=timestamp.to_pydatetime(),
            entry_mark_price=mark_price,
            entry_fill_price=fill_price,
            entry_fee_cost=entry_fee,
            entry_slippage_cost=entry_slippage_cost,
            funding_cost=0.0,
            stop_loss=stop_loss,
            take_profit=take_profit,
            time_stop_bars=time_stop_bars,
            daily_loss_limit=daily_loss_limit,
            entry_reason=str(reason),
        )
    return open_position, closed_trade


def _resolve_fill_price(
    *,
    mark_price: float,
    action: TradeAction,
    state: PositionState,
    slippage_rate: float,
) -> float:
    if mark_price <= 0.0:
        raise ValueError("mark_price must be > 0")
    if action is TradeAction.ENTER_LONG:
        return mark_price * (1.0 + slippage_rate)
    if action is TradeAction.ENTER_SHORT:
        return mark_price * (1.0 - slippage_rate)
    if action is TradeAction.EXIT:
        if state is PositionState.LONG:
            return mark_price * (1.0 - slippage_rate)
        if state is PositionState.SHORT:
            return mark_price * (1.0 + slippage_rate)
        return mark_price
    if action is TradeAction.REVERSE:
        if state is PositionState.LONG:
            return mark_price * (1.0 - slippage_rate)
        if state is PositionState.SHORT:
            return mark_price * (1.0 + slippage_rate)
        return mark_price
    return mark_price


def _normalize_action_for_state(*, action: TradeAction, state: PositionState) -> TradeAction:
    if action is TradeAction.HOLD:
        return TradeAction.HOLD
    if state is PositionState.FLAT and action is TradeAction.REVERSE:
        return TradeAction.HOLD
    if state is PositionState.LONG and action is TradeAction.ENTER_LONG:
        return TradeAction.HOLD
    if state is PositionState.SHORT and action is TradeAction.ENTER_SHORT:
        return TradeAction.HOLD
    return action


def _compute_gross_pnl(
    *,
    state: PositionState,
    entry_mark_price: float,
    exit_mark_price: float,
    quantity: float,
) -> float:
    if state is PositionState.LONG:
        return (exit_mark_price - entry_mark_price) * quantity
    if state is PositionState.SHORT:
        return (entry_mark_price - exit_mark_price) * quantity
    return 0.0


def _build_summary(
    *,
    trades: pd.DataFrame,
    equity_curve: pd.DataFrame,
    initial_equity: float,
    skipped_signal_count: int = 0,
) -> EventDrivenBacktestSummary:
    trade_count = int(len(trades.index))
    if equity_curve.empty:
        equity_final = initial_equity
        max_drawdown = 0.0
    else:
        equity_series = equity_curve["equity"].astype(float)
        equity_final = float(equity_series.iloc[-1])
        peak = equity_series.cummax()
        drawdown = equity_series / peak - 1.0
        max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

    if trade_count == 0:
        return EventDrivenBacktestSummary(
            sample_count=int(len(equity_curve.index)),
            trade_count=0,
            skipped_signal_count=int(skipped_signal_count),
            net_return=(equity_final / initial_equity) - 1.0,
            max_drawdown=max_drawdown,
            win_rate=0.0,
            profit_factor=0.0,
            expectancy=0.0,
            total_fee_cost=0.0,
            total_slippage_cost=0.0,
            total_funding_cost=0.0,
        )

    pnl = trades["net_pnl"].astype(float)
    wins = pnl[pnl > 0.0]
    losses = pnl[pnl < 0.0]
    gross_profit = float(wins.sum()) if not wins.empty else 0.0
    gross_loss = float(-losses.sum()) if not losses.empty else 0.0
    if gross_loss > 0.0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0.0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    return EventDrivenBacktestSummary(
        sample_count=int(len(equity_curve.index)),
        trade_count=trade_count,
        skipped_signal_count=int(skipped_signal_count),
        net_return=(equity_final / initial_equity) - 1.0,
        max_drawdown=max_drawdown,
        win_rate=float((pnl > 0.0).mean()),
        profit_factor=float(profit_factor),
        expectancy=float(pnl.mean()),
        total_fee_cost=float(trades["fee_cost"].sum()),
        total_slippage_cost=float(trades["slippage_cost"].sum()),
        total_funding_cost=float(trades["funding_cost"].sum()),
    )


def _validate_result_consistency(
    *,
    trades: pd.DataFrame,
    summary: EventDrivenBacktestSummary,
    action_snapshot: pd.DataFrame,
    diagnostics: dict[str, Any],
) -> None:
    trade_count = int(len(trades.index))
    if int(summary.trade_count) != trade_count:
        raise ValueError("summary.trade_count does not match trades rows")
    if "status" in action_snapshot.columns:
        skipped_count = int((action_snapshot["status"].astype(str).str.upper() == "SKIPPED").sum())
    else:
        skipped_count = 0
    if int(summary.skipped_signal_count) != skipped_count:
        raise ValueError("summary.skipped_signal_count does not match action snapshot")
    diag_skipped = int(diagnostics.get("skipped_signals", 0))
    if diag_skipped != skipped_count:
        raise ValueError("diagnostics.skipped_signals does not match action snapshot")


def _coalesce_float(value: Any, fallback: float | None) -> float | None:
    if value is None:
        return fallback
    if isinstance(value, float) and np.isnan(value):
        return fallback
    return float(value)


def _coalesce_int(value: Any, fallback: int | None) -> int | None:
    if value is None:
        return fallback
    if isinstance(value, float) and np.isnan(value):
        return fallback
    return int(value)


def _trade_columns() -> list[str]:
    return [
        "symbol",
        "side",
        "quantity",
        "entry_time",
        "exit_time",
        "entry_price",
        "exit_price",
        "entry_mark_price",
        "exit_mark_price",
        "gross_pnl",
        "fee_cost",
        "slippage_cost",
        "funding_cost",
        "net_pnl",
        "holding_bars",
        "exit_reason",
    ]


__all__ = [
    "EventDrivenBacktestConfig",
    "EventDrivenBacktestResult",
    "EventDrivenBacktestSummary",
    "build_strategy_report_root",
    "run_event_driven_backtest",
    "write_event_driven_outputs",
    "write_strategy_event_driven_outputs",
]

_LEDGER_CHUNK_THRESHOLD = 5_000
_LEDGER_CHUNK_FILE_PREFIX = "trades_"
_LEDGER_MANIFEST_FILENAME = "trade_ledger_manifest.json"
_KLINE_OVERVIEW_MAX_BARS = 1_200
_KLINE_TRADE_MARKER_MAX = 1_500
_KLINE_CHART_TRADE_META_MAX = 8_000
_KLINE_EQUITY_META_MAX = 80_000
_KLINE_SIGNAL_META_MAX = 12_000
_KLINE_SVG_FALLBACK_MAX_BARS = 2_000
_TIMELINE_MAX_ROWS = 500
_DASHBOARD_DOJI_SYNTH_THRESHOLD = 0.995
_REPORT_HUB_INDEX_NAME = "report_hub_index.json"
_REPORT_HUB_HTML_NAME = "report_hub.html"
_ECHARTS_LOCAL_FILENAME = "echarts.min.js"
_ECHARTS_LOCAL_VENDOR_PATH = Path(__file__).resolve().parent / "assets" / _ECHARTS_LOCAL_FILENAME
_DEFAULT_STRATEGY_BACKTEST_ROOT = Path("reports/backtests/strategy")
_SNAPSHOT_DIRNAME = "snapshots"
_SNAPSHOT_BASE_DIRNAME = "base"
_SNAPSHOT_RESAMPLED_DIRNAME = "resampled"
_SNAPSHOT_PRICE_FILENAME = "price_5m.parquet"
_SNAPSHOT_ACTION_FILENAME = "action_input.parquet"
_SNAPSHOT_MANIFEST_FILENAME = "snapshot_manifest.json"
_RESAMPLED_MANIFEST_FILENAME = "resampled_manifest.json"
_TIMELINE_DIRNAME = "timelines"
_SIGNAL_EXECUTION_FILENAME = "signal_execution.parquet"
_DECISION_TRACE_FILENAME = "decision_trace.parquet"
_LEDGER_DIRNAME = "ledgers"
_CURVE_DIRNAME = "curves"
_TRADES_PARQUET_FILENAME = "trades.parquet"
_EQUITY_PARQUET_FILENAME = "equity_curve.parquet"
_DIAGNOSTICS_FILENAME = "diagnostics.json"
_RUN_MANIFEST_FILENAME = "run_manifest.json"
_CHUNKSET_MANIFEST_FILENAME = "manifest.json"
_CHUNKSET_PRICE_ROWS = 20_000
_CHUNKSET_TRADE_ROWS = 5_000
_CHUNKSET_EQUITY_ROWS = 20_000
_CHUNKSET_TIMELINE_ROWS = 20_000
_CHUNKSET_DECISION_TRACE_ROWS = 20_000


def _slugify_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug


def _build_strategy_run_id(*, strategy_slug: str, at_time: datetime | None = None, run_suffix: str | None = None) -> str:
    ts = (at_time or datetime.now(tz=timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parts = [ts, strategy_slug]
    if run_suffix is not None and str(run_suffix).strip():
        suffix_slug = _slugify_name(str(run_suffix))
        if suffix_slug:
            parts.append(suffix_slug)
    return "_".join(parts)


def build_strategy_report_root(
    *,
    strategy_name: str,
    report_base: Path | str = _DEFAULT_STRATEGY_BACKTEST_ROOT,
    run_id: str | None = None,
    run_suffix: str | None = None,
    at_time: datetime | None = None,
) -> Path:
    strategy_slug = _slugify_name(strategy_name)
    if not strategy_slug:
        raise ValueError("strategy_name must contain at least one alphanumeric character")
    normalized_run_id = run_id or _build_strategy_run_id(
        strategy_slug=strategy_slug,
        at_time=at_time,
        run_suffix=run_suffix,
    )
    return Path(report_base) / strategy_slug / normalized_run_id


def write_strategy_event_driven_outputs(
    *,
    strategy_name: str,
    config: EventDrivenBacktestConfig,
    result: EventDrivenBacktestResult,
    decision_trace: pd.DataFrame | None = None,
    price_frame: pd.DataFrame | None = None,
    actions: pd.DataFrame | None = None,
    signal_interval_ms: int | None = None,
    resampled_price_frames: dict[str, pd.DataFrame] | None = None,
    report_base: Path | str = _DEFAULT_STRATEGY_BACKTEST_ROOT,
    run_id: str | None = None,
    run_suffix: str | None = None,
    at_time: datetime | None = None,
) -> dict[str, str]:
    report_root = build_strategy_report_root(
        strategy_name=strategy_name,
        report_base=report_base,
        run_id=run_id,
        run_suffix=run_suffix,
        at_time=at_time,
    )
    outputs = write_event_driven_outputs(
        report_root=report_root,
        collection_root=Path(report_base),
        config=config,
        result=result,
        decision_trace=decision_trace,
        price_frame=price_frame,
        actions=actions,
        signal_interval_ms=signal_interval_ms,
        resampled_price_frames=resampled_price_frames,
        strategy_name=strategy_name,
    )
    outputs["report_root"] = str(report_root)
    outputs["strategy_collection_root"] = str(Path(report_base))
    return outputs


def write_event_driven_outputs(
    *,
    report_root: Path,
    collection_root: Path | None = None,
    config: EventDrivenBacktestConfig,
    result: EventDrivenBacktestResult,
    decision_trace: pd.DataFrame | None = None,
    price_frame: pd.DataFrame | None = None,
    actions: pd.DataFrame | None = None,
    signal_interval_ms: int | None = None,
    resampled_price_frames: dict[str, pd.DataFrame] | None = None,
    strategy_name: str | None = None,
) -> dict[str, str]:
    """Persist event-driven backtest artifacts (data only, no UI reports)."""
    report_root.mkdir(parents=True, exist_ok=True)
    summary_path = report_root / "summary.json"
    diagnostics_path = report_root / _DIAGNOSTICS_FILENAME
    ledger_root = report_root / _LEDGER_DIRNAME
    curve_root = report_root / _CURVE_DIRNAME
    timeline_root = report_root / _TIMELINE_DIRNAME
    ledger_root.mkdir(parents=True, exist_ok=True)
    curve_root.mkdir(parents=True, exist_ok=True)
    timeline_root.mkdir(parents=True, exist_ok=True)
    trades_parquet_path = ledger_root / _TRADES_PARQUET_FILENAME
    equity_parquet_path = curve_root / _EQUITY_PARQUET_FILENAME
    timeline_path = timeline_root / _SIGNAL_EXECUTION_FILENAME
    decision_trace_path = timeline_root / _DECISION_TRACE_FILENAME
    run_manifest_path = report_root / _RUN_MANIFEST_FILENAME

    summary_payload = asdict(result.summary)
    summary_payload = {key: _json_safe_value(value) for key, value in summary_payload.items()}
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=True, indent=2), encoding="utf-8")
    diagnostics_payload = {
        "generated_at": _utc_now_iso(),
        "diagnostics": result.diagnostics,
    }
    diagnostics_path.write_text(json.dumps(diagnostics_payload, ensure_ascii=True, indent=2), encoding="utf-8")

    result.trades.to_parquet(trades_parquet_path, index=False)
    result.equity_curve.to_parquet(equity_parquet_path, index=False)
    snapshot_outputs = _write_input_snapshots(
        report_root=report_root,
        result=result,
        resampled_price_frames=resampled_price_frames,
    )
    timeline_outputs = _write_signal_execution_timeline(
        report_root=report_root,
        result=result,
        target_path=timeline_path,
    )
    decision_trace_outputs = _write_decision_trace_timeline(
        report_root=report_root,
        decision_trace=decision_trace,
        action_snapshot=result.action_input_snapshot,
        config=config,
        run_id=str(report_root.name),
        symbol=str(config.symbol),
        target_path=decision_trace_path,
    )
    chunk_outputs = _write_standard_chunk_sets(
        report_root=report_root,
        prices=result.price_input_snapshot,
        trades=result.trades,
        equity_curve=result.equity_curve,
        signal_execution=timeline_outputs["signal_execution_frame"],
        decision_trace=decision_trace_outputs["decision_trace_frame"],
    )
    ledger_manifest_name: str | None = None
    if len(result.trades.index) > _LEDGER_CHUNK_THRESHOLD:
        ledger_manifest_name = _write_trade_ledger_chunks(report_root=report_root, trades=result.trades)

    artifacts = [
        _build_json_artifact(report_root=report_root, path=summary_path, payload=summary_payload),
        _build_json_artifact(report_root=report_root, path=diagnostics_path, payload=diagnostics_payload),
        _build_frame_artifact(
            report_root=report_root,
            path=trades_parquet_path,
            frame=result.trades,
            time_columns=["entry_time", "exit_time"],
        ),
        _build_frame_artifact(
            report_root=report_root,
            path=equity_parquet_path,
            frame=result.equity_curve,
            time_columns=["timestamp"],
        ),
        _build_frame_artifact(
            report_root=report_root,
            path=snapshot_outputs["price_snapshot_path"],
            frame=result.price_input_snapshot,
            time_columns=["timestamp"],
        ),
        _build_frame_artifact(
            report_root=report_root,
            path=snapshot_outputs["action_snapshot_path"],
            frame=result.action_input_snapshot,
            time_columns=["signal_time", "execution_time"],
        ),
        _build_json_artifact(
            report_root=report_root,
            path=snapshot_outputs["snapshot_manifest_path"],
            payload=json.loads(snapshot_outputs["snapshot_manifest_path"].read_text(encoding="utf-8")),
        ),
        _build_json_artifact(
            report_root=report_root,
            path=snapshot_outputs["resampled_manifest_path"],
            payload=json.loads(snapshot_outputs["resampled_manifest_path"].read_text(encoding="utf-8")),
        ),
        _build_frame_artifact(
            report_root=report_root,
            path=timeline_outputs["signal_execution_path"],
            frame=timeline_outputs["signal_execution_frame"],
            time_columns=["signal_time", "execution_time"],
        ),
        _build_frame_artifact(
            report_root=report_root,
            path=decision_trace_outputs["decision_trace_path"],
            frame=decision_trace_outputs["decision_trace_frame"],
            time_columns=["signal_time", "execution_time"],
        ),
    ]
    for chunk_info in chunk_outputs.values():
        artifacts.append(
            _build_json_artifact(
                report_root=report_root,
                path=chunk_info["manifest_path"],
                payload=chunk_info["manifest_payload"],
            )
        )

    run_manifest = _build_run_manifest(
        report_root=report_root,
        strategy_name=strategy_name,
        config=config,
        summary_payload=summary_payload,
        diagnostics_payload=diagnostics_payload,
        artifacts=artifacts,
        base_timeframe="5m",
        resampled_timeframes=list(snapshot_outputs["resampled_paths"].keys()),
        chunk_sets=_build_chunk_sets_manifest_payload(report_root=report_root, chunk_outputs=chunk_outputs),
    )
    if ledger_manifest_name is not None:
        ledger_manifest_path = report_root / ledger_manifest_name
        run_manifest["artifacts"].append(
            _build_json_artifact(
                report_root=report_root,
                path=ledger_manifest_path,
                payload=json.loads(ledger_manifest_path.read_text(encoding="utf-8")),
            )
        )
    run_manifest_path.write_text(json.dumps(run_manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    outputs = {
        "run_manifest_path": str(run_manifest_path),
        "summary_path": str(summary_path),
        "diagnostics_path": str(diagnostics_path),
        "trades_path": str(trades_parquet_path),
        "trades_parquet_path": str(trades_parquet_path),
        "equity_curve_path": str(equity_parquet_path),
        "equity_curve_parquet_path": str(equity_parquet_path),
        "price_snapshot_path": str(snapshot_outputs["price_snapshot_path"]),
        "action_snapshot_path": str(snapshot_outputs["action_snapshot_path"]),
        "snapshot_manifest_path": str(snapshot_outputs["snapshot_manifest_path"]),
        "resampled_manifest_path": str(snapshot_outputs["resampled_manifest_path"]),
        "signal_execution_path": str(timeline_outputs["signal_execution_path"]),
        "decision_trace_path": str(decision_trace_outputs["decision_trace_path"]),
        "price_chunks_manifest_path": str(chunk_outputs["prices"]["manifest_path"]),
        "trades_chunks_manifest_path": str(chunk_outputs["trades"]["manifest_path"]),
        "equity_chunks_manifest_path": str(chunk_outputs["equity"]["manifest_path"]),
        "signal_execution_chunks_manifest_path": str(chunk_outputs["signal_execution"]["manifest_path"]),
        "decision_trace_chunks_manifest_path": str(chunk_outputs["decision_trace"]["manifest_path"]),
    }
    for timeframe, path in snapshot_outputs["resampled_paths"].items():
        outputs[f"resampled_{timeframe}_path"] = str(path)
    if ledger_manifest_name is not None:
        outputs["ledger_manifest_path"] = str(report_root / ledger_manifest_name)
    return outputs


def _copy_local_echarts_asset(*, report_root: Path) -> Path:
    if not _ECHARTS_LOCAL_VENDOR_PATH.exists():
        raise FileNotFoundError(
            f"Missing local ECharts asset at {_ECHARTS_LOCAL_VENDOR_PATH}. "
            "Add vendored echarts.min.js before generating report."
        )
    target = report_root / _ECHARTS_LOCAL_FILENAME
    shutil.copyfile(_ECHARTS_LOCAL_VENDOR_PATH, target)
    return target


def _write_input_snapshots(
    *,
    report_root: Path,
    result: EventDrivenBacktestResult,
    resampled_price_frames: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    snapshot_root = report_root / _SNAPSHOT_DIRNAME
    base_root = snapshot_root / _SNAPSHOT_BASE_DIRNAME
    resampled_root = snapshot_root / _SNAPSHOT_RESAMPLED_DIRNAME
    snapshot_root.mkdir(parents=True, exist_ok=True)
    base_root.mkdir(parents=True, exist_ok=True)
    resampled_root.mkdir(parents=True, exist_ok=True)
    price_path = base_root / _SNAPSHOT_PRICE_FILENAME
    action_path = snapshot_root / _SNAPSHOT_ACTION_FILENAME
    manifest_path = snapshot_root / _SNAPSHOT_MANIFEST_FILENAME
    resampled_manifest_path = resampled_root / _RESAMPLED_MANIFEST_FILENAME

    price_frame = result.price_input_snapshot.copy()
    action_frame = result.action_input_snapshot.copy()
    price_frame.to_parquet(price_path, index=False)
    action_frame.to_parquet(action_path, index=False)

    price_timestamps = (
        pd.to_datetime(price_frame["timestamp"], utc=True, errors="coerce").dropna()
        if ("timestamp" in price_frame.columns and not price_frame.empty)
        else pd.Series(dtype="datetime64[ns, UTC]")
    )
    action_exec_timestamps = (
        pd.to_datetime(action_frame["execution_time"], utc=True, errors="coerce").dropna()
        if ("execution_time" in action_frame.columns and not action_frame.empty)
        else pd.Series(dtype="datetime64[ns, UTC]")
    )
    manifest = {
        "version": "v1",
        "generated_at": _utc_now_iso(),
        "base_timeframe": "5m",
        "files": {
            "price_input": {
                "path": f"{_SNAPSHOT_DIRNAME}/{_SNAPSHOT_BASE_DIRNAME}/{_SNAPSHOT_PRICE_FILENAME}",
                "rows": int(len(price_frame.index)),
                "sha256": _file_sha256(price_path),
                "min_timestamp": price_timestamps.iloc[0].isoformat() if not price_timestamps.empty else None,
                "max_timestamp": price_timestamps.iloc[-1].isoformat() if not price_timestamps.empty else None,
            },
            "action_input": {
                "path": f"{_SNAPSHOT_DIRNAME}/{_SNAPSHOT_ACTION_FILENAME}",
                "rows": int(len(action_frame.index)),
                "sha256": _file_sha256(action_path),
                "min_execution_time": action_exec_timestamps.iloc[0].isoformat() if not action_exec_timestamps.empty else None,
                "max_execution_time": action_exec_timestamps.iloc[-1].isoformat() if not action_exec_timestamps.empty else None,
            },
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    resampled_paths: dict[str, Path] = {}
    resampled_entries: list[dict[str, Any]] = []
    for timeframe, frame in sorted((resampled_price_frames or {}).items(), key=lambda item: str(item[0])):
        tf_slug = _slugify_name(str(timeframe))
        if not tf_slug:
            continue
        target = resampled_root / f"price_{tf_slug}.parquet"
        frame_copy = frame.copy()
        frame_copy.to_parquet(target, index=False)
        time_col = "timestamp" if "timestamp" in frame_copy.columns else None
        ts_values = (
            pd.to_datetime(frame_copy[time_col], utc=True, errors="coerce").dropna()
            if (time_col is not None and not frame_copy.empty)
            else pd.Series(dtype="datetime64[ns, UTC]")
        )
        resampled_paths[tf_slug] = target
        resampled_entries.append(
            {
                "timeframe": str(timeframe),
                "path": f"{_SNAPSHOT_DIRNAME}/{_SNAPSHOT_RESAMPLED_DIRNAME}/{target.name}",
                "rows": int(len(frame_copy.index)),
                "sha256": _file_sha256(target),
                "min_timestamp": ts_values.iloc[0].isoformat() if not ts_values.empty else None,
                "max_timestamp": ts_values.iloc[-1].isoformat() if not ts_values.empty else None,
            }
        )
    resampled_manifest_payload = {
        "version": "v1",
        "generated_at": _utc_now_iso(),
        "source": f"{_SNAPSHOT_DIRNAME}/{_SNAPSHOT_BASE_DIRNAME}/{_SNAPSHOT_PRICE_FILENAME}",
        "base_timeframe": "5m",
        "method": {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "timezone": "UTC",
            "label": "right",
            "closed": "right",
        },
        "frames": resampled_entries,
    }
    resampled_manifest_path.write_text(json.dumps(resampled_manifest_payload, ensure_ascii=True, indent=2), encoding="utf-8")

    return {
        "price_snapshot_path": price_path,
        "action_snapshot_path": action_path,
        "snapshot_manifest_path": manifest_path,
        "resampled_manifest_path": resampled_manifest_path,
        "resampled_paths": resampled_paths,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _write_signal_execution_timeline(
    *,
    report_root: Path,
    result: EventDrivenBacktestResult,
    target_path: Path | None = None,
) -> dict[str, Any]:
    timeline_path = target_path or (report_root / _TIMELINE_DIRNAME / _SIGNAL_EXECUTION_FILENAME)
    timeline_path.parent.mkdir(parents=True, exist_ok=True)
    frame = result.action_input_snapshot.copy()
    required = ["signal_time", "execution_time", "action", "reason"]
    for col in required:
        if col not in frame.columns:
            frame[col] = pd.Series(dtype="object")
    if "symbol" not in frame.columns:
        frame["symbol"] = pd.Series(dtype="object")
    if "status" not in frame.columns:
        frame["status"] = "FILLED"
    if "skip_reason" not in frame.columns:
        frame["skip_reason"] = pd.Series(dtype="object")
    frame = frame[["signal_time", "execution_time", "symbol", "action", "reason", "status", "skip_reason"]].copy()
    frame["signal_time"] = pd.to_datetime(frame["signal_time"], utc=True, errors="coerce")
    frame["execution_time"] = pd.to_datetime(frame["execution_time"], utc=True, errors="coerce")
    frame["status"] = frame["status"].astype(str).str.upper()
    frame["skip_reason"] = frame["skip_reason"].where(frame["skip_reason"].notna(), None)
    frame["lag_ms"] = (
        (frame["execution_time"] - frame["signal_time"]).dt.total_seconds().fillna(0.0) * 1000.0
    ).astype("float64")
    frame = frame.dropna(subset=["signal_time", "execution_time"]).sort_values("signal_time").reset_index(drop=True)
    frame.to_parquet(timeline_path, index=False)
    return {
        "signal_execution_path": timeline_path,
        "signal_execution_frame": frame,
    }


def _normalize_decision_action(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if raw in {"ENTER", "ENTER_LONG", "ENTER_SHORT", "REVERSE"}:
        return "ENTER"
    if raw == "EXIT":
        return "EXIT"
    return "HOLD"


def _json_safe_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe_nested(raw) for key, raw in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_nested(item) for item in value]
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            scalar = value.item()
            if scalar is not value:
                return _json_safe_nested(scalar)
        except Exception:  # pragma: no cover - defensive
            pass
    try:
        if pd.isna(value):
            return None
    except Exception:  # pragma: no cover - defensive
        pass
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return _json_safe_value(float(value))
    return value


def _serialize_json_value(value: Any) -> str | None:
    normalized = _json_safe_nested(value)
    if normalized is None:
        return None
    if isinstance(normalized, str):
        text = normalized.strip()
        if not text:
            return None
        try:
            json.loads(text)
            return text
        except Exception:
            return json.dumps(text, ensure_ascii=True)
    return json.dumps(normalized, ensure_ascii=True)


def _write_decision_trace_timeline(
    *,
    report_root: Path,
    decision_trace: pd.DataFrame | None,
    action_snapshot: pd.DataFrame,
    config: EventDrivenBacktestConfig,
    run_id: str,
    symbol: str,
    target_path: Path | None = None,
) -> dict[str, Any]:
    timeline_path = target_path or (report_root / _TIMELINE_DIRNAME / _DECISION_TRACE_FILENAME)
    timeline_path.parent.mkdir(parents=True, exist_ok=True)
    lag_ms = int(config.execution_lag_bars) * int(config.interval_ms)
    lag_delta = pd.to_timedelta(lag_ms, unit="ms")

    frame = decision_trace.copy(deep=True) if isinstance(decision_trace, pd.DataFrame) else pd.DataFrame()
    if frame.empty:
        frame = action_snapshot.copy(deep=True)
        frame["action_raw"] = frame["action"] if "action" in frame.columns else pd.Series(dtype="object")
        frame["state"] = pd.Series(dtype="object")
        frame["score_total"] = pd.Series(dtype="float64")
        frame["feature_values"] = None
        frame["required_feature_refs"] = None
        frame["required_feature_values"] = None
        frame["rule_results"] = None
        frame["group_scores"] = None
        frame["group_weights"] = None
        frame["signal_decision"] = None
        frame["risk_decision"] = None
        frame["action_result"] = None
        if "reason" not in frame.columns:
            frame["reason"] = pd.Series(dtype="object")
        if "signal_time" not in frame.columns:
            frame["signal_time"] = frame["timestamp"] if "timestamp" in frame.columns else pd.Series(dtype="object")

    if "signal_time" not in frame.columns:
        if "timestamp" in frame.columns:
            frame["signal_time"] = frame["timestamp"]
        elif "execution_time" in frame.columns:
            frame["signal_time"] = pd.to_datetime(frame["execution_time"], utc=True, errors="coerce") - lag_delta
        else:
            frame["signal_time"] = pd.Series(dtype="object")
    if "execution_time" not in frame.columns:
        frame["execution_time"] = pd.to_datetime(frame["signal_time"], utc=True, errors="coerce") + lag_delta
    if "symbol" not in frame.columns:
        frame["symbol"] = symbol
    if "action_raw" not in frame.columns:
        frame["action_raw"] = frame["action"] if "action" in frame.columns else pd.Series(dtype="object")
    if "action" not in frame.columns:
        frame["action"] = frame["action_raw"]
    if "reason" not in frame.columns:
        frame["reason"] = pd.Series(dtype="object")
    if "state" not in frame.columns:
        frame["state"] = pd.Series(dtype="object")
    if "score_total" not in frame.columns:
        frame["score_total"] = pd.Series(dtype="float64")
    frame["run_id"] = str(run_id)
    frame["signal_time"] = pd.to_datetime(frame["signal_time"], utc=True, errors="coerce")
    frame["execution_time"] = pd.to_datetime(frame["execution_time"], utc=True, errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["action_raw"] = frame["action_raw"].astype(str).str.upper()
    frame["action"] = frame["action_raw"].map(_normalize_decision_action)
    frame["reason"] = frame["reason"].astype(str)
    frame["state"] = frame["state"].astype(str)
    frame["score_total"] = pd.to_numeric(frame["score_total"], errors="coerce").astype("float64")

    json_cols_map = {
        "feature_values_json": ("feature_values_json", "feature_values"),
        "required_feature_refs_json": ("required_feature_refs_json", "required_feature_refs"),
        "required_feature_values_json": ("required_feature_values_json", "required_feature_values"),
        "rule_results_json": ("rule_results_json", "rule_results"),
        "group_scores_json": ("group_scores_json", "group_scores"),
        "group_weights_json": ("group_weights_json", "group_weights"),
        "signal_decision_json": ("signal_decision_json", "signal_decision"),
        "risk_decision_json": ("risk_decision_json", "risk_decision"),
        "action_result_json": ("action_result_json", "action_result"),
    }
    for target_col, candidates in json_cols_map.items():
        source_col: str | None = None
        for candidate in candidates:
            if candidate in frame.columns:
                source_col = candidate
                break
        if source_col is None:
            frame[target_col] = None
            continue
        frame[target_col] = frame[source_col].map(_serialize_json_value)

    frame = frame[
        [
            "run_id",
            "symbol",
            "signal_time",
            "execution_time",
            "action",
            "action_raw",
            "reason",
            "state",
            "score_total",
            "feature_values_json",
            "required_feature_refs_json",
            "required_feature_values_json",
            "rule_results_json",
            "group_scores_json",
            "group_weights_json",
            "signal_decision_json",
            "risk_decision_json",
            "action_result_json",
        ]
    ].copy()
    frame = frame.dropna(subset=["signal_time", "execution_time"]).sort_values(
        ["execution_time", "signal_time", "symbol", "action_raw"]
    ).reset_index(drop=True)
    frame.to_parquet(timeline_path, index=False)
    return {
        "decision_trace_path": timeline_path,
        "decision_trace_frame": frame,
    }


def _write_standard_chunk_sets(
    *,
    report_root: Path,
    prices: pd.DataFrame,
    trades: pd.DataFrame,
    equity_curve: pd.DataFrame,
    signal_execution: pd.DataFrame,
    decision_trace: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    return {
        "prices": _write_time_chunk_set(
            report_root=report_root,
            dataset="prices",
            frame=prices,
            time_column="timestamp",
            rows_per_chunk=_CHUNKSET_PRICE_ROWS,
        ),
        "trades": _write_time_chunk_set(
            report_root=report_root,
            dataset="trades",
            frame=trades,
            time_column="entry_time",
            rows_per_chunk=_CHUNKSET_TRADE_ROWS,
        ),
        "equity": _write_time_chunk_set(
            report_root=report_root,
            dataset="equity",
            frame=equity_curve,
            time_column="timestamp",
            rows_per_chunk=_CHUNKSET_EQUITY_ROWS,
        ),
        "signal_execution": _write_time_chunk_set(
            report_root=report_root,
            dataset="signal_execution",
            frame=signal_execution,
            time_column="signal_time",
            rows_per_chunk=_CHUNKSET_TIMELINE_ROWS,
        ),
        "decision_trace": _write_time_chunk_set(
            report_root=report_root,
            dataset="decision_trace",
            frame=decision_trace,
            time_column="execution_time",
            rows_per_chunk=_CHUNKSET_DECISION_TRACE_ROWS,
        ),
    }


def _write_time_chunk_set(
    *,
    report_root: Path,
    dataset: str,
    frame: pd.DataFrame,
    time_column: str,
    rows_per_chunk: int,
) -> dict[str, Any]:
    dataset_slug = _slugify_name(dataset)
    chunk_root = report_root / "chunks" / dataset_slug
    chunk_root.mkdir(parents=True, exist_ok=True)
    manifest_path = chunk_root / _CHUNKSET_MANIFEST_FILENAME

    frame_copy = frame.copy()
    if frame_copy.empty or time_column not in frame_copy.columns:
        payload = {
            "version": "v1",
            "dataset": dataset_slug,
            "time_column": time_column,
            "rows_per_chunk": int(max(1, rows_per_chunk)),
            "total_rows": 0,
            "min_time": None,
            "max_time": None,
            "chunks": [],
        }
        manifest_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        return {"manifest_path": manifest_path, "manifest_payload": payload}

    frame_copy[time_column] = pd.to_datetime(frame_copy[time_column], utc=True, errors="coerce")
    frame_copy = frame_copy.dropna(subset=[time_column]).sort_values(time_column).reset_index(drop=True)
    chunk_size = int(max(1, rows_per_chunk))
    chunks: list[dict[str, Any]] = []
    for offset in range(0, len(frame_copy.index), chunk_size):
        subset = frame_copy.iloc[offset : offset + chunk_size].copy()
        if subset.empty:
            continue
        chunk_seq = offset // chunk_size + 1
        chunk_id = f"{chunk_seq:05d}"
        chunk_name = f"{dataset_slug}_{chunk_id}.parquet"
        chunk_path = chunk_root / chunk_name
        subset.to_parquet(chunk_path, index=False)
        ts_values = pd.to_datetime(subset[time_column], utc=True, errors="coerce").dropna()
        chunks.append(
            {
                "id": chunk_id,
                "file": f"chunks/{dataset_slug}/{chunk_name}",
                "rows": int(len(subset.index)),
                "min_time": ts_values.iloc[0].isoformat() if not ts_values.empty else None,
                "max_time": ts_values.iloc[-1].isoformat() if not ts_values.empty else None,
                "sha256": _file_sha256(chunk_path),
            }
        )

    all_ts = pd.to_datetime(frame_copy[time_column], utc=True, errors="coerce").dropna()
    payload = {
        "version": "v1",
        "dataset": dataset_slug,
        "time_column": time_column,
        "rows_per_chunk": chunk_size,
        "total_rows": int(len(frame_copy.index)),
        "min_time": all_ts.iloc[0].isoformat() if not all_ts.empty else None,
        "max_time": all_ts.iloc[-1].isoformat() if not all_ts.empty else None,
        "chunks": chunks,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return {"manifest_path": manifest_path, "manifest_payload": payload}


def _build_chunk_sets_manifest_payload(
    *,
    report_root: Path,
    chunk_outputs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for name, info in sorted(chunk_outputs.items(), key=lambda item: str(item[0])):
        manifest_payload = info["manifest_payload"]
        payload[name] = {
            "manifest_path": _artifact_relpath(report_root=report_root, path=info["manifest_path"]),
            "rows": int(manifest_payload.get("total_rows", 0) or 0),
            "chunk_count": int(len(manifest_payload.get("chunks", []))),
            "min_time": manifest_payload.get("min_time"),
            "max_time": manifest_payload.get("max_time"),
        }
    return payload


def _artifact_relpath(*, report_root: Path, path: Path) -> str:
    try:
        return path.relative_to(report_root).as_posix()
    except ValueError:
        return path.as_posix()


def _build_json_artifact(*, report_root: Path, path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": _artifact_relpath(report_root=report_root, path=path),
        "type": "json",
        "rows": int(len(payload)) if isinstance(payload, dict) else None,
        "sha256": _file_sha256(path),
    }


def _build_frame_artifact(*, report_root: Path, path: Path, frame: pd.DataFrame, time_columns: list[str]) -> dict[str, Any]:
    min_time: str | None = None
    max_time: str | None = None
    for col in time_columns:
        if col not in frame.columns:
            continue
        values = pd.to_datetime(frame[col], utc=True, errors="coerce").dropna()
        if values.empty:
            continue
        col_min = values.iloc[0].isoformat()
        col_max = values.iloc[-1].isoformat()
        if min_time is None or col_min < min_time:
            min_time = col_min
        if max_time is None or col_max > max_time:
            max_time = col_max
    return {
        "path": _artifact_relpath(report_root=report_root, path=path),
        "type": "table",
        "rows": int(len(frame.index)),
        "sha256": _file_sha256(path),
        "min_time": min_time,
        "max_time": max_time,
    }


def _build_run_manifest(
    *,
    report_root: Path,
    strategy_name: str | None,
    config: EventDrivenBacktestConfig,
    summary_payload: dict[str, Any],
    diagnostics_payload: dict[str, Any],
    artifacts: list[dict[str, Any]],
    base_timeframe: str,
    resampled_timeframes: list[str],
    chunk_sets: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    strategy_slug = report_root.parent.name if report_root.parent != report_root else None
    run_id = report_root.name
    created_at = _infer_run_created_at(run_id=run_id, report_root=report_root)
    return {
        "schema_version": "bt_run_v1",
        "generated_at": _utc_now_iso(),
        "created_at": created_at,
        "run_id": run_id,
        "strategy_slug": strategy_slug,
        "strategy_name": strategy_name,
        "symbol": str(config.symbol),
        "interval_ms": int(config.interval_ms),
        "execution_lag_bars": int(config.execution_lag_bars),
        "base_timeframe": base_timeframe,
        "resampled_timeframes": resampled_timeframes,
        "chunk_sets": chunk_sets or {},
        "summary": summary_payload,
        "diagnostics": diagnostics_payload.get("diagnostics", {}),
        "artifacts": artifacts,
    }


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, float):
        if np.isnan(value):
            return None
        if np.isposinf(value):
            return "inf"
        if np.isneginf(value):
            return "-inf"
    return value


def _update_report_hub(
    *,
    collection_root: Path,
    report_root: Path,
    config: EventDrivenBacktestConfig,
    summary_payload: dict[str, Any],
) -> dict[str, str]:
    collection_root.mkdir(parents=True, exist_ok=True)
    index_path = collection_root / _REPORT_HUB_INDEX_NAME
    hub_path = collection_root / _REPORT_HUB_HTML_NAME
    reports = _load_report_hub_entries(index_path=index_path)
    report_map: dict[str, dict[str, Any]] = {}
    for item in reports:
        run_key = str(item.get("run_path", "") or item.get("run_id", ""))
        if run_key:
            report_map[run_key] = item
    for item in _discover_report_hub_entries(collection_root=collection_root):
        run_key = str(item.get("run_path", "") or item.get("run_id", ""))
        if run_key and run_key not in report_map:
            report_map[run_key] = item
    current = _build_report_hub_entry(
        collection_root=collection_root,
        report_root=report_root,
        config=config,
        summary_payload=summary_payload,
    )
    current_key = str(current.get("run_path", "") or current.get("run_id", ""))
    report_map[current_key] = current
    reports = list(report_map.values())
    reports.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    payload = {
        "version": "v1",
        "updated_at": _utc_now_iso(),
        "collection": collection_root.name,
        "reports": reports,
    }
    index_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    hub_path.write_text(
        _build_report_hub_html(index_filename=_REPORT_HUB_INDEX_NAME, collection_name=collection_root.name),
        encoding="utf-8",
    )
    return {
        "report_hub_index_path": str(index_path),
        "report_hub_path": str(hub_path),
    }


def _load_report_hub_entries(*, index_path: Path) -> list[dict[str, Any]]:
    if not index_path.exists():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        reports = payload.get("reports", [])
        if isinstance(reports, list):
            return [item for item in reports if isinstance(item, dict)]
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _discover_report_hub_entries(*, collection_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not collection_root.exists():
        return entries
    report_dirs: list[Path] = []
    for summary_path in collection_root.rglob("summary.json"):
        child = summary_path.parent
        html_path = child / "event_driven_report.html"
        if not html_path.exists():
            continue
        try:
            child.relative_to(collection_root)
        except ValueError:
            continue
        report_dirs.append(child)
    for child in sorted(report_dirs, reverse=True):
        summary_path = child / "summary.json"
        try:
            summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary_payload = {}
        config_meta = _parse_config_from_report_md(report_path=child / "event_driven_report.md")
        run_rel_path = child.relative_to(collection_root).as_posix()
        entry = {
            "run_id": child.name,
            "run_path": run_rel_path,
            "created_at": _infer_run_created_at(run_id=child.name, report_root=child),
            "symbol": str(config_meta.get("symbol", "UNKNOWN")),
            "interval_ms": int(config_meta.get("interval_ms", 0) or 0),
            "execution_lag_bars": int(config_meta.get("execution_lag_bars", 0) or 0),
            "trade_count": int(_coalesce_int(summary_payload.get("trade_count"), 0) or 0),
            "net_return": _format_float(summary_payload.get("net_return"), digits=6),
            "max_drawdown": _format_float(summary_payload.get("max_drawdown"), digits=6),
            "win_rate": _format_float(summary_payload.get("win_rate"), digits=6),
            "profit_factor": _format_float(summary_payload.get("profit_factor"), digits=6),
            "html_path": f"{run_rel_path}/event_driven_report.html",
            "summary_path": f"{run_rel_path}/summary.json",
            "trades_path": f"{run_rel_path}/{_LEDGER_DIRNAME}/{_TRADES_PARQUET_FILENAME}",
            "equity_curve_path": f"{run_rel_path}/{_CURVE_DIRNAME}/{_EQUITY_PARQUET_FILENAME}",
        }
        entries.append(entry)
    return entries


def _parse_config_from_report_md(*, report_path: Path) -> dict[str, Any]:
    default = {"symbol": "UNKNOWN", "interval_ms": 0, "execution_lag_bars": 0}
    if not report_path.exists():
        return default
    text = report_path.read_text(encoding="utf-8")
    symbol = _extract_md_config_value(text=text, key="symbol") or "UNKNOWN"
    interval_ms = _coalesce_int(_extract_md_config_value(text=text, key="interval_ms"), 0) or 0
    execution_lag_bars = _coalesce_int(_extract_md_config_value(text=text, key="execution_lag_bars"), 0) or 0
    return {
        "symbol": symbol,
        "interval_ms": int(interval_ms),
        "execution_lag_bars": int(execution_lag_bars),
    }


def _extract_md_config_value(*, text: str, key: str) -> str | None:
    pattern = rf"-\s+{re.escape(key)}:\s+`([^`]+)`"
    match = re.search(pattern, text)
    if not match:
        return None
    return match.group(1).strip()


def _build_report_hub_entry(
    *,
    collection_root: Path,
    report_root: Path,
    config: EventDrivenBacktestConfig,
    summary_payload: dict[str, Any],
) -> dict[str, Any]:
    run_id = report_root.name
    try:
        run_rel_path = report_root.relative_to(collection_root).as_posix()
    except ValueError:
        run_rel_path = run_id
    trade_count = _coalesce_int(summary_payload.get("trade_count"), 0) or 0
    return {
        "run_id": run_id,
        "run_path": run_rel_path,
        "created_at": _infer_run_created_at(run_id=run_id, report_root=report_root),
        "symbol": str(config.symbol),
        "interval_ms": int(config.interval_ms),
        "execution_lag_bars": int(config.execution_lag_bars),
        "trade_count": int(trade_count),
        "net_return": _format_float(summary_payload.get("net_return"), digits=6),
        "max_drawdown": _format_float(summary_payload.get("max_drawdown"), digits=6),
        "win_rate": _format_float(summary_payload.get("win_rate"), digits=6),
        "profit_factor": _format_float(summary_payload.get("profit_factor"), digits=6),
        "html_path": f"{run_rel_path}/event_driven_report.html",
        "summary_path": f"{run_rel_path}/summary.json",
        "trades_path": f"{run_rel_path}/{_LEDGER_DIRNAME}/{_TRADES_PARQUET_FILENAME}",
        "equity_curve_path": f"{run_rel_path}/{_CURVE_DIRNAME}/{_EQUITY_PARQUET_FILENAME}",
    }


def _infer_run_created_at(*, run_id: str, report_root: Path) -> str:
    token = run_id.split("_", 1)[0]
    try:
        parsed = datetime.strptime(token, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return parsed.isoformat().replace("+00:00", "Z")
    except ValueError:
        pass
    try:
        mtime = datetime.fromtimestamp(report_root.stat().st_mtime, tz=timezone.utc)
        return mtime.isoformat().replace("+00:00", "Z")
    except OSError:
        return _utc_now_iso()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_report_hub_html(*, index_filename: str, collection_name: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Backtest Report Hub</title>
  <style>
    :root {{
      --bg: #f8fafc;
      --panel: #ffffff;
      --ink: #0f172a;
      --muted: #64748b;
      --line: #e2e8f0;
      --accent: #0f766e;
    }}
    body {{ margin: 0; font-family: "IBM Plex Sans", "Noto Sans SC", sans-serif; color: var(--ink); background: linear-gradient(180deg, #ecfeff 0%, var(--bg) 45%); }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 18px; }}
    .title {{ margin: 0 0 6px 0; font-size: 28px; }}
    .sub {{ margin: 0 0 14px 0; color: var(--muted); }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px; }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }}
    .controls label {{ font-size: 12px; color: var(--ink); font-weight: 600; }}
    .controls input, .controls select, .controls button {{ border: 1px solid var(--line); border-radius: 6px; background: #fff; padding: 5px 8px; font-size: 12px; }}
    .controls button {{ cursor: pointer; }}
    .status {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px; font-size: 12px; text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; }}
    .num {{ text-align: right; font-family: "IBM Plex Mono", monospace; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .empty {{ color: var(--muted); padding: 10px 0; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1 class="title">Backtest Report Hub</h1>
    <p class="sub">collection: <code>{escape(collection_name)}</code> | 保持此页面打开，新生成报告会自动出现。</p>
    <div class="panel">
      <div class="controls">
        <label for="q">Search:</label><input id="q" type="text" placeholder="run_id / symbol" />
        <label for="refreshMs">Auto Refresh:</label>
        <select id="refreshMs">
          <option value="5000" selected>5s</option>
          <option value="15000">15s</option>
          <option value="60000">60s</option>
        </select>
        <label><input id="autoRefresh" type="checkbox" checked /> enabled</label>
        <button id="refreshNow" type="button">Refresh Now</button>
      </div>
      <div id="status" class="status">Loading...</div>
      <table>
        <thead>
          <tr>
            <th>run_id</th><th>created_at</th><th>symbol</th><th class="num">interval_ms</th><th class="num">trades</th><th class="num">net_return</th><th class="num">max_dd</th><th class="num">win_rate</th><th class="num">pf</th><th>links</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
      <div id="empty" class="empty" style="display:none">No reports yet.</div>
    </div>
  </div>
  <script>
    (function () {{
      const indexFile = {json.dumps(index_filename, ensure_ascii=True)};
      const q = document.getElementById("q");
      const status = document.getElementById("status");
      const rows = document.getElementById("rows");
      const empty = document.getElementById("empty");
      const refreshNow = document.getElementById("refreshNow");
      const autoRefresh = document.getElementById("autoRefresh");
      const refreshMs = document.getElementById("refreshMs");
      const state = {{ reports: [], updatedAt: "", timer: null }};

      const esc = (v) => String(v || "").replace(/[&<>"]/g, (c) => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}}[c] || c));
      const norm = (v) => String(v || "").toLowerCase();

      const render = () => {{
        const keyword = norm(q ? q.value : "");
        const filtered = state.reports.filter((item) => {{
          if (!keyword) return true;
          return norm(item.run_id).includes(keyword) || norm(item.symbol).includes(keyword);
        }});
        rows.innerHTML = filtered.map((item) => {{
          return (
            "<tr>" +
            "<td><a href='" + esc(item.html_path) + "' target='_blank' rel='noopener noreferrer'>" + esc(item.run_id) + "</a></td>" +
            "<td>" + esc(item.created_at) + "</td>" +
            "<td>" + esc(item.symbol) + "</td>" +
            "<td class='num'>" + esc(item.interval_ms) + "</td>" +
            "<td class='num'>" + esc(item.trade_count) + "</td>" +
            "<td class='num'>" + esc(item.net_return) + "</td>" +
            "<td class='num'>" + esc(item.max_drawdown) + "</td>" +
            "<td class='num'>" + esc(item.win_rate) + "</td>" +
            "<td class='num'>" + esc(item.profit_factor) + "</td>" +
            "<td><a href='" + esc(item.summary_path) + "' target='_blank' rel='noopener noreferrer'>summary</a> | <a href='" + esc(item.trades_path) + "' target='_blank' rel='noopener noreferrer'>trades</a></td>" +
            "</tr>"
          );
        }}).join("");
        empty.style.display = filtered.length === 0 ? "" : "none";
        const label = state.updatedAt ? ("updated_at: " + state.updatedAt) : "updated_at: unknown";
        status.textContent = label + " | reports: " + state.reports.length + " | showing: " + filtered.length;
      }};

      const load = async () => {{
        try {{
          const res = await fetch(indexFile + "?ts=" + Date.now(), {{ cache: "no-store" }});
          if (!res.ok) throw new Error("failed: " + res.status);
          const payload = await res.json();
          state.reports = Array.isArray(payload.reports) ? payload.reports : [];
          state.updatedAt = String(payload.updated_at || "");
          render();
        }} catch (error) {{
          status.textContent = "load failed: " + error;
        }}
      }};

      const resetTimer = () => {{
        if (state.timer) {{
          clearInterval(state.timer);
          state.timer = null;
        }}
        if (!autoRefresh || !autoRefresh.checked) return;
        const ms = Number.parseInt(refreshMs ? refreshMs.value : "5000", 10);
        const interval = Number.isFinite(ms) ? Math.max(2000, ms) : 5000;
        state.timer = setInterval(load, interval);
      }};

      if (q) q.addEventListener("input", render);
      if (refreshNow) refreshNow.addEventListener("click", load);
      if (autoRefresh) autoRefresh.addEventListener("change", resetTimer);
      if (refreshMs) refreshMs.addEventListener("change", resetTimer);
      load();
      resetTimer();
    }})();
  </script>
</body>
</html>
"""


def _build_event_driven_dashboard_html(
    *,
    config: EventDrivenBacktestConfig,
    result: EventDrivenBacktestResult,
    summary_payload: dict[str, Any],
    price_frame: pd.DataFrame | None,
    actions: pd.DataFrame | None,
    signal_interval_ms: int | None,
    ledger_manifest_name: str | None = None,
    echarts_script_src: str = "./echarts.min.js",
) -> str:
    prices = _prepare_dashboard_prices(price_frame=price_frame, symbol=config.symbol)
    action_events = _prepare_dashboard_actions(
        actions=actions,
        symbol=config.symbol,
        execution_lag_ms=config.interval_ms * config.execution_lag_bars,
    )
    action_events_full = _prepare_dashboard_actions(
        actions=actions,
        symbol=config.symbol,
        execution_lag_ms=config.interval_ms * config.execution_lag_bars,
        max_rows=None,
    )
    chunked_ledger = ledger_manifest_name is not None
    replay_payload = _build_trade_replay_payload(prices=prices, trades=result.trades, max_trades=1_000 if chunked_ledger else None)
    replay_payload_json = _json_for_script(replay_payload)
    kline_payload_json = _json_for_script(
        _build_kline_chart_payload(
            prices=prices,
            trades=result.trades,
            equity_curve=result.equity_curve,
            action_events=action_events_full,
        )
    )
    dashboard_bounds = _build_dashboard_time_bounds(
        prices=prices,
        action_events=action_events,
        equity_curve=result.equity_curve,
        trades=result.trades,
    )
    dashboard_bounds_json = _json_for_script(dashboard_bounds)
    trades_table = _build_chunked_ledger_placeholder_html() if chunked_ledger else _build_trades_table_html(trades=result.trades)
    filter_options = _build_trade_filter_options(trades=result.trades, max_options=300 if chunked_ledger else None)
    has_trades = not result.trades.empty
    range_controls_html = (
        "<div class='controls'>"
        "<label for='rangePreset'>Range:</label>"
        "<select id='rangePreset'><option value='1D'>1D</option><option value='3D'>3D</option><option value='7D' selected>7D</option><option value='10D'>10D</option><option value='CUSTOM'>CUSTOM</option></select>"
        "<input id='rangeStart' type='datetime-local' />"
        "<input id='rangeEnd' type='datetime-local' />"
        "<button id='applyRange' type='button'>Apply</button>"
        "<span id='rangeStatus' class='hint'>Range 限制为最多 10 天（支持自定义）。</span>"
        "</div>"
    )
    replay_controls_html = (
        "<div class='controls'>"
        "<label for='tradeFilter'>Replay Trade:</label>"
        f"<select id='tradeFilter'>{filter_options}</select>"
        "<label for='klineMode'>Kline Mode:</label>"
        "<select id='klineMode'><option value='range' selected>Range</option><option value='spotlight'>Trade Spotlight</option></select>"
        "<label for='windowBars'>Window Bars:</label>"
        "<input id='windowBars' type='number' min='1' max='200' step='1' value='24' />"
        "<span class='hint'>Range 会自动抽样标记避免遮挡；Spotlight 用于单笔交易放大观察。</span>"
        "</div>"
        if has_trades
        else "<div class='empty'>No closed trades, replay selector unavailable.</div>"
    )
    details_html = (
        "<div id='tradeDetails' class='detail-card'>"
        "Select one trade from Replay Trade, or hover markers/ledger rows for details."
        "</div>"
        if has_trades
        else "<div id='tradeDetails' class='detail-card empty'>No closed trades.</div>"
    )
    ledger_mode_notice = (
        "<div class='detail-card'>Long-range mode enabled: Trade Ledger is chunk-loaded and paginated."
        " Open report via local static server for best experience.</div>"
        if chunked_ledger
        else ""
    )
    cards = [
        ("Trade Count", str(summary_payload.get("trade_count", 0))),
        ("Net Return", _format_float(summary_payload.get("net_return", 0.0), digits=6)),
        ("Max Drawdown", _format_float(summary_payload.get("max_drawdown", 0.0), digits=6)),
        ("Win Rate", _format_float(summary_payload.get("win_rate", 0.0), digits=6)),
        ("Profit Factor", _format_float(summary_payload.get("profit_factor", 0.0), digits=6)),
        ("Expectancy", _format_float(summary_payload.get("expectancy", 0.0), digits=6)),
    ]
    card_html = "".join(
        [
            "<div class='card'>"
            f"<div class='card-title'>{escape(name)}</div>"
            f"<div class='card-value'>{escape(value)}</div>"
            "</div>"
            for name, value in cards
        ]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Event-driven Backtest Dashboard</title>
  <script src="{escape(str(echarts_script_src))}"></script>
  <style>
    :root {{
      --bg: #f8fafc;
      --panel: #ffffff;
      --ink: #0f172a;
      --muted: #64748b;
      --line: #e2e8f0;
      --up: #16a34a;
      --down: #dc2626;
      --entry: #2563eb;
      --exit-win: #16a34a;
      --exit-loss: #dc2626;
    }}
    body {{ margin: 0; font-family: "IBM Plex Sans", "Noto Sans SC", sans-serif; color: var(--ink); background: linear-gradient(180deg, #eef2ff 0%, var(--bg) 40%); }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 20px; }}
    .title {{ margin: 0 0 8px 0; font-size: 28px; font-weight: 700; }}
    .sub {{ margin: 0 0 18px 0; color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 16px; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; }}
    .card-title {{ font-size: 12px; color: var(--muted); margin-bottom: 6px; }}
    .card-value {{ font-size: 20px; font-weight: 700; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px; margin-bottom: 14px; }}
    .panel h2 {{ margin: 0 0 10px 0; font-size: 16px; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 8px 0 0 0; color: var(--muted); font-size: 12px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 4px; }}
    .controls {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0 0 8px 0; font-size: 12px; color: var(--muted); }}
    .controls label {{ color: var(--ink); font-weight: 600; }}
    .controls select {{ border: 1px solid var(--line); border-radius: 6px; background: #fff; padding: 4px 8px; font-size: 12px; }}
    .controls input[type='datetime-local'] {{ width: 140px; border: 1px solid var(--line); border-radius: 6px; background: #fff; padding: 4px 8px; font-size: 12px; }}
    .controls input[type='number'] {{ width: 84px; border: 1px solid var(--line); border-radius: 6px; background: #fff; padding: 4px 8px; font-size: 12px; }}
    .controls input[type='checkbox'] {{ width: auto; accent-color: #2563eb; transform: translateY(1px); }}
    .controls button {{ border: 1px solid var(--line); border-radius: 6px; background: #fff; padding: 4px 8px; font-size: 12px; cursor: pointer; }}
    .hint {{ color: var(--muted); }}
    .detail-card {{ border: 1px dashed #cbd5e1; border-radius: 8px; background: #f8fafc; padding: 9px 10px; margin: 0 0 10px 0; font-size: 12px; color: #0f172a; }}
    .detail-title {{ font-size: 13px; font-weight: 700; margin-bottom: 6px; }}
    .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(138px, 1fr)); gap: 5px 10px; }}
    .detail-item {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #334155; }}
    .detail-item strong {{ color: #0f172a; }}
    .banner {{ border: 1px solid #fbbf24; background: #fffbeb; color: #92400e; }}
    .banner button {{ margin-left: 8px; border: 1px solid #f59e0b; border-radius: 6px; background: #fff; color: #92400e; padding: 3px 8px; cursor: pointer; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 7px; font-size: 12px; text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; }}
    .num {{ text-align: right; font-family: "IBM Plex Mono", monospace; }}
    .win {{ color: var(--up); }}
    .loss {{ color: var(--down); }}
    .empty {{ color: var(--muted); font-size: 13px; padding: 6px 0; }}
    svg {{ width: 100%; height: auto; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
    .kline-echart {{ width: 100%; height: 430px; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div id="fileModeBanner" class="detail-card banner" style="display:none">
      Detected file:// mode. For chunk auto-loading, run local static server:
      <code>python -m http.server 8000</code> and open <code>http://localhost:8000/...</code>.
      <button id="copyServerCmd" type="button">Copy Command</button>
      <span id="copyServerCmdStatus" class="hint"></span>
    </div>
    <h1 class="title">Event-driven Backtest Dashboard</h1>
    <p class="sub">symbol: <code>{escape(str(config.symbol))}</code> | interval_ms: <code>{config.interval_ms}</code> | execution_lag_bars: <code>{config.execution_lag_bars}</code></p>

    <div class="grid">{card_html}</div>

    <div class="panel">
      <h2>Kline</h2>
      {range_controls_html}
      <div id="klineEchart" class="kline-echart" style="visibility:hidden"></div>
      <div class="legend">
        <span><i class="dot" style="background:var(--up)"></i>Bull Candle</span>
        <span><i class="dot" style="background:var(--down)"></i>Bear Candle</span>
      </div>
    </div>

    <div class="panel">
      <h2>Trade Ledger</h2>
      {replay_controls_html}
      {ledger_mode_notice}
      {details_html}
      {trades_table}
    </div>
  </div>
  <script>
    (function () {{
      const ledgerManifestName = {json.dumps(ledger_manifest_name, ensure_ascii=True)};
      const isChunkedLedger = Boolean(ledgerManifestName);
      const replay = {replay_payload_json};
      const klinePayload = {kline_payload_json};
      const dashboardBounds = {dashboard_bounds_json};
      const tradeBars = replay.trade_bars || {{}};
      const tradeDetails = replay.trade_details || {{}};
      const filter = document.getElementById("tradeFilter");
      const klineMode = document.getElementById("klineMode");
      const windowBarsInput = document.getElementById("windowBars");
      const rangePreset = document.getElementById("rangePreset");
      const rangeStart = document.getElementById("rangeStart");
      const rangeEnd = document.getElementById("rangeEnd");
      const applyRangeBtn = document.getElementById("applyRange");
      const rangeStatus = document.getElementById("rangeStatus");
      const detailsCard = document.getElementById("tradeDetails");
      const klineSvg = document.getElementById("klineSvg");
      const timelineSvg = document.getElementById("timelineSvg");
      const equitySvg = document.getElementById("equitySvg");
      const klineBaseViewBox = klineSvg ? klineSvg.getAttribute("data-base-viewbox") : null;
      const timelineBaseViewBox = timelineSvg ? timelineSvg.getAttribute("data-base-viewbox") : null;
      const equityBaseViewBox = equitySvg ? equitySvg.getAttribute("data-base-viewbox") : null;
      const timelineDetailsCard = document.getElementById("timelineDetails");
      const ledgerBody = document.getElementById("tradeLedgerBody");
      const ledgerInfo = document.getElementById("tradeLedgerInfo");
      const ledgerPrev = document.getElementById("tradeLedgerPrev");
      const ledgerNext = document.getElementById("tradeLedgerNext");
      const pageSizeSelect = document.getElementById("tradeLedgerPageSize");
      const fileBanner = document.getElementById("fileModeBanner");
      const copyServerCmdBtn = document.getElementById("copyServerCmd");
      const copyServerCmdStatus = document.getElementById("copyServerCmdStatus");
      if (fileBanner && window.location.protocol === "file:") {{
        fileBanner.style.display = "block";
      }}
      if (copyServerCmdBtn) {{
        copyServerCmdBtn.addEventListener("click", async () => {{
          const cmd = "python -m http.server 8000";
          let ok = false;
          try {{
            if (navigator.clipboard && navigator.clipboard.writeText) {{
              await navigator.clipboard.writeText(cmd);
              ok = true;
            }}
          }} catch (_error) {{}}
          if (!ok) {{
            const input = document.createElement("input");
            input.value = cmd;
            document.body.appendChild(input);
            input.select();
            try {{
              ok = document.execCommand("copy");
            }} catch (_error) {{
              ok = false;
            }}
            document.body.removeChild(input);
          }}
          if (copyServerCmdStatus) {{
            copyServerCmdStatus.textContent = ok ? " copied." : " copy failed.";
          }}
        }});
      }}

      const ledgerState = {{
        manifest: null,
        chunkCache: new Map(),
        loadedRows: [],
        filteredRows: [],
        page: 1,
        pageSize: 100,
        rangeStartMs: null,
        rangeEndMs: null,
      }};
      const MAX_RANGE_KLINE_MARKERS = 60;
      const MAX_RANGE_MS = 10 * 24 * 3600 * 1000;
      const MAX_BARS_PER_VIEW = 2_900;
      const klineEchartRoot = document.getElementById("klineEchart");
      const klineBars = Array.isArray(klinePayload && klinePayload.bars) ? klinePayload.bars : [];
      const klineTrades = Array.isArray(klinePayload && klinePayload.trades) ? klinePayload.trades : [];
      const klineTradeMetaFromPayload = new Map();
      klineTrades.forEach((row) => {{
        const tradeId = String(row.trade_id || "");
        if (!tradeId) return;
        const entryMs = Number.parseFloat(String(row.entry_ms || "NaN"));
        const exitMs = Number.parseFloat(String(row.exit_ms || "NaN"));
        klineTradeMetaFromPayload.set(tradeId, {{
          entryMs,
          exitMs: Number.isFinite(exitMs) ? exitMs : entryMs,
          entryIdx: Number.parseInt(String(row.entry_idx || "0"), 10),
          exitIdx: Number.parseInt(String(row.exit_idx || "0"), 10),
          entryPrice: Number.parseFloat(String(row.entry_price || "NaN")),
          exitPrice: Number.parseFloat(String(row.exit_price || "NaN")),
          side: String(row.side || ""),
          netPnl: Number.parseFloat(String(row.net_pnl || "0")),
        }});
      }});
      const hasEcharts = typeof window.echarts !== "undefined";
      const canUseEchartKline = Boolean(hasEcharts && klineEchartRoot && klineBars.length > 0);
      if (klineEchartRoot && !canUseEchartKline) {{
        klineEchartRoot.style.display = "";
        klineEchartRoot.style.visibility = "visible";
        klineEchartRoot.innerHTML = "<div class='empty' style='padding:12px'>ECharts unavailable or no kline bars.</div>";
      }}
      let klineChart = null;
      let klineResizeObserver = null;
      let suppressKlineDataZoomSync = false;

      const restoreDetails = () => {{
        if (!detailsCard) return;
        detailsCard.textContent = "Select one trade from Replay Trade, or hover markers/ledger rows for details.";
      }};

      const restoreTimelineDetails = () => {{
        if (!timelineDetailsCard) return;
        timelineDetailsCard.textContent = "Hover any timeline event to inspect signal_time, execution_time, lag, action, and reason.";
      }};

      const parseUtcMs = (value) => {{
        if (!value) return null;
        const normalized = String(value).trim();
        if (!normalized) return null;
        const localIso = /^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}(?::\\d{{2}})?$/;
        const withZone = /[zZ]$|[+\\-]\\d{{2}}:\\d{{2}}$/;
        const candidate = localIso.test(normalized) && !withZone.test(normalized) ? normalized + "Z" : normalized;
        const parsed = Date.parse(candidate);
        if (Number.isNaN(parsed)) return null;
        return parsed;
      }};

      const setRangeStatus = (text) => {{
        if (!rangeStatus) return;
        rangeStatus.textContent = text || "Range 限制为最多 10 天（支持自定义）。";
      }};

      const toDatetimeLocal = (ms) => {{
        if (!Number.isFinite(ms)) return "";
        const date = new Date(ms);
        const pad = (n) => String(n).padStart(2, "0");
        const yyyy = date.getUTCFullYear();
        const mm = pad(date.getUTCMonth() + 1);
        const dd = pad(date.getUTCDate());
        const hh = pad(date.getUTCHours());
        const mi = pad(date.getUTCMinutes());
        return `${{yyyy}}-${{mm}}-${{dd}}T${{hh}}:${{mi}}`;
      }};

      const syncRangeInputs = (startMs, endMs, bounds) => {{
        if (rangeStart && Number.isFinite(startMs)) rangeStart.value = toDatetimeLocal(startMs);
        if (rangeEnd && Number.isFinite(endMs)) rangeEnd.value = toDatetimeLocal(endMs);
        if (rangeStart && Number.isFinite(bounds.minMs)) rangeStart.min = toDatetimeLocal(bounds.minMs);
        if (rangeStart && Number.isFinite(bounds.maxMs)) rangeStart.max = toDatetimeLocal(bounds.maxMs);
        if (rangeEnd && Number.isFinite(bounds.minMs)) rangeEnd.min = toDatetimeLocal(bounds.minMs);
        if (rangeEnd && Number.isFinite(bounds.maxMs)) rangeEnd.max = toDatetimeLocal(bounds.maxMs);
      }};

      const intersects = (aStart, aEnd, bStart, bEnd) => !(aEnd < bStart || bEnd < aStart);

      const resolveRangeBounds = () => {{
        let minMs = parseUtcMs(dashboardBounds ? dashboardBounds.min_time : null);
        let maxMs = parseUtcMs(dashboardBounds ? dashboardBounds.max_time : null);
        const manifestMin = parseUtcMs(ledgerState.manifest ? ledgerState.manifest.min_entry_time : null);
        const manifestMax = parseUtcMs(ledgerState.manifest ? ledgerState.manifest.max_entry_time : null);
        if (Number.isFinite(manifestMin)) {{
          minMs = Number.isFinite(minMs) ? Math.min(minMs, manifestMin) : manifestMin;
        }}
        if (Number.isFinite(manifestMax)) {{
          maxMs = Number.isFinite(maxMs) ? Math.max(maxMs, manifestMax) : manifestMax;
        }}
        return {{ minMs, maxMs }};
      }};

      const getActiveRange = () => {{
        const bounds = resolveRangeBounds();
        let startMs = Number.isFinite(ledgerState.rangeStartMs) ? ledgerState.rangeStartMs : bounds.minMs;
        let endMs = Number.isFinite(ledgerState.rangeEndMs) ? ledgerState.rangeEndMs : bounds.maxMs;
        if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) {{
          return {{ startMs: null, endMs: null }};
        }}
        if (endMs < startMs) {{
          const temp = startMs;
          startMs = endMs;
          endMs = temp;
        }}
        if (Number.isFinite(bounds.minMs)) startMs = Math.max(startMs, bounds.minMs);
        if (Number.isFinite(bounds.maxMs)) endMs = Math.min(endMs, bounds.maxMs);
        return {{ startMs, endMs }};
      }};

      const normalizeRange = (startMs, endMs, bounds) => {{
        let s = Number.isFinite(startMs) ? startMs : bounds.minMs;
        let e = Number.isFinite(endMs) ? endMs : bounds.maxMs;
        if (!Number.isFinite(s) || !Number.isFinite(e)) {{
          return {{ startMs: null, endMs: null, clamped: false }};
        }}
        if (e < s) {{
          const tmp = s;
          s = e;
          e = tmp;
        }}
        if (Number.isFinite(bounds.minMs)) s = Math.max(s, bounds.minMs);
        if (Number.isFinite(bounds.maxMs)) e = Math.min(e, bounds.maxMs);
        let clamped = false;
        if ((e - s) > MAX_RANGE_MS) {{
          s = e - MAX_RANGE_MS;
          clamped = true;
          if (Number.isFinite(bounds.minMs) && s < bounds.minMs) {{
            s = bounds.minMs;
          }}
        }}
        return {{ startMs: s, endMs: e, clamped }};
      }};

      const applyTimeRangeView = (svg, baseViewBox, startMs, endMs) => {{
        if (!svg || !baseViewBox) return;
        if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) {{
          svg.setAttribute("viewBox", baseViewBox);
          return;
        }}
        const chartWidth = Number(svg.dataset.chartWidth || 0);
        const chartHeight = Number(svg.dataset.chartHeight || 0);
        const marginLeft = Number(svg.dataset.marginLeft || 0);
        const marginRight = Number(svg.dataset.marginRight || 0);
        const dataMin = Number(svg.dataset.minMs || NaN);
        const dataMax = Number(svg.dataset.maxMs || NaN);
        if (!(chartWidth > 0 && chartHeight > 0 && Number.isFinite(dataMin) && Number.isFinite(dataMax) && dataMax > dataMin)) {{
          svg.setAttribute("viewBox", baseViewBox);
          return;
        }}
        const clampedStart = Math.max(dataMin, Math.min(startMs, dataMax));
        const clampedEnd = Math.max(dataMin, Math.min(endMs, dataMax));
        if (!(clampedEnd > clampedStart)) {{
          svg.setAttribute("viewBox", baseViewBox);
          return;
        }}
        const fullSpan = dataMax - dataMin;
        const selectedSpan = clampedEnd - clampedStart;
        if (!(fullSpan > 0) || selectedSpan >= fullSpan * 0.995) {{
          // Prevent axis label clipping when user is effectively on ALL range.
          svg.setAttribute("viewBox", baseViewBox);
          return;
        }}
        const innerWidth = chartWidth - marginLeft - marginRight;
        const xOf = (ms) => marginLeft + ((ms - dataMin) / (dataMax - dataMin)) * innerWidth;
        const xLeft = xOf(clampedStart);
        const xRight = xOf(clampedEnd);
        const pad = Math.max(6.0, innerWidth * 0.008);
        let viewWidth = Math.max(80.0, xRight - xLeft + pad * 2.0);
        viewWidth = Math.min(viewWidth, chartWidth);
        let viewX = xLeft - pad;
        viewX = Math.max(0.0, Math.min(viewX, chartWidth - viewWidth));
        svg.setAttribute("viewBox", viewX.toFixed(2) + " 0 " + viewWidth.toFixed(2) + " " + chartHeight.toFixed(2));
      }};

      const applyRangeToPanels = () => {{
        const {{ startMs, endMs }} = getActiveRange();
        applyTimeRangeView(timelineSvg, timelineBaseViewBox, startMs, endMs);
        applyTimeRangeView(equitySvg, equityBaseViewBox, startMs, endMs);
      }};

      const applyKlineRangeView = (startMs, endMs) => {{
        if (!klineSvg || !klineBaseViewBox) return;
        if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) {{
          klineSvg.setAttribute("viewBox", klineBaseViewBox);
          const overviewLabel = document.getElementById("klineOverviewLabel");
          if (overviewLabel) overviewLabel.style.display = "";
          return;
        }}
        const chartWidth = Number(klineSvg.dataset.chartWidth || 0);
        const chartHeight = Number(klineSvg.dataset.chartHeight || 0);
        const marginLeft = Number(klineSvg.dataset.marginLeft || 0);
        const marginRight = Number(klineSvg.dataset.marginRight || 0);
        const dataMin = Number(klineSvg.dataset.minMs || NaN);
        const dataMax = Number(klineSvg.dataset.maxMs || NaN);
        if (!(chartWidth > 0 && chartHeight > 0 && Number.isFinite(dataMin) && Number.isFinite(dataMax) && dataMax > dataMin)) {{
          klineSvg.setAttribute("viewBox", klineBaseViewBox);
          return;
        }}
        const clampedStart = Math.max(dataMin, Math.min(startMs, dataMax));
        const clampedEnd = Math.max(dataMin, Math.min(endMs, dataMax));
        if (!(clampedEnd > clampedStart)) {{
          klineSvg.setAttribute("viewBox", klineBaseViewBox);
          return;
        }}
        const fullSpan = dataMax - dataMin;
        const selectedSpan = clampedEnd - clampedStart;
        const useFull = !(fullSpan > 0) || selectedSpan >= fullSpan * 0.995;
        const overviewLabel = document.getElementById("klineOverviewLabel");
        if (overviewLabel) overviewLabel.style.display = useFull ? "" : "none";
        if (useFull) {{
          klineSvg.setAttribute("viewBox", klineBaseViewBox);
          return;
        }}
        const innerWidth = chartWidth - marginLeft - marginRight;
        const xOf = (ms) => marginLeft + ((ms - dataMin) / (dataMax - dataMin)) * innerWidth;
        const xLeft = xOf(clampedStart);
        const xRight = xOf(clampedEnd);
        const padX = Math.max(6.0, innerWidth * 0.008);
        let viewWidth = Math.max(80.0, xRight - xLeft + padX * 2.0);
        viewWidth = Math.min(viewWidth, chartWidth);
        let viewX = xLeft - padX;
        viewX = Math.max(0.0, Math.min(viewX, chartWidth - viewWidth));

        let yTop = Number.POSITIVE_INFINITY;
        let yBottom = Number.NEGATIVE_INFINITY;
        klineSvg.querySelectorAll(".kline-candle[data-ts-ms]").forEach((node) => {{
          const ts = Number.parseFloat(node.getAttribute("data-ts-ms") || "NaN");
          if (!Number.isFinite(ts) || ts < clampedStart || ts > clampedEnd) return;
          const y1 = Number.parseFloat(node.getAttribute("y1") || "NaN");
          const y2 = Number.parseFloat(node.getAttribute("y2") || "NaN");
          const y = Number.parseFloat(node.getAttribute("y") || "NaN");
          const h = Number.parseFloat(node.getAttribute("height") || "NaN");
          if (Number.isFinite(y1) && Number.isFinite(y2)) {{
            yTop = Math.min(yTop, y1, y2);
            yBottom = Math.max(yBottom, y1, y2);
          }} else if (Number.isFinite(y) && Number.isFinite(h)) {{
            yTop = Math.min(yTop, y);
            yBottom = Math.max(yBottom, y + h);
          }}
        }});

        let viewY = 0.0;
        let viewHeight = chartHeight;
        if (Number.isFinite(yTop) && Number.isFinite(yBottom) && yBottom > yTop) {{
          const padY = Math.max(6.0, (yBottom - yTop) * 0.18);
          const minViewH = Math.max(60.0, chartHeight * 0.36);
          const y0 = Math.max(0.0, yTop - padY);
          const y1 = Math.min(chartHeight, yBottom + padY);
          viewY = y0;
          viewHeight = Math.max(minViewH, y1 - y0);
          if (viewY + viewHeight > chartHeight) {{
            viewY = Math.max(0.0, chartHeight - viewHeight);
          }}
          viewHeight = Math.min(viewHeight, chartHeight);
        }}
        klineSvg.setAttribute(
          "viewBox",
          viewX.toFixed(2) + " " + viewY.toFixed(2) + " " + viewWidth.toFixed(2) + " " + viewHeight.toFixed(2),
        );
      }};

      const setPresetRange = () => {{
        const preset = rangePreset ? rangePreset.value : "7D";
        const bounds = resolveRangeBounds();
        const endMs = bounds.maxMs;
        if (!Number.isFinite(endMs)) return;
        let startMs = endMs;
        if (preset === "1D") startMs = endMs - 1 * 24 * 3600 * 1000;
        else if (preset === "3D") startMs = endMs - 3 * 24 * 3600 * 1000;
        else if (preset === "7D") startMs = endMs - 7 * 24 * 3600 * 1000;
        else if (preset === "10D") startMs = endMs - 10 * 24 * 3600 * 1000;
        else if (preset === "CUSTOM") {{
          startMs = parseUtcMs(rangeStart ? rangeStart.value : "");
        }}
        const customEnd = preset === "CUSTOM" ? parseUtcMs(rangeEnd ? rangeEnd.value : "") : endMs;
        const normalized = normalizeRange(startMs, customEnd, bounds);
        ledgerState.rangeStartMs = normalized.startMs;
        ledgerState.rangeEndMs = normalized.endMs;
        setRangeStatus(normalized.clamped ? "自定义区间超过 10 天，已自动截断到 10 天。" : "");
        syncRangeInputs(ledgerState.rangeStartMs, ledgerState.rangeEndMs, bounds);
      }};

      const loadLedgerManifest = async () => {{
        if (!isChunkedLedger) return;
        if (ledgerState.manifest) return;
        const response = await fetch(ledgerManifestName);
        if (!response.ok) throw new Error(`failed to load manifest: ${{response.status}}`);
        ledgerState.manifest = await response.json();
        setPresetRange();
      }};

      const loadLedgerRowsForRange = async () => {{
        if (!isChunkedLedger) return;
        await loadLedgerManifest();
        const manifest = ledgerState.manifest;
        if (!manifest) return;
        const activeRange = getActiveRange();
        const startMs = Number.isFinite(activeRange.startMs) ? activeRange.startMs : parseUtcMs(manifest.min_entry_time);
        const endMs = Number.isFinite(activeRange.endMs) ? activeRange.endMs : parseUtcMs(manifest.max_entry_time);
        const chunkItems = Array.isArray(manifest.chunks) ? manifest.chunks : [];
        const need = chunkItems.filter((chunk) => {{
          const cStart = parseUtcMs(chunk.start);
          const cEnd = parseUtcMs(chunk.end);
          if (!Number.isFinite(cStart) || !Number.isFinite(cEnd)) return false;
          return intersects(cStart, cEnd, startMs, endMs);
        }});
        for (const chunk of need) {{
          if (ledgerState.chunkCache.has(chunk.id)) continue;
          const res = await fetch(chunk.file);
          if (!res.ok) continue;
          const payload = await res.json();
          const rows = Array.isArray(payload.rows) ? payload.rows : [];
          ledgerState.chunkCache.set(chunk.id, rows);
        }}
        const loaded = [];
        for (const chunk of need) {{
          const rows = ledgerState.chunkCache.get(chunk.id) || [];
          for (const row of rows) {{
            loaded.push(row);
          }}
        }}
        ledgerState.loadedRows = loaded;
        ledgerState.filteredRows = loaded.filter((row) => {{
          const t = parseUtcMs(row.entry_time);
          if (!Number.isFinite(t)) return false;
          return t >= startMs && t <= endMs;
        }});
      }};

      const renderLedgerInfo = () => {{
        if (!ledgerInfo) return;
        const total = ledgerState.filteredRows.length;
        const totalPages = Math.max(1, Math.ceil(total / ledgerState.pageSize));
        ledgerState.page = Math.max(1, Math.min(ledgerState.page, totalPages));
        ledgerInfo.textContent = `Rows: ${{total}} | Page: ${{ledgerState.page}} / ${{totalPages}}`;
      }};

      const renderLedgerRows = () => {{
        if (!ledgerBody) return;
        const selected = filter ? filter.value : "all";
        const base = selected === "all"
          ? ledgerState.filteredRows
          : ledgerState.filteredRows.filter((row) => String(row.trade_id) === selected);
        const totalPages = Math.max(1, Math.ceil(base.length / ledgerState.pageSize));
        ledgerState.page = Math.max(1, Math.min(ledgerState.page, totalPages));
        const start = (ledgerState.page - 1) * ledgerState.pageSize;
        const end = Math.min(start + ledgerState.pageSize, base.length);
        const rows = base.slice(start, end);
        ledgerBody.innerHTML = rows.map((row) => {{
          const pnl = Number.parseFloat(String(row.net_pnl || "0"));
          const cls = Number.isFinite(pnl) && pnl >= 0 ? "win" : "loss";
          const entryMs = parseUtcMs(row.entry_time);
          const exitMs = parseUtcMs(row.exit_time);
          return (
            "<tr class='trade-row' data-trade-id='" + row.trade_id + "' data-entry-ms='" + (Number.isFinite(entryMs) ? entryMs : "") + "' data-exit-ms='" + (Number.isFinite(exitMs) ? exitMs : "") + "'>" +
            "<td>" + row.trade_id + "</td>" +
            "<td>" + (row.side || "") + "</td>" +
            "<td>" + (row.entry_time || "") + "</td>" +
            "<td>" + (row.exit_time || "") + "</td>" +
            "<td class='num'>" + (row.entry_price || "NA") + "</td>" +
            "<td class='num'>" + (row.exit_price || "NA") + "</td>" +
            "<td class='num'>" + (row.quantity || "NA") + "</td>" +
            "<td class='num " + cls + "'>" + (row.net_pnl || "NA") + "</td>" +
            "<td>" + (row.exit_reason || "") + "</td>" +
            "</tr>"
          );
        }}).join("");
        renderLedgerInfo();
        document.querySelectorAll(".trade-row[data-trade-id]").forEach((el) => {{
          el.addEventListener("mouseenter", () => {{
            const tradeId = el.getAttribute("data-trade-id");
            if (tradeId) renderDetails(tradeId);
          }});
          el.addEventListener("mouseleave", () => {{
            const selectedNow = filter ? filter.value : "all";
            if (selectedNow === "all") restoreDetails();
            else renderDetails(selectedNow);
          }});
        }});
      }};

      const renderDetails = (tradeId) => {{
        if (!detailsCard) return;
        if (!tradeId || !tradeDetails[tradeId]) {{
          restoreDetails();
          return;
        }}
        const d = tradeDetails[tradeId];
        detailsCard.innerHTML =
          "<div class='detail-title'>Trade " + tradeId + " (" + d.side + ")</div>" +
          "<div class='detail-grid'>" +
          "<div class='detail-item'><strong>entry:</strong> " + d.entry_time + "</div>" +
          "<div class='detail-item'><strong>exit:</strong> " + d.exit_time + "</div>" +
          "<div class='detail-item'><strong>entry_px:</strong> " + d.entry_price + "</div>" +
          "<div class='detail-item'><strong>exit_px:</strong> " + d.exit_price + "</div>" +
          "<div class='detail-item'><strong>qty:</strong> " + d.quantity + "</div>" +
          "<div class='detail-item'><strong>gross:</strong> " + d.gross_pnl + "</div>" +
          "<div class='detail-item'><strong>fee:</strong> " + d.fee_cost + "</div>" +
          "<div class='detail-item'><strong>slippage:</strong> " + d.slippage_cost + "</div>" +
          "<div class='detail-item'><strong>funding:</strong> " + d.funding_cost + "</div>" +
          "<div class='detail-item'><strong>net:</strong> " + d.net_pnl + "</div>" +
          "<div class='detail-item'><strong>holding_bars:</strong> " + d.holding_bars + "</div>" +
          "<div class='detail-item'><strong>exit_reason:</strong> " + d.exit_reason + "</div>" +
          "</div>";
      }};

      const applyKlineWindow = (tradeId) => {{
        if (!klineSvg || !klineBaseViewBox) return;
        const activeRange = getActiveRange();
        if (!tradeId || !tradeBars[tradeId]) {{
          applyKlineRangeView(activeRange.startMs, activeRange.endMs);
          return;
        }}
        const span = tradeBars[tradeId];
        const entryIdx = Number(span.entry_idx);
        const exitIdx = Number(span.exit_idx);
        if (!Number.isFinite(entryIdx) || !Number.isFinite(exitIdx)) {{
          applyTimeRangeView(klineSvg, klineBaseViewBox, activeRange.startMs, activeRange.endMs);
          return;
        }}
        const chartWidth = Number(klineSvg.dataset.chartWidth || 0);
        const chartHeight = Number(klineSvg.dataset.chartHeight || 0);
        const marginLeft = Number(klineSvg.dataset.marginLeft || 0);
        const marginRight = Number(klineSvg.dataset.marginRight || 0);
        const barCount = Number(klineSvg.dataset.barCount || 0);
        if (!(chartWidth > 0 && chartHeight > 0 && barCount > 0)) {{
          applyKlineRangeView(activeRange.startMs, activeRange.endMs);
          return;
        }}
        const windowBars = Math.max(1, Math.min(300, Number.parseInt((windowBarsInput && windowBarsInput.value) || "24", 10) || 24));
        let leftIdx = Math.max(0, Math.min(entryIdx, exitIdx) - windowBars);
        let rightIdx = Math.min(barCount - 1, Math.max(entryIdx, exitIdx) + windowBars);
        const minMs = Number(klineSvg.dataset.minMs || NaN);
        const maxMs = Number(klineSvg.dataset.maxMs || NaN);
        if (Number.isFinite(activeRange.startMs) && Number.isFinite(activeRange.endMs) && Number.isFinite(minMs) && Number.isFinite(maxMs) && maxMs > minMs) {{
          const leftByRange = Math.floor(((activeRange.startMs - minMs) / (maxMs - minMs)) * (barCount - 1));
          const rightByRange = Math.ceil(((activeRange.endMs - minMs) / (maxMs - minMs)) * (barCount - 1));
          leftIdx = Math.max(leftIdx, Math.max(0, Math.min(barCount - 1, leftByRange)));
          rightIdx = Math.min(rightIdx, Math.max(0, Math.min(barCount - 1, rightByRange)));
          if (rightIdx <= leftIdx) {{
            applyKlineRangeView(activeRange.startMs, activeRange.endMs);
            return;
          }}
        }}
        const innerWidth = chartWidth - marginLeft - marginRight;
        const step = innerWidth / Math.max(barCount, 1);
        const xLeft = marginLeft + leftIdx * step;
        const xRight = marginLeft + (rightIdx + 1) * step;
        const pad = Math.max(6.0, step * 0.8);
        let viewWidth = Math.max(80.0, xRight - xLeft + pad * 2.0);
        viewWidth = Math.min(viewWidth, chartWidth);
        let viewX = xLeft - pad;
        viewX = Math.max(0.0, Math.min(viewX, chartWidth - viewWidth));
        klineSvg.setAttribute("viewBox", viewX.toFixed(2) + " 0 " + viewWidth.toFixed(2) + " " + chartHeight.toFixed(2));
      }};

      const findBarIndexByMs = (ms) => {{
        if (!Number.isFinite(ms) || klineBars.length === 0) return null;
        let lo = 0;
        let hi = klineBars.length - 1;
        while (lo < hi) {{
          const mid = Math.floor((lo + hi) / 2);
          const value = Number.parseFloat(String((klineBars[mid] && klineBars[mid][0]) || "NaN"));
          if (!Number.isFinite(value) || value < ms) lo = mid + 1;
          else hi = mid;
        }}
        const idx = Math.max(0, Math.min(klineBars.length - 1, lo));
        const curr = Number.parseFloat(String((klineBars[idx] && klineBars[idx][0]) || "NaN"));
        if (idx <= 0 || !Number.isFinite(curr)) return idx;
        const prev = Number.parseFloat(String((klineBars[idx - 1] && klineBars[idx - 1][0]) || "NaN"));
        if (!Number.isFinite(prev)) return idx;
        return Math.abs(curr - ms) < Math.abs(ms - prev) ? idx : (idx - 1);
      }};

      const resolveVisibleRangeFromChart = () => {{
        if (!klineChart || klineBars.length === 0) return {{ startMs: null, endMs: null }};
        const option = klineChart.getOption ? klineChart.getOption() : null;
        const zooms = Array.isArray(option && option.dataZoom) ? option.dataZoom : [];
        const zoom = zooms.find((item) => item && (item.id === "insideZoom" || item.id === "sliderZoom")) || zooms[0];
        const count = klineBars.length;
        if (count <= 0) {{
          return {{ startMs: null, endMs: null }};
        }}
        let startIdx = Number.parseInt(String(zoom && zoom.startValue !== undefined ? zoom.startValue : "NaN"), 10);
        let endIdx = Number.parseInt(String(zoom && zoom.endValue !== undefined ? zoom.endValue : "NaN"), 10);
        if (!Number.isFinite(startIdx) || !Number.isFinite(endIdx)) {{
          const startPct = Number.parseFloat(String(zoom && zoom.start !== undefined ? zoom.start : "0"));
          const endPct = Number.parseFloat(String(zoom && zoom.end !== undefined ? zoom.end : "100"));
          if (Number.isFinite(startPct) && Number.isFinite(endPct) && count > 1) {{
            startIdx = Math.floor((Math.max(0, Math.min(100, startPct)) / 100.0) * (count - 1));
            endIdx = Math.ceil((Math.max(0, Math.min(100, endPct)) / 100.0) * (count - 1));
          }}
        }}
        if (!Number.isFinite(startIdx) || !Number.isFinite(endIdx)) {{
          const startMsFromValue = Number.parseFloat(String(zoom && zoom.startValue !== undefined ? zoom.startValue : "NaN"));
          const endMsFromValue = Number.parseFloat(String(zoom && zoom.endValue !== undefined ? zoom.endValue : "NaN"));
          if (Number.isFinite(startMsFromValue) && Number.isFinite(endMsFromValue)) {{
            startIdx = findBarIndexByMs(startMsFromValue);
            endIdx = findBarIndexByMs(endMsFromValue);
          }}
        }}
        if (!Number.isFinite(startIdx) || !Number.isFinite(endIdx)) return {{ startMs: null, endMs: null }};
        if (endIdx < startIdx) {{
          const tmp = startIdx;
          startIdx = endIdx;
          endIdx = tmp;
        }}
        startIdx = Math.max(0, Math.min(count - 1, startIdx));
        endIdx = Math.max(0, Math.min(count - 1, endIdx));
        const startMs = Number.parseFloat(String((klineBars[startIdx] && klineBars[startIdx][0]) || "NaN"));
        const endMs = Number.parseFloat(String((klineBars[endIdx] && klineBars[endIdx][0]) || "NaN"));
        if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return {{ startMs: null, endMs: null }};
        return {{ startMs, endMs }};
      }};

      const resolvePriceAxisRange = (leftIdx, rightIdx) => {{
        if (!Number.isFinite(leftIdx) || !Number.isFinite(rightIdx) || rightIdx < leftIdx) {{
          return {{ min: undefined, max: undefined }};
        }}
        let low = Number.POSITIVE_INFINITY;
        let high = Number.NEGATIVE_INFINITY;
        for (let idx = leftIdx; idx <= rightIdx; idx += 1) {{
          const bar = klineBars[idx];
          if (!bar) continue;
          const barHigh = Number.parseFloat(String(bar[2] || "NaN"));
          const barLow = Number.parseFloat(String(bar[3] || "NaN"));
          if (Number.isFinite(barHigh)) high = Math.max(high, barHigh);
          if (Number.isFinite(barLow)) low = Math.min(low, barLow);
        }}
        if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) {{
          return {{ min: undefined, max: undefined }};
        }}
        const span = high - low;
        const pad = Math.max(1e-9, span * 0.08);
        return {{ min: low - pad, max: high + pad }};
      }};

      const initKlineEchart = () => {{
        if (!canUseEchartKline || klineChart) return;
        if (klineEchartRoot) {{
          klineEchartRoot.style.display = "";
          klineEchartRoot.style.visibility = "visible";
        }}
        klineChart = window.echarts.init(klineEchartRoot, null, {{ renderer: "canvas" }});
        const category = klineBars.map((bar) => Number.parseFloat(String((bar && bar[0]) || "NaN")));
        const candles = klineBars.map((bar) => ([
          Number.parseFloat(String((bar && bar[1]) || "0")),
          Number.parseFloat(String((bar && bar[4]) || "0")),
          Number.parseFloat(String((bar && bar[3]) || "0")),
          Number.parseFloat(String((bar && bar[2]) || "0")),
        ]));
        klineChart.setOption(
          {{
            animation: false,
            tooltip: {{
              trigger: "axis",
              axisPointer: {{ type: "cross" }},
            }},
            grid: {{ left: 62, right: 28, top: 18, bottom: 72 }},
            xAxis: {{
              type: "category",
              data: category,
              boundaryGap: true,
              axisLine: {{ lineStyle: {{ color: "#94a3b8" }} }},
              axisLabel: {{
                color: "#64748b",
                formatter: (value) => {{
                  const raw = Number.parseFloat(String(value));
                  if (!Number.isFinite(raw)) return "";
                  const d = new Date(raw);
                  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
                  const dd = String(d.getUTCDate()).padStart(2, "0");
                  const hh = String(d.getUTCHours()).padStart(2, "0");
                  const mi = String(d.getUTCMinutes()).padStart(2, "0");
                  return `${{mm}}-${{dd}} ${{hh}}:${{mi}}`;
                }},
              }},
            }},
            yAxis: {{
              id: "priceAxis",
              type: "value",
              scale: true,
              axisLabel: {{ color: "#64748b" }},
              splitLine: {{ lineStyle: {{ color: "#e2e8f0" }} }},
            }},
            dataZoom: [
              {{
                id: "insideZoom",
                type: "inside",
                xAxisIndex: 0,
                filterMode: "filter",
              }},
              {{
                id: "sliderZoom",
                type: "slider",
                xAxisIndex: 0,
                height: 18,
                bottom: 18,
                filterMode: "filter",
              }},
            ],
            series: [
              {{
                id: "candles",
                name: "Kline",
                type: "candlestick",
                data: candles,
                itemStyle: {{
                  color: "#16a34a",
                  color0: "#dc2626",
                  borderColor: "#16a34a",
                  borderColor0: "#dc2626",
                }},
              }},
            ],
          }},
          {{ notMerge: true }},
        );
        klineChart.on("datazoom", () => {{
          if (suppressKlineDataZoomSync) return;
          const bounds = resolveRangeBounds();
          const chartRange = resolveVisibleRangeFromChart();
          const normalized = normalizeRange(chartRange.startMs, chartRange.endMs, bounds);
          if (!Number.isFinite(normalized.startMs) || !Number.isFinite(normalized.endMs)) return;
          if (normalized.clamped) {{
            const startIdx = findBarIndexByMs(normalized.startMs);
            const endIdx = findBarIndexByMs(normalized.endMs);
            const maxIdx = Math.max(klineBars.length - 1, 1);
            const clampedStartIdx = Number.isFinite(startIdx) ? Math.max(0, Math.min(maxIdx, startIdx)) : 0;
            const clampedEndIdx = Number.isFinite(endIdx) ? Math.max(0, Math.min(maxIdx, endIdx)) : maxIdx;
            const startPct = Math.max(0.0, Math.min(100.0, (clampedStartIdx / maxIdx) * 100.0));
            const endPct = Math.max(0.0, Math.min(100.0, (clampedEndIdx / maxIdx) * 100.0));
            suppressKlineDataZoomSync = true;
            try {{
              klineChart.dispatchAction({{
                type: "dataZoom",
                dataZoomId: "insideZoom",
                start: startPct,
                end: endPct,
              }});
              klineChart.dispatchAction({{
                type: "dataZoom",
                dataZoomId: "sliderZoom",
                start: startPct,
                end: endPct,
              }});
            }} finally {{
              suppressKlineDataZoomSync = false;
            }}
          }}
          ledgerState.rangeStartMs = normalized.startMs;
          ledgerState.rangeEndMs = normalized.endMs;
          syncRangeInputs(ledgerState.rangeStartMs, ledgerState.rangeEndMs, bounds);
          if (rangePreset) rangePreset.value = "CUSTOM";
          setRangeStatus(normalized.clamped ? "图表缩放超过 10 天，已自动截断到 10 天。" : "");
          applyRangeToPanels();
        }});
        const safeResize = () => {{
          if (!klineChart) return;
          klineChart.resize();
        }};
        window.addEventListener("resize", safeResize);
        if (typeof ResizeObserver !== "undefined" && klineEchartRoot && !klineResizeObserver) {{
          klineResizeObserver = new ResizeObserver(() => {{
            safeResize();
          }});
          klineResizeObserver.observe(klineEchartRoot);
        }}
        requestAnimationFrame(() => safeResize());
        setTimeout(() => safeResize(), 80);
      }};

      const renderKlineEchart = (state) => {{
        if (!canUseEchartKline) return false;
        initKlineEchart();
        if (!klineChart) return false;
        const activeRange = state && state.activeRange ? state.activeRange : {{ startMs: null, endMs: null }};

        const barCount = klineBars.length;
        let leftIdx = 0;
        let rightIdx = Math.max(0, barCount - 1);
        if (Number.isFinite(activeRange.startMs) && Number.isFinite(activeRange.endMs)) {{
          const fromIdx = findBarIndexByMs(activeRange.startMs);
          const toIdx = findBarIndexByMs(activeRange.endMs);
          if (Number.isFinite(fromIdx) && Number.isFinite(toIdx)) {{
            leftIdx = Math.max(0, Math.min(fromIdx, toIdx));
            rightIdx = Math.min(barCount - 1, Math.max(fromIdx, toIdx));
          }}
        }}
        if ((rightIdx - leftIdx + 1) > MAX_BARS_PER_VIEW) {{
          leftIdx = Math.max(0, rightIdx - MAX_BARS_PER_VIEW + 1);
        }}
        if (rightIdx <= leftIdx) {{
          leftIdx = 0;
          rightIdx = Math.max(0, barCount - 1);
        }}
        const priceAxisBounds = resolvePriceAxisRange(leftIdx, rightIdx);
        const maxIdx = Math.max(barCount - 1, 1);
        const startPct = Math.max(0.0, Math.min(100.0, (leftIdx / maxIdx) * 100.0));
        const endPct = Math.max(0.0, Math.min(100.0, (rightIdx / maxIdx) * 100.0));

        klineChart.setOption(
          {{
            dataZoom: [
              {{
                id: "insideZoom",
                start: startPct,
                end: endPct,
              }},
              {{
                id: "sliderZoom",
                start: startPct,
                end: endPct,
              }},
            ],
            yAxis: {{
              id: "priceAxis",
              show: true,
              min: Number.isFinite(priceAxisBounds.min) ? priceAxisBounds.min : undefined,
              max: Number.isFinite(priceAxisBounds.max) ? priceAxisBounds.max : undefined,
            }},
          }},
          {{ notMerge: false }},
        );
        suppressKlineDataZoomSync = true;
        try {{
          klineChart.dispatchAction({{
            type: "dataZoom",
            dataZoomId: "insideZoom",
            start: startPct,
            end: endPct,
          }});
          klineChart.dispatchAction({{
            type: "dataZoom",
            dataZoomId: "sliderZoom",
            start: startPct,
            end: endPct,
          }});
        }} finally {{
          suppressKlineDataZoomSync = false;
        }}
        return true;
      }};

      if (!filter) {{
        restoreDetails();
        return;
      }}
      const apply = () => {{
        const selected = filter.value;
        const activeRange = getActiveRange();
        const spotlightEnabled = Boolean(klineMode && klineMode.value === "spotlight");
        const visibleTradeIds = new Set();
        const klineTradeMeta = klineTradeMetaFromPayload.size > 0 ? new Map(klineTradeMetaFromPayload) : new Map();
        if (klineTradeMeta.size === 0) {{
          document.querySelectorAll(".kline-trade[data-trade-id]").forEach((el) => {{
            const tradeId = el.getAttribute("data-trade-id");
            if (!tradeId || klineTradeMeta.has(tradeId)) return;
            const entryMs = Number.parseFloat(el.getAttribute("data-entry-ms") || "NaN");
            const exitMs = Number.parseFloat(el.getAttribute("data-exit-ms") || "NaN");
            klineTradeMeta.set(tradeId, {{
              entryMs,
              exitMs: Number.isFinite(exitMs) ? exitMs : entryMs,
            }});
          }});
        }}
        if (selected !== "all") {{
          const meta = klineTradeMeta.get(selected);
          const inRange = !meta
            ? true
            : (!Number.isFinite(activeRange.startMs) || !Number.isFinite(activeRange.endMs)
              ? true
              : intersects(meta.entryMs, meta.exitMs, activeRange.startMs, activeRange.endMs));
          if (inRange) visibleTradeIds.add(selected);
        }} else if (spotlightEnabled) {{
          klineTradeMeta.forEach((_meta, tradeId) => visibleTradeIds.add(tradeId));
        }} else {{
          const ranged = [];
          klineTradeMeta.forEach((meta, tradeId) => {{
            const inRange = !Number.isFinite(activeRange.startMs) || !Number.isFinite(activeRange.endMs)
              ? true
              : intersects(meta.entryMs, meta.exitMs, activeRange.startMs, activeRange.endMs);
            if (!inRange) return;
            ranged.push({{ tradeId, entryMs: Number.isFinite(meta.entryMs) ? meta.entryMs : 0 }});
          }});
          ranged.sort((a, b) => a.entryMs - b.entryMs);
          if (ranged.length <= MAX_RANGE_KLINE_MARKERS) {{
            ranged.forEach((item) => visibleTradeIds.add(item.tradeId));
          }} else {{
            const step = ranged.length / MAX_RANGE_KLINE_MARKERS;
            for (let idx = 0; idx < MAX_RANGE_KLINE_MARKERS; idx += 1) {{
              const pick = ranged[Math.floor(idx * step)];
              if (pick) visibleTradeIds.add(pick.tradeId);
            }}
          }}
        }}
        document.querySelectorAll("[data-trade-id]").forEach((el) => {{
          const tradeId = el.getAttribute("data-trade-id");
          const matched = selected === "all" || tradeId === selected;
          const entryMs = Number.parseFloat(el.getAttribute("data-entry-ms") || "NaN");
          const exitMs = Number.parseFloat(el.getAttribute("data-exit-ms") || "NaN");
          const inRange = !Number.isFinite(activeRange.startMs) || !Number.isFinite(activeRange.endMs)
            ? true
            : (Number.isFinite(entryMs)
              ? intersects(entryMs, Number.isFinite(exitMs) ? exitMs : entryMs, activeRange.startMs, activeRange.endMs)
              : true);
          if (el.tagName === "TR") {{
            el.style.display = (matched && inRange) ? "" : "none";
          }} else {{
            const sampled = !el.classList.contains("kline-trade") || (tradeId ? visibleTradeIds.has(tradeId) : true);
            const visible = matched && inRange && sampled;
            el.style.display = visible ? "" : "none";
            el.style.opacity = visible ? "1" : "0.12";
          }}
        }});
        if (selected === "all") {{
          restoreDetails();
        }} else {{
          renderDetails(selected);
        }}
        renderKlineEchart({{
          selected,
          activeRange,
          spotlightEnabled,
          visibleTradeIds,
        }});
        if (isChunkedLedger) {{
          ledgerState.page = 1;
          renderLedgerRows();
        }}
      }};
      filter.addEventListener("change", apply);
      if (windowBarsInput) {{
        windowBarsInput.addEventListener("input", () => {{
          if (!klineMode || klineMode.value !== "spotlight") return;
          apply();
        }});
      }}
      if (klineMode) {{
        klineMode.addEventListener("change", apply);
      }}
      document.querySelectorAll("[data-trade-id]").forEach((el) => {{
        el.addEventListener("mouseenter", () => {{
          const tradeId = el.getAttribute("data-trade-id");
          if (tradeId) {{
            renderDetails(tradeId);
          }}
        }});
        el.addEventListener("mouseleave", () => {{
          const selected = filter.value;
          if (selected === "all") {{
            restoreDetails();
          }} else {{
            renderDetails(selected);
          }}
        }});
      }});
      document.querySelectorAll(".timeline-event[data-action-id]").forEach((el) => {{
        el.addEventListener("mouseenter", () => {{
          if (!timelineDetailsCard) return;
          el.style.opacity = "1";
          const actionId = el.getAttribute("data-action-id") || "NA";
          const action = el.getAttribute("data-action") || "NA";
          const reason = el.getAttribute("data-reason") || "NA";
          const signalTime = el.getAttribute("data-signal-time") || "NA";
          const executionTime = el.getAttribute("data-execution-time") || "NA";
          const lagMs = Number.parseFloat(el.getAttribute("data-lag-ms") || "0");
          const lagSec = Number.isFinite(lagMs) ? (lagMs / 1000.0).toFixed(2) : "NA";
          timelineDetailsCard.innerHTML =
            "<div class='detail-title'>Timeline Event " + actionId + "</div>" +
            "<div class='detail-grid'>" +
            "<div class='detail-item'><strong>action:</strong> " + action + "</div>" +
            "<div class='detail-item'><strong>reason:</strong> " + reason + "</div>" +
            "<div class='detail-item'><strong>signal_time:</strong> " + signalTime + "</div>" +
            "<div class='detail-item'><strong>execution_time:</strong> " + executionTime + "</div>" +
            "<div class='detail-item'><strong>lag:</strong> " + lagSec + " s</div>" +
            "</div>";
        }});
        el.addEventListener("mouseleave", () => {{
          el.style.opacity = "";
          restoreTimelineDetails();
        }});
      }});
      if (pageSizeSelect) {{
        pageSizeSelect.addEventListener("change", () => {{
          const v = Number.parseInt(pageSizeSelect.value, 10);
          ledgerState.pageSize = Number.isFinite(v) ? Math.max(10, Math.min(1000, v)) : 100;
          ledgerState.page = 1;
          if (isChunkedLedger) renderLedgerRows();
        }});
      }}
      if (ledgerPrev) {{
        ledgerPrev.addEventListener("click", () => {{
          ledgerState.page = Math.max(1, ledgerState.page - 1);
          if (isChunkedLedger) renderLedgerRows();
        }});
      }}
      if (ledgerNext) {{
        ledgerNext.addEventListener("click", () => {{
          ledgerState.page += 1;
          if (isChunkedLedger) renderLedgerRows();
        }});
      }}
      if (rangePreset) {{
        rangePreset.addEventListener("change", () => {{
          setPresetRange();
          if (isChunkedLedger && rangePreset.value !== "CUSTOM") {{
            loadLedgerRowsForRange().then(() => {{
              ledgerState.page = 1;
              apply();
            }});
            return;
          }}
          apply();
        }});
      }}
      if (applyRangeBtn) {{
        applyRangeBtn.addEventListener("click", () => {{
          const bounds = resolveRangeBounds();
          const startMs = parseUtcMs(rangeStart ? rangeStart.value : "");
          const endMs = parseUtcMs(rangeEnd ? rangeEnd.value : "");
          const normalized = normalizeRange(startMs, endMs, bounds);
          if (Number.isFinite(normalized.startMs)) ledgerState.rangeStartMs = normalized.startMs;
          if (Number.isFinite(normalized.endMs)) ledgerState.rangeEndMs = normalized.endMs;
          syncRangeInputs(ledgerState.rangeStartMs, ledgerState.rangeEndMs, bounds);
          setRangeStatus(normalized.clamped ? "自定义区间超过 10 天，已自动截断到 10 天。" : "");
          if (rangePreset) rangePreset.value = "CUSTOM";
          if (isChunkedLedger) {{
            loadLedgerRowsForRange().then(() => {{
              ledgerState.page = 1;
              apply();
            }});
            return;
          }}
          apply();
        }});
      }}
      setPresetRange();
      if (isChunkedLedger) {{
        loadLedgerRowsForRange()
          .then(() => {{
            ledgerState.pageSize = Number.parseInt((pageSizeSelect && pageSizeSelect.value) || "100", 10) || 100;
            renderLedgerRows();
            apply();
          }})
          .catch((error) => {{
            if (ledgerInfo) ledgerInfo.textContent = `Ledger load failed: ${{error}}`;
            apply();
          }});
      }} else {{
        apply();
      }}
    }})();
  </script>
</body>
</html>
"""


def _build_trade_replay_payload(*, prices: pd.DataFrame, trades: pd.DataFrame, max_trades: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"trade_bars": {}, "trade_details": {}}
    if trades.empty:
        return payload
    bars_ms: list[int] = []
    if not prices.empty and "timestamp" in prices.columns:
        bars_ms = [int(pd.Timestamp(ts).value // 1_000_000) for ts in prices["timestamp"]]
    frame = trades.copy().reset_index(drop=True)
    frame["trade_id"] = np.arange(1, len(frame.index) + 1, dtype="int64")
    if max_trades is not None and max_trades > 0 and len(frame.index) > max_trades:
        frame = frame.iloc[-max_trades:].copy()
    for index, row in frame.iterrows():
        trade_id = str(int(row.get("trade_id", index + 1)))
        payload["trade_details"][trade_id] = {
            "side": escape(str(row.get("side", ""))),
            "entry_time": _format_timestamp(row.get("entry_time")),
            "exit_time": _format_timestamp(row.get("exit_time")),
            "entry_price": _format_float(row.get("entry_price", 0.0), digits=6),
            "exit_price": _format_float(row.get("exit_price", 0.0), digits=6),
            "quantity": _format_float(row.get("quantity", 0.0), digits=6),
            "gross_pnl": _format_float(row.get("gross_pnl", 0.0), digits=6),
            "fee_cost": _format_float(row.get("fee_cost", 0.0), digits=6),
            "slippage_cost": _format_float(row.get("slippage_cost", 0.0), digits=6),
            "funding_cost": _format_float(row.get("funding_cost", 0.0), digits=6),
            "net_pnl": _format_float(row.get("net_pnl", 0.0), digits=6),
            "holding_bars": str(_coalesce_int(row.get("holding_bars"), 0) or 0),
            "exit_reason": escape(str(row.get("exit_reason", ""))),
        }
        if not bars_ms:
            continue
        entry_ts = pd.to_datetime(row.get("entry_time"), utc=True, errors="coerce")
        exit_ts = pd.to_datetime(row.get("exit_time"), utc=True, errors="coerce")
        if pd.isna(entry_ts) or pd.isna(exit_ts):
            continue
        entry_idx = _nearest_bar_index(target_ms=int(entry_ts.value // 1_000_000), bars_ms=bars_ms)
        exit_idx = _nearest_bar_index(target_ms=int(exit_ts.value // 1_000_000), bars_ms=bars_ms)
        if entry_idx is None or exit_idx is None:
            continue
        payload["trade_bars"][trade_id] = {
            "entry_idx": int(entry_idx),
            "exit_idx": int(exit_idx),
        }
    return payload


def _build_kline_chart_payload(
    *,
    prices: pd.DataFrame,
    trades: pd.DataFrame,
    equity_curve: pd.DataFrame | None,
    action_events: pd.DataFrame | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"bars": [], "trades": [], "equity": [], "events": []}
    if prices.empty:
        return payload
    bars_ms = [int(pd.Timestamp(ts).value // 1_000_000) for ts in prices["timestamp"]]
    bars: list[list[float]] = []
    for row in prices.itertuples(index=False):
        ts_ms = int(pd.Timestamp(getattr(row, "timestamp")).value // 1_000_000)
        bars.append(
            [
                float(ts_ms),
                float(getattr(row, "open")),
                float(getattr(row, "high")),
                float(getattr(row, "low")),
                float(getattr(row, "close")),
            ]
        )
    payload["bars"] = bars

    if not trades.empty:
        frame = trades.copy().reset_index(drop=True)
        frame["trade_id"] = np.arange(1, len(frame.index) + 1, dtype="int64")
        if len(frame.index) > _KLINE_CHART_TRADE_META_MAX:
            step = len(frame.index) / float(_KLINE_CHART_TRADE_META_MAX)
            sampled_idx = sorted({min(int(i * step), len(frame.index) - 1) for i in range(_KLINE_CHART_TRADE_META_MAX)})
            if sampled_idx[-1] != len(frame.index) - 1:
                sampled_idx.append(len(frame.index) - 1)
            frame = frame.iloc[sampled_idx].copy()
        trade_rows: list[dict[str, Any]] = []
        for index, row in frame.iterrows():
            trade_id = int(row.get("trade_id", index + 1))
            entry_ts = pd.to_datetime(row.get("entry_time"), utc=True, errors="coerce")
            exit_ts = pd.to_datetime(row.get("exit_time"), utc=True, errors="coerce")
            if pd.isna(entry_ts) or pd.isna(exit_ts):
                continue
            entry_ms = int(entry_ts.value // 1_000_000)
            exit_ms = int(exit_ts.value // 1_000_000)
            entry_idx = _nearest_bar_index(target_ms=entry_ms, bars_ms=bars_ms)
            exit_idx = _nearest_bar_index(target_ms=exit_ms, bars_ms=bars_ms)
            if entry_idx is None or exit_idx is None:
                continue
            entry_price = _coalesce_float(row.get("entry_mark_price"), None)
            if entry_price is None:
                entry_price = _coalesce_float(row.get("entry_price"), None)
            exit_price = _coalesce_float(row.get("exit_mark_price"), None)
            if exit_price is None:
                exit_price = _coalesce_float(row.get("exit_price"), None)
            if entry_price is None or exit_price is None:
                continue
            trade_rows.append(
                {
                    "trade_id": str(trade_id),
                    "side": str(row.get("side", "")).upper(),
                    "entry_ms": entry_ms,
                    "exit_ms": exit_ms,
                    "entry_idx": int(entry_idx),
                    "exit_idx": int(exit_idx),
                    "entry_price": float(entry_price),
                    "exit_price": float(exit_price),
                    "net_pnl": float(_coalesce_float(row.get("net_pnl"), 0.0) or 0.0),
                }
            )
        payload["trades"] = trade_rows

    if equity_curve is not None and not equity_curve.empty and {"timestamp", "equity"}.issubset(equity_curve.columns):
        frame = equity_curve.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
        frame = frame.dropna(subset=["timestamp", "equity"]).sort_values("timestamp").reset_index(drop=True)
        if len(frame.index) > _KLINE_EQUITY_META_MAX:
            step = len(frame.index) / float(_KLINE_EQUITY_META_MAX)
            sampled_idx = sorted({min(int(i * step), len(frame.index) - 1) for i in range(_KLINE_EQUITY_META_MAX)})
            if sampled_idx[-1] != len(frame.index) - 1:
                sampled_idx.append(len(frame.index) - 1)
            frame = frame.iloc[sampled_idx].copy()
        payload["equity"] = [
            [float(int(pd.Timestamp(ts).value // 1_000_000)), float(eq)]
            for ts, eq in frame[["timestamp", "equity"]].itertuples(index=False, name=None)
        ]

    if action_events is not None and not action_events.empty:
        frame = action_events.copy()
        frame["signal_time"] = pd.to_datetime(frame["signal_time"], utc=True, errors="coerce")
        frame["execution_time"] = pd.to_datetime(frame["execution_time"], utc=True, errors="coerce")
        frame["action"] = frame["action"].astype(str)
        frame["reason"] = frame["reason"].astype(str)
        frame = frame.dropna(subset=["signal_time", "execution_time"]).sort_values("signal_time").reset_index(drop=True)
        if len(frame.index) > _KLINE_SIGNAL_META_MAX:
            step = len(frame.index) / float(_KLINE_SIGNAL_META_MAX)
            sampled_idx = sorted({min(int(i * step), len(frame.index) - 1) for i in range(_KLINE_SIGNAL_META_MAX)})
            if sampled_idx[-1] != len(frame.index) - 1:
                sampled_idx.append(len(frame.index) - 1)
            frame = frame.iloc[sampled_idx].copy()
        payload["events"] = [
            [
                float(int(pd.Timestamp(signal_time).value // 1_000_000)),
                float(int(pd.Timestamp(execution_time).value // 1_000_000)),
                str(action),
                str(reason),
            ]
            for signal_time, execution_time, action, reason in frame[
                ["signal_time", "execution_time", "action", "reason"]
            ].itertuples(index=False, name=None)
        ]
    elif not trades.empty:
        frame = trades.copy().reset_index(drop=True)
        frame["entry_time"] = pd.to_datetime(frame["entry_time"], utc=True, errors="coerce")
        frame["exit_time"] = pd.to_datetime(frame["exit_time"], utc=True, errors="coerce")
        frame["side"] = frame["side"].astype(str).str.upper()
        frame = frame.dropna(subset=["entry_time", "exit_time"]).sort_values("entry_time").reset_index(drop=True)
        if len(frame.index) > _KLINE_SIGNAL_META_MAX:
            step = len(frame.index) / float(_KLINE_SIGNAL_META_MAX)
            sampled_idx = sorted({min(int(i * step), len(frame.index) - 1) for i in range(_KLINE_SIGNAL_META_MAX)})
            if sampled_idx[-1] != len(frame.index) - 1:
                sampled_idx.append(len(frame.index) - 1)
            frame = frame.iloc[sampled_idx].copy()
        events: list[list[Any]] = []
        for row in frame.itertuples(index=False):
            side = str(getattr(row, "side", "")).upper()
            events.append(
                [
                    float(int(pd.Timestamp(getattr(row, "entry_time")).value // 1_000_000)),
                    float(int(pd.Timestamp(getattr(row, "entry_time")).value // 1_000_000)),
                    f"ENTER_{side}" if side else "ENTER",
                    "from_trades_fallback",
                ]
            )
            events.append(
                [
                    float(int(pd.Timestamp(getattr(row, "exit_time")).value // 1_000_000)),
                    float(int(pd.Timestamp(getattr(row, "exit_time")).value // 1_000_000)),
                    "EXIT",
                    str(getattr(row, "exit_reason", "")),
                ]
            )
        payload["events"] = events
    return payload


def _build_dashboard_time_bounds(
    *,
    prices: pd.DataFrame,
    action_events: pd.DataFrame,
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, str | None]:
    timestamps: list[pd.Timestamp] = []
    if not prices.empty and "timestamp" in prices.columns:
        values = pd.to_datetime(prices["timestamp"], utc=True, errors="coerce").dropna()
        if not values.empty:
            timestamps.append(pd.Timestamp(values.iloc[0]))
            timestamps.append(pd.Timestamp(values.iloc[-1]))
    if not action_events.empty:
        for column in ("signal_time", "execution_time"):
            if column in action_events.columns:
                values = pd.to_datetime(action_events[column], utc=True, errors="coerce").dropna()
                if not values.empty:
                    timestamps.append(pd.Timestamp(values.iloc[0]))
                    timestamps.append(pd.Timestamp(values.iloc[-1]))
    if not equity_curve.empty and "timestamp" in equity_curve.columns:
        values = pd.to_datetime(equity_curve["timestamp"], utc=True, errors="coerce").dropna()
        if not values.empty:
            timestamps.append(pd.Timestamp(values.iloc[0]))
            timestamps.append(pd.Timestamp(values.iloc[-1]))
    if not trades.empty:
        for column in ("entry_time", "exit_time"):
            if column in trades.columns:
                values = pd.to_datetime(trades[column], utc=True, errors="coerce").dropna()
                if not values.empty:
                    timestamps.append(pd.Timestamp(values.iloc[0]))
                    timestamps.append(pd.Timestamp(values.iloc[-1]))
    if not timestamps:
        return {"min_time": None, "max_time": None}
    min_ts = min(timestamps)
    max_ts = max(timestamps)
    return {"min_time": min_ts.isoformat(), "max_time": max_ts.isoformat()}


def _json_for_script(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True).replace("<", "\\u003c")


def _write_trade_ledger_chunks(*, report_root: Path, trades: pd.DataFrame) -> str:
    chunk_root = report_root / "chunks"
    chunk_root.mkdir(parents=True, exist_ok=True)
    manifest_path = report_root / _LEDGER_MANIFEST_FILENAME
    if trades.empty:
        payload = {
            "version": "v1",
            "total_trades": 0,
            "min_entry_time": None,
            "max_entry_time": None,
            "chunks": [],
        }
        manifest_path.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
        return manifest_path.name

    frame = trades.copy().reset_index(drop=True)
    frame["trade_id"] = np.arange(1, len(frame.index) + 1, dtype="int64")
    frame["entry_time"] = pd.to_datetime(frame["entry_time"], utc=True, errors="coerce")
    frame["exit_time"] = pd.to_datetime(frame["exit_time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["entry_time"]).sort_values("entry_time").copy()
    frame["chunk_id"] = frame["entry_time"].dt.strftime("%Y_%m")
    chunks_meta: list[dict[str, Any]] = []
    for chunk_id, group in frame.groupby("chunk_id", sort=True):
        rows: list[dict[str, Any]] = []
        for row in group.itertuples(index=False):
            rows.append(
                {
                    "trade_id": int(row.trade_id),
                    "side": str(getattr(row, "side", "")),
                    "entry_time": pd.Timestamp(row.entry_time).isoformat(),
                    "exit_time": _format_timestamp(getattr(row, "exit_time", None)),
                    "entry_price": _format_float(getattr(row, "entry_price", np.nan), digits=6),
                    "exit_price": _format_float(getattr(row, "exit_price", np.nan), digits=6),
                    "quantity": _format_float(getattr(row, "quantity", np.nan), digits=6),
                    "gross_pnl": _format_float(getattr(row, "gross_pnl", np.nan), digits=6),
                    "fee_cost": _format_float(getattr(row, "fee_cost", np.nan), digits=6),
                    "slippage_cost": _format_float(getattr(row, "slippage_cost", np.nan), digits=6),
                    "funding_cost": _format_float(getattr(row, "funding_cost", np.nan), digits=6),
                    "net_pnl": _format_float(getattr(row, "net_pnl", np.nan), digits=6),
                    "holding_bars": str(_coalesce_int(getattr(row, "holding_bars", 0), 0) or 0),
                    "exit_reason": str(getattr(row, "exit_reason", "")),
                }
            )
        file_name = f"{_LEDGER_CHUNK_FILE_PREFIX}{chunk_id}.json"
        file_path = chunk_root / file_name
        file_path.write_text(
            json.dumps({"chunk_id": chunk_id, "rows": rows}, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )
        chunk_start = pd.Timestamp(group["entry_time"].iloc[0]).isoformat()
        chunk_end = pd.Timestamp(group["entry_time"].iloc[-1]).isoformat()
        chunks_meta.append(
            {
                "id": chunk_id,
                "file": f"chunks/{file_name}",
                "start": chunk_start,
                "end": chunk_end,
                "rows": int(len(group.index)),
            }
        )

    min_entry = pd.Timestamp(frame["entry_time"].iloc[0]).isoformat()
    max_entry = pd.Timestamp(frame["entry_time"].iloc[-1]).isoformat()
    manifest_payload = {
        "version": "v1",
        "total_trades": int(len(frame.index)),
        "min_entry_time": min_entry,
        "max_entry_time": max_entry,
        "chunks": chunks_meta,
    }
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    return manifest_path.name


def _prepare_dashboard_prices(*, price_frame: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    if price_frame is None or price_frame.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    required = {"timestamp", "symbol", "close"}
    if not required.issubset(price_frame.columns):
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    frame = price_frame.copy()
    has_open = "open" in frame.columns
    has_high = "high" in frame.columns
    has_low = "low" in frame.columns
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    for column in ("open", "high", "low"):
        if column not in frame.columns:
            frame[column] = frame["close"]
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["open"] = frame["open"].fillna(frame["close"])
    frame["high"] = frame["high"].fillna(frame["close"])
    frame["low"] = frame["low"].fillna(frame["close"])
    filtered = frame[frame["symbol"] == str(symbol).upper()].dropna(subset=["timestamp", "open", "high", "low", "close"])
    if filtered.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    filtered = filtered.sort_values("timestamp").reset_index(drop=True)
    result = filtered[["timestamp", "open", "high", "low", "close"]].copy()
    # Report-only visualization fallback:
    # close-only inputs (or degenerate doji streams) make candles look broken.
    # We synthesize a visual open/high/low from previous close to keep chart readable.
    doji_ratio = float((result["open"] - result["close"]).abs().le(1e-12).mean()) if not result.empty else 0.0
    needs_visual_synth = (not has_open) or (not has_high) or (not has_low) or (doji_ratio >= _DASHBOARD_DOJI_SYNTH_THRESHOLD)
    if needs_visual_synth and not result.empty:
        visual_open = result["close"].shift(1).fillna(result["close"])
        result["open"] = visual_open
        result["high"] = pd.concat([result["high"], result["open"], result["close"]], axis=1).max(axis=1)
        result["low"] = pd.concat([result["low"], result["open"], result["close"]], axis=1).min(axis=1)
    result.attrs["interval_label"] = _infer_interval_label(result["timestamp"])
    return result


def _infer_interval_label(timestamps: pd.Series) -> str:
    values = pd.to_datetime(timestamps, utc=True, errors="coerce").dropna()
    if len(values.index) < 2:
        return "raw"
    diffs = values.diff().dropna()
    if diffs.empty:
        return "raw"
    median_ms = int(diffs.median().total_seconds() * 1000)
    return _interval_label(median_ms)


def _build_overview_candles(*, filtered: pd.DataFrame, max_bars: int) -> tuple[pd.DataFrame, str]:
    candidates: list[tuple[str, str]] = [
        ("5m", "5min"),
        ("1h", "1h"),
        ("4h", "4h"),
        ("1d", "1d"),
    ]
    frame = filtered[["timestamp", "open", "high", "low", "close"]].copy()
    for label, rule in candidates:
        if rule == "5min":
            candidate = frame.copy()
        else:
            candidate = _resample_candles(frame=frame, rule=rule)
        if candidate.empty:
            continue
        if len(candidate.index) <= max_bars:
            return candidate.reset_index(drop=True), label
    fallback = _resample_candles(frame=frame, rule="1d")
    if fallback.empty:
        fallback = frame.copy()
    if len(fallback.index) > max_bars:
        fallback = fallback.iloc[-max_bars:].reset_index(drop=True)
    return fallback.reset_index(drop=True), "1d"


def _resample_candles(*, frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    resampled = (
        frame.set_index("timestamp")[["open", "high", "low", "close"]]
        .resample(rule, label="right", closed="right")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
            }
        )
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    return resampled


def _prepare_dashboard_actions(
    *,
    actions: pd.DataFrame | None,
    symbol: str,
    execution_lag_ms: int,
    max_rows: int | None = _TIMELINE_MAX_ROWS,
) -> pd.DataFrame:
    if actions is None or actions.empty:
        return pd.DataFrame(columns=["signal_time", "execution_time", "action", "reason"])
    required = {"timestamp", "symbol", "action"}
    if not required.issubset(actions.columns):
        return pd.DataFrame(columns=["signal_time", "execution_time", "action", "reason"])
    frame = actions.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["action"] = frame["action"].astype(str)
    if "reason" not in frame.columns:
        frame["reason"] = ""
    frame["reason"] = frame["reason"].astype(str)
    frame = frame[(frame["symbol"] == str(symbol).upper())].dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if frame.empty:
        return pd.DataFrame(columns=["signal_time", "execution_time", "action", "reason"])
    frame["signal_time"] = frame["timestamp"]
    frame["execution_time"] = frame["signal_time"] + pd.to_timedelta(execution_lag_ms, unit="ms")
    output = frame[["signal_time", "execution_time", "action", "reason"]].copy()
    if max_rows is not None and len(output.index) > max_rows:
        output = output.iloc[-max_rows:].reset_index(drop=True)
    return output


def _build_candlestick_svg(*, prices: pd.DataFrame, trades: pd.DataFrame) -> str:
    if prices.empty:
        return "<div class='empty'>No price frame provided for kline rendering.</div>"
    render_prices = prices
    if len(prices.index) > _KLINE_SVG_FALLBACK_MAX_BARS:
        fallback, interval_label = _build_overview_candles(filtered=prices, max_bars=_KLINE_OVERVIEW_MAX_BARS)
        render_prices = fallback
        render_prices.attrs["interval_label"] = f"{interval_label} (fallback)"

    width = 1160.0
    height = 420.0
    margin_left = 62.0
    margin_right = 18.0
    margin_top = 16.0
    margin_bottom = 28.0
    inner_w = width - margin_left - margin_right
    inner_h = height - margin_top - margin_bottom

    lows = render_prices["low"].astype(float)
    highs = render_prices["high"].astype(float)
    y_min = float(lows.min())
    y_max = float(highs.max())
    if y_max <= y_min:
        y_max = y_min + 1e-6
    pad = (y_max - y_min) * 0.05
    y_min -= pad
    y_max += pad

    def y_of(price: float) -> float:
        return margin_top + (y_max - price) / (y_max - y_min) * inner_h

    count = len(render_prices.index)
    step = inner_w / max(count, 1)
    body_w = max(min(step * 0.62, 10.0), 1.2)
    timestamps_ms = [(pd.Timestamp(ts).value // 1_000_000) for ts in render_prices["timestamp"]]
    min_ts_ms = int(timestamps_ms[0]) if timestamps_ms else 0
    max_ts_ms = int(timestamps_ms[-1]) if timestamps_ms else 1
    if max_ts_ms <= min_ts_ms:
        max_ts_ms = min_ts_ms + 1
    interval_label = str(render_prices.attrs.get("interval_label", "5m"))
    base_view_box = f"0 0 {width:.0f} {height:.0f}"

    parts: list[str] = [
        f"<svg id='klineSvg' viewBox='{base_view_box}' data-base-viewbox='{base_view_box}' data-chart-width='{width:.0f}' data-chart-height='{height:.0f}' data-margin-left='{margin_left:.2f}' data-margin-right='{margin_right:.2f}' data-bar-count='{count}' data-min-ms='{min_ts_ms}' data-max-ms='{max_ts_ms}' xmlns='http://www.w3.org/2000/svg'>"
    ]
    parts.append(
        f"<text id='klineOverviewLabel' x='{(width - margin_right - 120):.2f}' y='{(margin_top - 2):.2f}' font-size='11' fill='#64748b'>Overview TF: {escape(interval_label)}</text>"
    )
    for idx in range(6):
        frac = idx / 5.0
        y_line = margin_top + frac * inner_h
        price = y_max - frac * (y_max - y_min)
        parts.append(
            f"<line x1='{margin_left:.2f}' y1='{y_line:.2f}' x2='{(width - margin_right):.2f}' y2='{y_line:.2f}' stroke='#eef2f7' stroke-width='1'/>"
        )
        parts.append(
            f"<text x='8' y='{(y_line + 4):.2f}' font-size='11' fill='#64748b'>{price:.4f}</text>"
        )

    for idx, row in enumerate(render_prices.itertuples(index=False), start=0):
        ts_ms = int(timestamps_ms[idx])
        x_center = margin_left + (idx + 0.5) * step
        open_price = float(row.open)
        high_price = float(row.high)
        low_price = float(row.low)
        close_price = float(row.close)
        y_open = y_of(open_price)
        y_close = y_of(close_price)
        y_high = y_of(high_price)
        y_low = y_of(low_price)
        up = close_price >= open_price
        color = "#16a34a" if up else "#dc2626"
        body_top = min(y_open, y_close)
        body_h = max(abs(y_close - y_open), 1.0)
        parts.append(
            f"<line x1='{x_center:.2f}' y1='{y_high:.2f}' x2='{x_center:.2f}' y2='{y_low:.2f}' stroke='{color}' stroke-width='1.2' class='kline-candle' data-bar-index='{idx}' data-ts-ms='{ts_ms}'/>"
        )
        parts.append(
            f"<rect x='{(x_center - body_w / 2):.2f}' y='{body_top:.2f}' width='{body_w:.2f}' height='{body_h:.2f}' fill='{color}' opacity='0.86' class='kline-candle' data-bar-index='{idx}' data-ts-ms='{ts_ms}'/>"
        )

    if not trades.empty:
        frame = trades.copy().reset_index(drop=True)
        frame["trade_id"] = np.arange(1, len(frame.index) + 1, dtype="int64")
        if len(frame.index) > _KLINE_TRADE_MARKER_MAX:
            frame = frame.iloc[-_KLINE_TRADE_MARKER_MAX:].copy()
        for index, row in frame.iterrows():
            trade_id = int(row.get("trade_id", index + 1))
            entry_ts = pd.to_datetime(row.get("entry_time"), utc=True, errors="coerce")
            exit_ts = pd.to_datetime(row.get("exit_time"), utc=True, errors="coerce")
            if pd.isna(entry_ts) or pd.isna(exit_ts):
                continue
            entry_ms = int(entry_ts.value // 1_000_000)
            exit_ms = int(exit_ts.value // 1_000_000)
            entry_idx = _nearest_bar_index(target_ms=entry_ms, bars_ms=timestamps_ms)
            exit_idx = _nearest_bar_index(target_ms=exit_ms, bars_ms=timestamps_ms)
            if entry_idx is None or exit_idx is None:
                continue
            entry_price = float(row.get("entry_mark_price", row.get("entry_price", np.nan)))
            exit_price = float(row.get("exit_mark_price", row.get("exit_price", np.nan)))
            if np.isnan(entry_price) or np.isnan(exit_price):
                continue
            side = str(row.get("side", "")).upper()
            net_pnl = float(row.get("net_pnl", 0.0))
            x_entry = margin_left + (entry_idx + 0.5) * step
            y_entry = y_of(entry_price)
            x_exit = margin_left + (exit_idx + 0.5) * step
            y_exit = y_of(exit_price)
            entry_color = "#2563eb"
            exit_color = "#16a34a" if net_pnl >= 0.0 else "#dc2626"
            if side == "LONG":
                entry_poly = f"{x_entry:.2f},{(y_entry - 7):.2f} {(x_entry - 6):.2f},{(y_entry + 5):.2f} {(x_entry + 6):.2f},{(y_entry + 5):.2f}"
            else:
                entry_poly = f"{x_entry:.2f},{(y_entry + 7):.2f} {(x_entry - 6):.2f},{(y_entry - 5):.2f} {(x_entry + 6):.2f},{(y_entry - 5):.2f}"
            trade_common = (
                f"class='kline-trade' data-trade-id='{trade_id}' data-entry-ms='{entry_ms}' data-exit-ms='{exit_ms}'"
            )
            parts.append(
                f"<line x1='{x_entry:.2f}' y1='{y_entry:.2f}' x2='{x_exit:.2f}' y2='{y_exit:.2f}' stroke='{entry_color}' stroke-width='1.0' stroke-dasharray='3,3' opacity='0.28' {trade_common}/>"
            )
            parts.append(f"<polygon points='{entry_poly}' fill='{entry_color}' fill-opacity='0.32' {trade_common}/>")
            parts.append(f"<circle cx='{x_exit:.2f}' cy='{y_exit:.2f}' r='4.4' fill='{exit_color}' fill-opacity='0.82' {trade_common}/>")

    if count >= 2:
        first_ts = pd.Timestamp(render_prices["timestamp"].iloc[0]).isoformat()
        last_ts = pd.Timestamp(render_prices["timestamp"].iloc[-1]).isoformat()
        parts.append(
            f"<text x='{margin_left:.2f}' y='{(height - 8):.2f}' font-size='11' fill='#64748b'>{escape(first_ts)}</text>"
        )
        parts.append(
            f"<text x='{(width - margin_right - 190):.2f}' y='{(height - 8):.2f}' font-size='11' fill='#64748b'>{escape(last_ts)}</text>"
        )

    parts.append("</svg>")
    return "".join(parts)


def _build_signal_timeline_svg(
    *,
    action_events: pd.DataFrame,
    signal_tf_label: str,
    execution_tf_label: str,
) -> str:
    if action_events.empty:
        return "<div class='empty'>No action events provided for signal timeline.</div>"
    width = 1160.0
    height = 170.0
    margin_left = 72.0
    margin_right = 18.0
    margin_top = 16.0
    lane_signal = 58.0
    lane_exec = 118.0
    inner_w = width - margin_left - margin_right

    min_time = pd.Timestamp(action_events["signal_time"].min())
    max_time = pd.Timestamp(action_events["execution_time"].max())
    min_ms = int(min_time.value // 1_000_000)
    max_ms = int(max_time.value // 1_000_000)
    if max_ms <= min_ms:
        max_ms = min_ms + 1
    base_view_box = f"0 0 {width:.0f} {height:.0f}"

    def x_of(value: pd.Timestamp) -> float:
        ts_ms = int(pd.Timestamp(value).value // 1_000_000)
        return margin_left + (ts_ms - min_ms) / (max_ms - min_ms) * inner_w

    parts: list[str] = [
        f"<svg id='timelineSvg' viewBox='{base_view_box}' data-base-viewbox='{base_view_box}' data-chart-width='{width:.0f}' data-chart-height='{height:.0f}' data-margin-left='{margin_left:.2f}' data-margin-right='{margin_right:.2f}' data-min-ms='{min_ms}' data-max-ms='{max_ms}' xmlns='http://www.w3.org/2000/svg'>"
    ]
    parts.append(f"<line x1='{margin_left:.2f}' y1='{lane_signal:.2f}' x2='{(width - margin_right):.2f}' y2='{lane_signal:.2f}' stroke='#cbd5e1' stroke-width='1.2'/>")
    parts.append(f"<line x1='{margin_left:.2f}' y1='{lane_exec:.2f}' x2='{(width - margin_right):.2f}' y2='{lane_exec:.2f}' stroke='#cbd5e1' stroke-width='1.2'/>")
    parts.append(f"<text x='8' y='{(lane_signal + 4):.2f}' font-size='11' fill='#64748b'>Signal TF ({escape(signal_tf_label)})</text>")
    parts.append(f"<text x='8' y='{(lane_exec + 4):.2f}' font-size='11' fill='#64748b'>Exec TF ({escape(execution_tf_label)})</text>")

    for action_id, row in enumerate(action_events.itertuples(index=False), start=1):
        signal_t = pd.Timestamp(row.signal_time)
        exec_t = pd.Timestamp(row.execution_time)
        action = str(row.action)
        reason = str(getattr(row, "reason", ""))
        color = _action_color(action)
        x_signal = x_of(signal_t)
        x_exec = x_of(exec_t)
        signal_iso = signal_t.isoformat()
        exec_iso = exec_t.isoformat()
        lag_ms = int(max((exec_t.value - signal_t.value) // 1_000_000, 0))
        signal_ms = int(signal_t.value // 1_000_000)
        exec_ms = int(exec_t.value // 1_000_000)
        action_attr = escape(action, quote=True)
        reason_attr = escape(reason, quote=True)
        signal_attr = escape(signal_iso, quote=True)
        exec_attr = escape(exec_iso, quote=True)
        common = (
            f"class='timeline-event' data-action-id='{action_id}' data-action='{action_attr}' "
            f"data-reason='{reason_attr}' data-signal-time='{signal_attr}' data-execution-time='{exec_attr}' "
            f"data-signal-ms='{signal_ms}' data-execution-ms='{exec_ms}' data-lag-ms='{lag_ms}'"
        )
        parts.append(
            f"<line x1='{x_signal:.2f}' y1='{lane_signal:.2f}' x2='{x_exec:.2f}' y2='{lane_exec:.2f}' stroke='{color}' stroke-width='1' stroke-dasharray='2,2' opacity='0.6' {common}/>"
        )
        parts.append(f"<circle cx='{x_signal:.2f}' cy='{lane_signal:.2f}' r='3.8' fill='{color}' {common}/>")
        parts.append(
            f"<circle cx='{x_exec:.2f}' cy='{lane_exec:.2f}' r='3.8' fill='white' stroke='{color}' stroke-width='1.5' {common}/>"
        )

    parts.append(f"<text x='{margin_left:.2f}' y='{(height - 8):.2f}' font-size='11' fill='#64748b'>{escape(min_time.isoformat())}</text>")
    parts.append(f"<text x='{(width - margin_right - 190):.2f}' y='{(height - 8):.2f}' font-size='11' fill='#64748b'>{escape(max_time.isoformat())}</text>")
    parts.append("</svg>")
    return "".join(parts)


def _build_equity_svg(*, equity_curve: pd.DataFrame) -> str:
    if equity_curve.empty:
        return "<div class='empty'>No equity curve data available.</div>"
    frame = equity_curve.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "equity"]).sort_values("timestamp").reset_index(drop=True)
    if frame.empty:
        return "<div class='empty'>No equity curve data available.</div>"
    width = 1160.0
    height = 240.0
    margin_left = 62.0
    margin_right = 18.0
    margin_top = 16.0
    margin_bottom = 26.0
    inner_w = width - margin_left - margin_right
    inner_h = height - margin_top - margin_bottom
    y_min = float(frame["equity"].min())
    y_max = float(frame["equity"].max())
    if y_max <= y_min:
        y_max = y_min + 1e-6
    pad = (y_max - y_min) * 0.05
    y_min -= pad
    y_max += pad

    def y_of(value: float) -> float:
        return margin_top + (y_max - value) / (y_max - y_min) * inner_h

    min_time = pd.Timestamp(frame["timestamp"].iloc[0])
    max_time = pd.Timestamp(frame["timestamp"].iloc[-1])
    min_ms = int(min_time.value // 1_000_000)
    max_ms = int(max_time.value // 1_000_000)
    if max_ms <= min_ms:
        max_ms = min_ms + 1

    def x_of(ts: pd.Timestamp) -> float:
        ts_ms = int(pd.Timestamp(ts).value // 1_000_000)
        return margin_left + (ts_ms - min_ms) / (max_ms - min_ms) * inner_w

    points: list[str] = []
    for row in frame.itertuples(index=False):
        x = x_of(pd.Timestamp(row.timestamp))
        y = y_of(float(row.equity))
        points.append(f"{x:.2f},{y:.2f}")
    first_ts = min_time.isoformat()
    last_ts = max_time.isoformat()
    base_view_box = f"0 0 {width:.0f} {height:.0f}"
    return (
        f"<svg id='equitySvg' viewBox='{base_view_box}' data-base-viewbox='{base_view_box}' data-chart-width='{width:.0f}' data-chart-height='{height:.0f}' data-margin-left='{margin_left:.2f}' data-margin-right='{margin_right:.2f}' data-min-ms='{min_ms}' data-max-ms='{max_ms}' xmlns='http://www.w3.org/2000/svg'>"
        f"<line x1='{margin_left:.2f}' y1='{margin_top + inner_h:.2f}' x2='{width - margin_right:.2f}' y2='{margin_top + inner_h:.2f}' stroke='#e2e8f0' stroke-width='1'/>"
        f"<polyline fill='none' stroke='#0f766e' stroke-width='2' points='{' '.join(points)}'/>"
        f"<text x='8' y='{(margin_top + 4):.2f}' font-size='11' fill='#64748b'>{y_max:.4f}</text>"
        f"<text x='8' y='{(margin_top + inner_h + 4):.2f}' font-size='11' fill='#64748b'>{y_min:.4f}</text>"
        f"<text x='{margin_left:.2f}' y='{(height - 7):.2f}' font-size='11' fill='#64748b'>{escape(first_ts)}</text>"
        f"<text x='{(width - margin_right - 190):.2f}' y='{(height - 7):.2f}' font-size='11' fill='#64748b'>{escape(last_ts)}</text>"
        "</svg>"
    )


def _build_trades_table_html(*, trades: pd.DataFrame) -> str:
    if trades.empty:
        return "<div class='empty'>No closed trades.</div>"
    rows: list[str] = []
    frame = trades.copy().reset_index(drop=True)
    for index, row in frame.iterrows():
        trade_id = index + 1
        net_pnl = float(row.get("net_pnl", 0.0))
        pnl_class = "win" if net_pnl >= 0.0 else "loss"
        entry_ts = pd.to_datetime(row.get("entry_time"), utc=True, errors="coerce")
        exit_ts = pd.to_datetime(row.get("exit_time"), utc=True, errors="coerce")
        entry_ms = int(entry_ts.value // 1_000_000) if not pd.isna(entry_ts) else ""
        exit_ms = int(exit_ts.value // 1_000_000) if not pd.isna(exit_ts) else ""
        rows.append(
            f"<tr class='trade-row' data-trade-id='{trade_id}' data-entry-ms='{entry_ms}' data-exit-ms='{exit_ms}'>"
            f"<td>{trade_id}</td>"
            f"<td>{escape(str(row.get('side', '')))}</td>"
            f"<td>{escape(str(row.get('entry_time', '')))}</td>"
            f"<td>{escape(str(row.get('exit_time', '')))}</td>"
            f"<td class='num'>{_format_float(row.get('entry_price', 0.0), digits=6)}</td>"
            f"<td class='num'>{_format_float(row.get('exit_price', 0.0), digits=6)}</td>"
            f"<td class='num'>{_format_float(row.get('quantity', 0.0), digits=6)}</td>"
            f"<td class='num {pnl_class}'>{_format_float(net_pnl, digits=6)}</td>"
            f"<td>{escape(str(row.get('exit_reason', '')))}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<tr>"
        "<th>#</th><th>side</th><th>entry_time</th><th>exit_time</th>"
        "<th class='num'>entry_price</th><th class='num'>exit_price</th><th class='num'>qty</th><th class='num'>net_pnl</th><th>exit_reason</th>"
        "</tr>"
        + "".join(rows)
        + "</table>"
    )


def _build_chunked_ledger_placeholder_html() -> str:
    return (
        "<div class='controls'>"
        "<label for='tradeLedgerPageSize'>Page Size:</label>"
        "<select id='tradeLedgerPageSize'><option value='50'>50</option><option value='100' selected>100</option><option value='200'>200</option><option value='500'>500</option></select>"
        "<button id='tradeLedgerPrev' type='button'>Prev</button>"
        "<button id='tradeLedgerNext' type='button'>Next</button>"
        "<span id='tradeLedgerInfo' class='hint'>Loading ledger...</span>"
        "</div>"
        "<table>"
        "<tr>"
        "<th>#</th><th>side</th><th>entry_time</th><th>exit_time</th>"
        "<th class='num'>entry_price</th><th class='num'>exit_price</th><th class='num'>qty</th><th class='num'>net_pnl</th><th>exit_reason</th>"
        "</tr>"
        "<tbody id='tradeLedgerBody'></tbody>"
        "</table>"
    )


def _build_trade_filter_options(*, trades: pd.DataFrame, max_options: int | None = None) -> str:
    if trades.empty:
        return "<option value='all'>All Trades</option>"
    options = ["<option value='all'>All Trades</option>"]
    start_index = 0
    if max_options is not None and max_options > 0 and len(trades.index) > max_options:
        start_index = len(trades.index) - max_options
    for index in range(start_index, len(trades.index)):
        trade_id = index + 1
        options.append(f"<option value='{trade_id}'>Trade {trade_id}</option>")
    return "".join(options)


def _nearest_bar_index(*, target_ms: int, bars_ms: list[int]) -> int | None:
    if not bars_ms:
        return None
    index = bisect.bisect_left(bars_ms, target_ms)
    if index <= 0:
        return 0
    if index >= len(bars_ms):
        return len(bars_ms) - 1
    left = bars_ms[index - 1]
    right = bars_ms[index]
    if abs(target_ms - left) <= abs(right - target_ms):
        return index - 1
    return index


def _interval_label(interval_ms: int | None) -> str:
    if interval_ms is None or interval_ms <= 0:
        return "unknown"
    mapping = {
        60_000: "1m",
        300_000: "5m",
        900_000: "15m",
        1_800_000: "30m",
        3_600_000: "1h",
        14_400_000: "4h",
        86_400_000: "1d",
    }
    if interval_ms in mapping:
        return mapping[interval_ms]
    if interval_ms % 60_000 == 0:
        return f"{interval_ms // 60_000}m"
    return f"{interval_ms}ms"


def _action_color(action: str) -> str:
    normalized = action.strip().upper()
    if normalized == TradeAction.ENTER_LONG.value:
        return "#16a34a"
    if normalized == TradeAction.ENTER_SHORT.value:
        return "#dc2626"
    if normalized == TradeAction.EXIT.value:
        return "#2563eb"
    if normalized == TradeAction.REVERSE.value:
        return "#7c3aed"
    return "#64748b"


def _format_timestamp(value: Any) -> str:
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return "NA"
    return pd.Timestamp(ts).isoformat()


def _format_float(value: Any, *, digits: int = 6) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "NA"
    if np.isnan(parsed):
        return "NA"
    if np.isposinf(parsed):
        return "inf"
    if np.isneginf(parsed):
        return "-inf"
    return f"{parsed:.{digits}f}"
