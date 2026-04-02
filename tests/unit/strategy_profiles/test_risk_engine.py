from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from xtrader.strategy_profiles import RiskEngine, StrategyProfilePrecompileEngine


def _payload() -> dict[str, object]:
    return json.loads(
        Path("configs/strategy-profiles/five_min_regime_momentum/v0.3.json").read_text(encoding="utf-8")
    )


def _signal_df() -> pd.DataFrame:
    ts = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=4, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["BTCUSDT"] * 4,
            "action": ["ENTER_LONG", "ENTER_SHORT", "EXIT", "HOLD"],
            "reason_code": ["LONG", "SHORT", "EXIT", "HOLD"],
            "matched_rule_id": ["a", "b", "c", "d"],
            "score_total": [0.8, -0.9, 0.0, 0.1],
            "state": ["TREND_CLEAN", "TREND_CLEAN", "TRANSITION", "TRANSITION"],
        }
    )


def _market_df(close: list[float], *, atr_col: str | None = None, atr_values: list[float] | None = None) -> pd.DataFrame:
    ts = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=len(close), freq="5min", tz="UTC")
    payload: dict[str, object] = {
        "timestamp": ts,
        "symbol": ["BTCUSDT"] * len(close),
        "close": close,
    }
    if atr_col is not None and atr_values is not None:
        payload[atr_col] = atr_values
    return pd.DataFrame(payload)


def test_risk_engine_fixed_pct_positive() -> None:
    payload = _payload()
    precompile = StrategyProfilePrecompileEngine().compile(payload)
    assert precompile.status == "SUCCESS"

    signal = _signal_df()
    market = _market_df([100.0, 100.0, 101.0, 99.0])
    out = RiskEngine().run(
        resolved_profile=precompile.resolved_profile,
        signal_df=signal,
        market_df=market,
        account_context={"equity": 10_000.0},
    ).frame

    # fixed_fraction: size = equity * fraction / close = 10000 * 0.02 / 100 = 2
    assert out.loc[0, "size"] == pytest.approx(2.0)
    assert out.loc[1, "size"] == pytest.approx(2.0)
    assert out.loc[2, "size"] == pytest.approx(0.0)
    assert out.loc[3, "size"] == pytest.approx(0.0)

    # fixed_pct stop/take
    assert out.loc[0, "stop_loss"] == pytest.approx(99.2)
    assert out.loc[0, "take_profit"] == pytest.approx(101.6)
    assert out.loc[1, "stop_loss"] == pytest.approx(100.8)
    assert out.loc[1, "take_profit"] == pytest.approx(98.4)
    assert pd.isna(out.loc[2, "stop_loss"])
    assert pd.isna(out.loc[3, "take_profit"])
    assert set(out.columns).issuperset({"timestamp", "symbol", "action", "size", "stop_loss", "take_profit", "reason"})


def test_risk_engine_atr_rr_positive() -> None:
    payload = _payload()
    precompile = StrategyProfilePrecompileEngine().compile(payload)
    assert precompile.status == "SUCCESS"
    profile = copy.deepcopy(precompile.resolved_profile)
    profile["risk_spec"]["stop_model"] = {"mode": "atr_multiple", "params": {"multiple": 2.0}}
    profile["risk_spec"]["take_profit_model"] = {"mode": "rr_multiple", "params": {"multiple": 1.5}}

    signal = _signal_df()
    market = _market_df([100.0, 100.0, 101.0, 99.0], atr_col="f:5m:atr_14:value", atr_values=[5.0, 5.0, 5.0, 5.0])
    out = RiskEngine().run(
        resolved_profile=profile,
        signal_df=signal,
        market_df=market,
        account_context={"equity": 10_000.0},
    ).frame
    # LONG: stop=100-2*5=90, tp=100+1.5*(100-90)=115
    assert out.loc[0, "stop_loss"] == pytest.approx(90.0)
    assert out.loc[0, "take_profit"] == pytest.approx(115.0)
    # SHORT: stop=100+2*5=110, tp=100-1.5*(110-100)=85
    assert out.loc[1, "stop_loss"] == pytest.approx(110.0)
    assert out.loc[1, "take_profit"] == pytest.approx(85.0)


def test_risk_engine_action_size_contract_positive() -> None:
    payload = _payload()
    precompile = StrategyProfilePrecompileEngine().compile(payload)
    assert precompile.status == "SUCCESS"
    out = RiskEngine().run(
        resolved_profile=precompile.resolved_profile,
        signal_df=_signal_df(),
        market_df=_market_df([100.0, 100.0, 101.0, 99.0]),
        account_context={"equity": 10_000.0},
    ).frame
    assert float(out.loc[0, "size"]) > 0.0
    assert float(out.loc[1, "size"]) > 0.0
    assert out.loc[2, "size"] == pytest.approx(0.0)
    assert out.loc[3, "size"] == pytest.approx(0.0)


def test_risk_engine_portfolio_guards_positive() -> None:
    payload = _payload()
    precompile = StrategyProfilePrecompileEngine().compile(payload)
    assert precompile.status == "SUCCESS"

    signal = _signal_df().iloc[[0]].reset_index(drop=True)  # ENTER_LONG
    market = _market_df([100.0])

    out_guard_pos = RiskEngine().run(
        resolved_profile=precompile.resolved_profile,
        signal_df=signal,
        market_df=market,
        account_context={"equity": 10_000.0, "open_positions": 1},
    ).frame
    assert out_guard_pos.loc[0, "action"] == "HOLD"
    assert out_guard_pos.loc[0, "reason_code"] == "GUARD_MAX_CONCURRENT_POSITIONS"

    out_guard_loss = RiskEngine().run(
        resolved_profile=precompile.resolved_profile,
        signal_df=signal,
        market_df=market,
        account_context={"equity": 10_000.0, "open_positions": 0, "daily_pnl_pct": -0.05},
    ).frame
    assert out_guard_loss.loc[0, "action"] == "HOLD"
    assert out_guard_loss.loc[0, "reason_code"] == "GUARD_DAILY_LOSS_LIMIT"


def test_risk_engine_missing_close_negative() -> None:
    payload = _payload()
    precompile = StrategyProfilePrecompileEngine().compile(payload)
    assert precompile.status == "SUCCESS"

    signal = _signal_df()
    market = _market_df([100.0, 100.0, 101.0, 99.0]).drop(columns=["close"])
    with pytest.raises(ValueError, match=r"XTRSP006::MISSING_MARKET_COLUMN::"):
        RiskEngine().run(
            resolved_profile=precompile.resolved_profile,
            signal_df=signal,
            market_df=market,
            account_context={"equity": 10_000.0},
        )


def test_risk_engine_missing_atr_negative() -> None:
    payload = _payload()
    precompile = StrategyProfilePrecompileEngine().compile(payload)
    assert precompile.status == "SUCCESS"
    profile = copy.deepcopy(precompile.resolved_profile)
    profile["risk_spec"]["stop_model"] = {"mode": "atr_multiple", "params": {"multiple": 2.0}}
    profile["risk_spec"]["take_profit_model"] = {"mode": "rr_multiple", "params": {"multiple": 1.5}}

    signal = _signal_df()
    market = _market_df([100.0, 100.0, 101.0, 99.0])  # no atr column
    with pytest.raises(ValueError, match=r"XTRSP006::MISSING_ATR_COLUMN::"):
        RiskEngine().run(
            resolved_profile=profile,
            signal_df=signal,
            market_df=market,
            account_context={"equity": 10_000.0},
        )
