"""Builtin BTC intraday action-driven strategy implementations."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from xtrader.strategies.base import (
    ActionStrategyResult,
    BaseActionStrategy,
    DEFAULT_ACTION_OUTPUT_SCHEMA,
    StrategyContext,
    StrategySpec,
    TradeAction,
)


@dataclass(slots=True)
class ThresholdIntradayStrategy(BaseActionStrategy):
    """Single-symbol intraday strategy converting time-series signals to actions."""

    strategy_id: str = "btc_threshold_intraday"
    version: str = "v1"
    input_name: str = "features"
    signal_column: str = "value"

    def spec(self) -> StrategySpec:
        return StrategySpec(
            strategy_id=self.strategy_id,
            version=self.version,
            required_inputs=(self.input_name,),
            output_schema=DEFAULT_ACTION_OUTPUT_SCHEMA,
            params_schema={
                "entry_threshold": {"type": float, "default": 0.5, "min": 0.0, "max": 10_000.0},
                "exit_threshold": {"type": float, "default": 0.1, "min": 0.0, "max": 10_000.0},
                "position_size": {"type": float, "default": 1.0, "min": 0.0, "max": 1_000_000.0},
                "stop_loss": {"type": float, "default": 0.01, "min": 0.0, "max": 1.0},
                "take_profit": {"type": float, "default": 0.02, "min": 0.0, "max": 10.0},
                "time_stop_bars": {"type": int, "default": 24, "min": 1, "max": 100_000},
                "daily_loss_limit": {"type": float, "default": 0.03, "min": 0.0, "max": 10_000.0},
            },
        )

    def generate_actions(self, context: StrategyContext) -> ActionStrategyResult:
        params = self.spec().resolve_params(context.params)
        frame = context.require_input(self.input_name).copy()

        required = {"timestamp", "symbol", self.signal_column}
        if not required.issubset(frame.columns):
            missing = ", ".join(sorted(required.difference(frame.columns)))
            raise ValueError(f"features input missing required columns: {missing}")

        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        frame["signal"] = pd.to_numeric(frame[self.signal_column], errors="coerce")
        if context.universe:
            frame = frame[frame["symbol"].isin(context.universe)]
        frame = frame.dropna(subset=["timestamp", "symbol", "signal"]).sort_values(["timestamp", "symbol"]).reset_index(drop=True)

        entry_threshold = float(params["entry_threshold"])
        exit_threshold = float(params["exit_threshold"])
        position_size = float(params["position_size"])
        if exit_threshold > entry_threshold:
            raise ValueError("exit_threshold must be <= entry_threshold")
        if position_size <= 0.0:
            raise ValueError("position_size must be > 0")

        rows: list[dict[str, object]] = []
        for row in frame.itertuples(index=False):
            signal = float(row.signal)
            action: TradeAction
            reason: str
            if signal >= entry_threshold:
                action = TradeAction.ENTER_LONG
                reason = "signal_enter_long"
            elif signal <= -entry_threshold:
                action = TradeAction.ENTER_SHORT
                reason = "signal_enter_short"
            elif abs(signal) <= exit_threshold:
                action = TradeAction.EXIT
                reason = "signal_exit"
            else:
                action = TradeAction.HOLD
                reason = "signal_hold"
            rows.append(
                {
                    "timestamp": row.timestamp,
                    "symbol": row.symbol,
                    "action": action.value,
                    "size": position_size,
                    "stop_loss": float(params["stop_loss"]),
                    "take_profit": float(params["take_profit"]),
                    "reason": reason,
                }
            )
        output = pd.DataFrame(rows, columns=["timestamp", "symbol", "action", "size", "stop_loss", "take_profit", "reason"])
        result = ActionStrategyResult(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            actions=output,
            diagnostics={
                "input_rows": int(len(frame.index)),
                "output_rows": int(len(output.index)),
                "entry_threshold": entry_threshold,
                "exit_threshold": exit_threshold,
                "signal_column": self.signal_column,
            },
        )
        result.validate_schema(self.spec().output_schema)
        return result


__all__ = [
    "ThresholdIntradayStrategy",
]
