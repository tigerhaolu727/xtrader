"""Risk engine runtime for strategy profile v0.3."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

_REQUIRED_SIGNAL_COLUMNS: tuple[str, ...] = ("timestamp", "symbol", "action", "reason_code")
_REQUIRED_MARKET_COLUMNS: tuple[str, ...] = ("timestamp", "symbol", "close")
_ATR_FEATURE_REF_PATTERN = re.compile(r"^f:[^:]+:(atr_[^:]*):value$")
_ACTION_ENTER_LONG = "ENTER_LONG"
_ACTION_ENTER_SHORT = "ENTER_SHORT"
_ACTION_HOLD = "HOLD"
_VALID_ACTIONS = {"ENTER_LONG", "ENTER_SHORT", "EXIT", "HOLD", "REVERSE"}


def _xtr_sp006_error(code: str, detail: str) -> ValueError:
    return ValueError(f"XTRSP006::{code}::{detail}")


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _is_enter_action(action: str) -> bool:
    return action in (_ACTION_ENTER_LONG, _ACTION_ENTER_SHORT)


def _is_long(action: str) -> bool:
    return action == _ACTION_ENTER_LONG


@dataclass(frozen=True, slots=True)
class RiskEngineResult:
    frame: pd.DataFrame


class RiskEngine:
    """Apply RiskSpec to signal actions and emit action-risk payload."""

    def run(
        self,
        *,
        resolved_profile: dict[str, Any],
        signal_df: pd.DataFrame,
        market_df: pd.DataFrame,
        account_context: dict[str, Any] | None = None,
    ) -> RiskEngineResult:
        signal_missing = [column for column in _REQUIRED_SIGNAL_COLUMNS if column not in signal_df.columns]
        if signal_missing:
            raise _xtr_sp006_error("MISSING_SIGNAL_COLUMN", ",".join(signal_missing))
        market_missing = [column for column in _REQUIRED_MARKET_COLUMNS if column not in market_df.columns]
        if market_missing:
            raise _xtr_sp006_error("MISSING_MARKET_COLUMN", ",".join(market_missing))

        risk_spec = dict(resolved_profile["risk_spec"])
        size_model = dict(risk_spec["size_model"])
        stop_model = dict(risk_spec["stop_model"])
        take_profit_model = dict(risk_spec["take_profit_model"])
        time_stop = dict(risk_spec["time_stop"])
        guards = dict(risk_spec["portfolio_guards"])
        rounding = dict(risk_spec.get("rounding_policy") or {})

        if str(size_model["mode"]) != "fixed_fraction":
            raise _xtr_sp006_error("SIZE_MODE_UNSUPPORTED", str(size_model["mode"]))
        stop_mode = str(stop_model["mode"])
        if stop_mode not in {"fixed_pct", "atr_multiple"}:
            raise _xtr_sp006_error("STOP_MODE_UNSUPPORTED", stop_mode)
        tp_mode = str(take_profit_model["mode"])
        if tp_mode not in {"fixed_pct", "rr_multiple"}:
            raise _xtr_sp006_error("TAKE_PROFIT_MODE_UNSUPPORTED", tp_mode)

        signal = signal_df.copy(deep=True).reset_index(drop=True)
        market = market_df.copy(deep=True).reset_index(drop=True)
        merged = self._join_market(signal=signal, market=market, require_atr=(stop_mode == "atr_multiple"))

        account = dict(account_context or {})
        equity = float(account.get("equity", 1.0))
        daily_pnl_pct = account.get("daily_pnl_pct")
        open_positions = int(account.get("open_positions", 0))
        max_positions = int(guards["max_concurrent_positions"])
        daily_loss_limit = float(guards["daily_loss_limit"])
        size_fraction = float(size_model["params"]["fraction"])
        price_dp = int(rounding.get("price_dp", 8))
        size_dp = int(rounding.get("size_dp", 8))
        time_stop_bars = int(time_stop["bars"])

        rows: list[dict[str, Any]] = []
        for row in merged.itertuples(index=False):
            action = str(row.action)
            reason_code = str(row.reason_code)
            if action not in _VALID_ACTIONS:
                raise _xtr_sp006_error("INVALID_ACTION", action)

            guarded_action, guarded_reason = self._apply_guards(
                action=action,
                daily_pnl_pct=daily_pnl_pct,
                daily_loss_limit=daily_loss_limit,
                open_positions=open_positions,
                max_positions=max_positions,
            )
            if guarded_reason is not None:
                reason_code = guarded_reason
                action = guarded_action

            close = _to_float(row.close)
            if _is_enter_action(action):
                if pd.isna(close) or close <= 0.0:
                    raise _xtr_sp006_error("INVALID_CLOSE", str(close))
                size = (equity * size_fraction) / close
                stop_loss = self._compute_stop(
                    action=action,
                    close=close,
                    atr_value=_to_float(getattr(row, "atr_runtime_value", float("nan"))),
                    stop_mode=stop_mode,
                    stop_params=dict(stop_model["params"]),
                )
                take_profit = self._compute_take_profit(
                    action=action,
                    close=close,
                    stop_loss=stop_loss,
                    take_profit_mode=tp_mode,
                    take_profit_params=dict(take_profit_model["params"]),
                )
            else:
                size = 0.0
                stop_loss = float("nan")
                take_profit = float("nan")

            rows.append(
                {
                    "timestamp": row.timestamp,
                    "symbol": row.symbol,
                    "action": action,
                    "size": round(float(size), size_dp),
                    "stop_loss": round(float(stop_loss), price_dp) if pd.notna(stop_loss) else float("nan"),
                    "take_profit": round(float(take_profit), price_dp) if pd.notna(take_profit) else float("nan"),
                    "reason": reason_code,
                    "reason_code": reason_code,
                    "time_stop_bars": time_stop_bars if _is_enter_action(action) else 0,
                    "matched_rule_id": getattr(row, "matched_rule_id", None),
                    "score_total": getattr(row, "score_total", float("nan")),
                    "state": getattr(row, "state", None),
                }
            )
        output = pd.DataFrame(rows)
        return RiskEngineResult(frame=output)

    def _join_market(self, *, signal: pd.DataFrame, market: pd.DataFrame, require_atr: bool) -> pd.DataFrame:
        view_columns = ["timestamp", "symbol", "close"]
        atr_column = self._resolve_atr_column(market) if require_atr else None
        if atr_column is not None:
            view_columns.append(atr_column)

        market_view = market[view_columns].copy(deep=True)
        if market_view[["timestamp", "symbol"]].duplicated().any():
            raise _xtr_sp006_error("MARKET_DUPLICATE_KEY", "timestamp,symbol")
        if atr_column is not None:
            market_view = market_view.rename(columns={atr_column: "atr_runtime_value"})

        merged = signal.merge(market_view, on=["timestamp", "symbol"], how="left", validate="many_to_one")
        if merged["close"].isna().any():
            raise _xtr_sp006_error("MISSING_MARKET_ROW", "close")
        return merged

    def _resolve_atr_column(self, market: pd.DataFrame) -> str:
        if "atr_value" in market.columns:
            return "atr_value"
        candidates: list[str] = []
        for column in market.columns:
            match = _ATR_FEATURE_REF_PATTERN.match(str(column))
            if not match:
                continue
            instance_id = str(match.group(1))
            if instance_id.startswith("atr_pct_rank"):
                continue
            candidates.append(str(column))
        if not candidates:
            raise _xtr_sp006_error("MISSING_ATR_COLUMN", "atr_value|f:*:atr_*:value")
        if len(candidates) > 1:
            raise _xtr_sp006_error("AMBIGUOUS_ATR_COLUMN", ",".join(sorted(candidates)))
        return candidates[0]

    def _apply_guards(
        self,
        *,
        action: str,
        daily_pnl_pct: Any,
        daily_loss_limit: float,
        open_positions: int,
        max_positions: int,
    ) -> tuple[str, str | None]:
        if _is_enter_action(action) and daily_pnl_pct is not None:
            pnl = _to_float(daily_pnl_pct)
            if pd.notna(pnl) and pnl <= -daily_loss_limit:
                return _ACTION_HOLD, "GUARD_DAILY_LOSS_LIMIT"
        if _is_enter_action(action) and open_positions >= max_positions:
            return _ACTION_HOLD, "GUARD_MAX_CONCURRENT_POSITIONS"
        return action, None

    def _compute_stop(
        self,
        *,
        action: str,
        close: float,
        atr_value: float,
        stop_mode: str,
        stop_params: dict[str, Any],
    ) -> float:
        if stop_mode == "fixed_pct":
            pct = float(stop_params["pct"])
            if _is_long(action):
                return close * (1.0 - pct)
            return close * (1.0 + pct)

        if stop_mode == "atr_multiple":
            if pd.isna(atr_value) or atr_value <= 0.0:
                raise _xtr_sp006_error("INVALID_ATR_VALUE", str(atr_value))
            multiple = float(stop_params["multiple"])
            if _is_long(action):
                return close - (atr_value * multiple)
            return close + (atr_value * multiple)

        raise _xtr_sp006_error("STOP_MODE_UNSUPPORTED", stop_mode)

    def _compute_take_profit(
        self,
        *,
        action: str,
        close: float,
        stop_loss: float,
        take_profit_mode: str,
        take_profit_params: dict[str, Any],
    ) -> float:
        if take_profit_mode == "fixed_pct":
            pct = float(take_profit_params["pct"])
            if _is_long(action):
                return close * (1.0 + pct)
            return close * (1.0 - pct)

        if take_profit_mode == "rr_multiple":
            multiple = float(take_profit_params["multiple"])
            if _is_long(action):
                risk = close - stop_loss
                return close + (risk * multiple)
            risk = stop_loss - close
            return close - (risk * multiple)

        raise _xtr_sp006_error("TAKE_PROFIT_MODE_UNSUPPORTED", take_profit_mode)


__all__ = ["RiskEngine", "RiskEngineResult"]
