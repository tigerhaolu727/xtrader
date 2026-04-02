from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import xtrader.backtests.event_driven as event_driven_module
from xtrader.backtests import (
    EventDrivenBacktestConfig,
    build_strategy_report_root,
    run_event_driven_backtest,
    write_event_driven_outputs,
    write_strategy_event_driven_outputs,
)
from xtrader.strategies import ProfileActionStrategy, StrategyContext, TradeAction


def _build_price_frame() -> pd.DataFrame:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    closes = [100.0, 101.0, 102.0, 101.5, 101.0]
    for idx, close in enumerate(closes):
        rows.append(
            {
                "timestamp": start + timedelta(minutes=5 * idx),
                "symbol": "BTCUSDT",
                "close": close,
                "funding_rate": 0.0,
            }
        )
    return pd.DataFrame(rows)


def _build_profile_5m_frame(rows: int = 420) -> pd.DataFrame:
    ts = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=rows, freq="5min", tz="UTC")
    close = pd.Series([100.0 + (idx * 0.18) + ((idx % 7) - 3) * 0.09 for idx in range(rows)], dtype="float64")
    frame = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["BTCUSDT"] * rows,
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.3,
            "close": close,
            "volume": [1000.0 + ((idx * 11) % 160) for idx in range(rows)],
        }
    )
    frame["funding_rate"] = 0.0
    return frame


def test_prepare_dashboard_prices_synthesizes_visual_ohlc_for_degenerate_doji_stream() -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * idx) for idx in range(4)],
            "symbol": ["BTCUSDT"] * 4,
            "open": [100.0, 101.0, 103.0, 102.0],
            "high": [102.0, 104.0, 104.0, 103.0],
            "low": [99.0, 100.0, 101.0, 100.0],
            "close": [100.0, 101.0, 103.0, 102.0],
        }
    )
    out = event_driven_module._prepare_dashboard_prices(price_frame=frame, symbol="BTCUSDT")
    assert len(out.index) == 4
    assert float(out.iloc[0]["open"]) == pytest.approx(float(out.iloc[0]["close"]))
    assert float(out.iloc[1]["open"]) == pytest.approx(float(out.iloc[0]["close"]))
    assert float(out.iloc[2]["open"]) == pytest.approx(float(out.iloc[1]["close"]))
    assert not bool((out["open"] - out["close"]).abs().le(1e-12).all())


def test_event_driven_backtest_generates_trade_ledger() -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    actions = pd.DataFrame(
        {
            "timestamp": [start, start + timedelta(minutes=5)],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value, TradeAction.EXIT.value],
            "size": [1.0, 1.0],
            "stop_loss": [None, None],
            "take_profit": [None, None],
            "reason": ["signal_entry", "signal_exit"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=_build_price_frame(),
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            initial_equity=1000.0,
            default_stop_loss=None,
            default_take_profit=None,
        ),
    )
    assert result.summary.trade_count == 1
    assert not result.trades.empty
    trade = result.trades.iloc[0]
    assert trade["symbol"] == "BTCUSDT"
    assert trade["exit_reason"] == "signal_exit"
    assert float(trade["net_pnl"]) == pytest.approx(1.0)
    assert result.summary.net_return > 0.0
    assert int(result.summary.skipped_signal_count) == 0


def test_event_driven_backtest_marks_tail_signal_as_skipped_no_next_bar() -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    prices = _build_price_frame().iloc[:2].reset_index(drop=True)
    actions = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5)],
            "symbol": ["BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value],
            "size": [1.0],
            "stop_loss": [0.01],
            "take_profit": [0.03],
            "reason": ["signal_entry"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=prices,
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            initial_equity=1000.0,
        ),
    )
    assert int(result.summary.skipped_signal_count) == 1
    assert int(result.diagnostics["skipped_signals"]) == 1
    assert result.summary.trade_count == 0
    assert len(result.action_input_snapshot.index) == 1
    row = result.action_input_snapshot.iloc[0]
    assert row["status"] == "SKIPPED"
    assert row["skip_reason"] == "NO_NEXT_BAR"


def test_event_driven_backtest_marks_executable_signals_as_filled() -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    actions = pd.DataFrame(
        {
            "timestamp": [start, start + timedelta(minutes=5)],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value, TradeAction.EXIT.value],
            "size": [1.0, 1.0],
            "stop_loss": [None, None],
            "take_profit": [None, None],
            "reason": ["signal_entry", "signal_exit"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=_build_price_frame(),
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            initial_equity=1000.0,
            default_stop_loss=None,
            default_take_profit=None,
        ),
    )
    assert set(result.action_input_snapshot["status"].tolist()) == {"FILLED"}
    assert int(result.summary.skipped_signal_count) == 0
    assert int(result.diagnostics["skipped_signals"]) == 0


def test_event_driven_backtest_forces_stop_loss_exit() -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    prices = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * idx) for idx in range(5)],
            "symbol": ["BTCUSDT"] * 5,
            "close": [100.0, 100.0, 98.0, 97.5, 97.0],
            "funding_rate": [0.0] * 5,
        }
    )
    actions = pd.DataFrame(
        {
            "timestamp": [start],
            "symbol": ["BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value],
            "size": [1.0],
            "stop_loss": [0.01],
            "take_profit": [0.03],
            "reason": ["signal_entry"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=prices,
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            initial_equity=1000.0,
        ),
    )
    assert result.summary.trade_count == 1
    assert result.trades.iloc[0]["exit_reason"] == "stop_loss"
    assert result.diagnostics["forced_risk_exits"] >= 1


def test_event_driven_backtest_does_not_trigger_stop_loss_on_entry_bar() -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    prices = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * idx) for idx in range(5)],
            "symbol": ["BTCUSDT"] * 5,
            "open": [100.0, 100.0, 95.0, 94.0, 93.0],
            "high": [101.0, 101.0, 96.0, 95.0, 94.0],
            "low": [99.0, 90.0, 94.0, 93.0, 92.0],
            "close": [100.0, 90.0, 94.0, 93.0, 92.0],
            "funding_rate": [0.0] * 5,
        }
    )
    actions = pd.DataFrame(
        {
            "timestamp": [start],
            "symbol": ["BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value],
            "size": [1.0],
            "stop_loss": [0.01],
            "take_profit": [None],
            "reason": ["signal_entry"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=prices,
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            initial_equity=1000.0,
            default_take_profit=None,
        ),
    )
    assert result.summary.trade_count == 1
    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "stop_loss"
    assert pd.Timestamp(trade["exit_time"]) > pd.Timestamp(trade["entry_time"])


def test_event_driven_backtest_trade_ledger_reconciles_costs() -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    prices = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * idx) for idx in range(6)],
            "symbol": ["BTCUSDT"] * 6,
            "close": [100.0, 100.5, 101.0, 101.2, 101.4, 101.6],
            "funding_rate": [0.0, 0.0, 0.0001, 0.0001, 0.0, 0.0],
        }
    )
    actions = pd.DataFrame(
        {
            "timestamp": [start, start + timedelta(minutes=20)],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value, TradeAction.EXIT.value],
            "size": [1.5, 1.5],
            "stop_loss": [0.01, 0.01],
            "take_profit": [0.03, 0.03],
            "reason": ["signal_entry", "signal_exit"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=prices,
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=6.0,
            slippage_bps=5.0,
            initial_equity=1000.0,
        ),
    )
    assert result.summary.trade_count == 1
    trade = result.trades.iloc[0]
    reconciled = (
        float(trade["gross_pnl"])
        - float(trade["fee_cost"])
        - float(trade["slippage_cost"])
        - float(trade["funding_cost"])
    )
    assert float(trade["net_pnl"]) == pytest.approx(reconciled, abs=1e-10)


def test_event_driven_backtest_executes_signal_orders_at_next_bar_open() -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    prices = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=5 * idx) for idx in range(5)],
            "symbol": ["BTCUSDT"] * 5,
            "open": [100.0, 110.0, 120.0, 130.0, 140.0],
            "high": [101.0, 111.0, 121.0, 131.0, 141.0],
            "low": [99.0, 109.0, 119.0, 129.0, 139.0],
            "close": [100.5, 110.5, 120.5, 130.5, 140.5],
            "funding_rate": [0.0] * 5,
        }
    )
    actions = pd.DataFrame(
        {
            "timestamp": [start, start + timedelta(minutes=5)],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value, TradeAction.EXIT.value],
            "size": [1.0, 1.0],
            "stop_loss": [None, None],
            "take_profit": [None, None],
            "reason": ["signal_entry", "signal_exit"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=prices,
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=0.0,
            slippage_bps=0.0,
            initial_equity=1000.0,
            default_stop_loss=None,
            default_take_profit=None,
        ),
    )
    assert result.summary.trade_count == 1
    trade = result.trades.iloc[0]
    assert float(trade["entry_price"]) == pytest.approx(110.0)
    assert float(trade["exit_price"]) == pytest.approx(120.0)


def test_event_driven_report_smoke_writes_artifacts(tmp_path) -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    actions = pd.DataFrame(
        {
            "timestamp": [start, start + timedelta(minutes=5)],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value, TradeAction.EXIT.value],
            "size": [1.0, 1.0],
            "stop_loss": [0.01, 0.01],
            "take_profit": [0.03, 0.03],
            "reason": ["signal_entry", "signal_exit"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=_build_price_frame(),
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=6.0,
            slippage_bps=3.0,
            initial_equity=1000.0,
        ),
    )
    report_root = tmp_path / "reports" / "event_driven_smoke"
    outputs = write_event_driven_outputs(
        report_root=report_root,
        config=EventDrivenBacktestConfig(symbol="BTCUSDT"),
        result=result,
        price_frame=_build_price_frame(),
        actions=actions,
        signal_interval_ms=60_000,
        resampled_price_frames={
            "15m": _build_price_frame().iloc[::3].reset_index(drop=True),
            "1h": _build_price_frame().iloc[::6].reset_index(drop=True),
        },
    )
    run_manifest_path = report_root / "run_manifest.json"
    summary_path = report_root / "summary.json"
    diagnostics_path = report_root / "diagnostics.json"
    trades_parquet_path = report_root / "ledgers" / "trades.parquet"
    equity_parquet_path = report_root / "curves" / "equity_curve.parquet"
    signal_execution_path = report_root / "timelines" / "signal_execution.parquet"
    decision_trace_path = report_root / "timelines" / "decision_trace.parquet"
    snapshot_root = report_root / "snapshots"
    price_snapshot_path = snapshot_root / "base" / "price_5m.parquet"
    action_snapshot_path = snapshot_root / "action_input.parquet"
    snapshot_manifest_path = snapshot_root / "snapshot_manifest.json"
    resampled_manifest_path = snapshot_root / "resampled" / "resampled_manifest.json"
    resampled_15m_path = snapshot_root / "resampled" / "price_15m.parquet"
    resampled_1h_path = snapshot_root / "resampled" / "price_1h.parquet"
    assert summary_path.exists()
    assert diagnostics_path.exists()
    assert run_manifest_path.exists()
    assert trades_parquet_path.exists()
    assert equity_parquet_path.exists()
    assert signal_execution_path.exists()
    assert decision_trace_path.exists()
    assert price_snapshot_path.exists()
    assert action_snapshot_path.exists()
    assert snapshot_manifest_path.exists()
    assert resampled_manifest_path.exists()
    assert resampled_15m_path.exists()
    assert resampled_1h_path.exists()
    assert not (report_root / "trades.csv").exists()
    assert not (report_root / "equity_curve.csv").exists()
    assert not (report_root / "timelines" / "signal_execution.csv").exists()
    assert not (snapshot_root / "base" / "price_5m.csv").exists()
    assert not (snapshot_root / "action_input.csv").exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    for key in ("profit_factor", "expectancy", "win_rate", "max_drawdown", "net_return"):
        assert key in payload
    assert "skipped_signal_count" in payload
    diagnostics_payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert "diagnostics" in diagnostics_payload
    assert outputs["summary_path"].endswith("summary.json")
    assert outputs["run_manifest_path"].endswith("run_manifest.json")
    assert outputs["diagnostics_path"].endswith("diagnostics.json")
    assert outputs["signal_execution_path"].endswith("timelines/signal_execution.parquet")
    assert outputs["decision_trace_path"].endswith("timelines/decision_trace.parquet")
    assert outputs["price_snapshot_path"].endswith("snapshots/base/price_5m.parquet")
    assert outputs["action_snapshot_path"].endswith("snapshots/action_input.parquet")
    assert outputs["snapshot_manifest_path"].endswith("snapshots/snapshot_manifest.json")
    assert outputs["resampled_manifest_path"].endswith("snapshots/resampled/resampled_manifest.json")
    assert "resampled_15m_path" in outputs
    assert "resampled_1h_path" in outputs
    manifest_payload = json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
    assert manifest_payload["version"] == "v1"
    assert manifest_payload["base_timeframe"] == "5m"
    files_payload = manifest_payload["files"]
    assert files_payload["price_input"]["rows"] == int(len(result.price_input_snapshot.index))
    assert files_payload["action_input"]["rows"] == int(len(result.action_input_snapshot.index))
    price_digest = hashlib.sha256(price_snapshot_path.read_bytes()).hexdigest()
    action_digest = hashlib.sha256(action_snapshot_path.read_bytes()).hexdigest()
    assert files_payload["price_input"]["sha256"] == price_digest
    assert files_payload["action_input"]["sha256"] == action_digest
    run_manifest_payload = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    assert run_manifest_payload["schema_version"] == "bt_run_v1"
    assert run_manifest_payload["base_timeframe"] == "5m"
    assert "artifacts" in run_manifest_payload
    assert len(run_manifest_payload["artifacts"]) >= 8
    artifact_paths = [str(item.get("path", "")) for item in run_manifest_payload["artifacts"]]
    assert f"ledgers/{event_driven_module._TRADES_PARQUET_FILENAME}" in artifact_paths
    assert f"curves/{event_driven_module._EQUITY_PARQUET_FILENAME}" in artifact_paths
    assert f"timelines/{event_driven_module._SIGNAL_EXECUTION_FILENAME}" in artifact_paths
    assert f"timelines/{event_driven_module._DECISION_TRACE_FILENAME}" in artifact_paths
    assert all(not path.endswith(".csv") for path in artifact_paths if path)
    prices_chunk_manifest = json.loads(Path(outputs["price_chunks_manifest_path"]).read_text(encoding="utf-8"))
    if prices_chunk_manifest["chunks"]:
        assert prices_chunk_manifest["chunks"][0]["file"].endswith(".parquet")
    decision_chunk_manifest = json.loads(Path(outputs["decision_trace_chunks_manifest_path"]).read_text(encoding="utf-8"))
    assert decision_chunk_manifest["dataset"] == "decision_trace"
    resampled_manifest_payload = json.loads(resampled_manifest_path.read_text(encoding="utf-8"))
    frames = resampled_manifest_payload["frames"]
    assert len(frames) == 2
    assert {item["timeframe"] for item in frames} == {"15m", "1h"}


def test_event_driven_backtest_reproducible_for_same_inputs() -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    actions = pd.DataFrame(
        {
            "timestamp": [start, start + timedelta(minutes=5)],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value, TradeAction.EXIT.value],
            "size": [1.0, 1.0],
            "stop_loss": [0.01, 0.01],
            "take_profit": [0.03, 0.03],
            "reason": ["signal_entry", "signal_exit"],
        }
    )
    prices = _build_price_frame()
    config = EventDrivenBacktestConfig(
        symbol="BTCUSDT",
        interval_ms=300_000,
        execution_lag_bars=1,
        taker_fee_bps=6.0,
        slippage_bps=3.0,
        initial_equity=1000.0,
    )
    result_a = run_event_driven_backtest(actions=actions, price_frame=prices, config=config)
    result_b = run_event_driven_backtest(actions=actions, price_frame=prices, config=config)
    assert result_a.summary == result_b.summary
    assert result_a.diagnostics == result_b.diagnostics
    assert_frame_equal(result_a.trades.reset_index(drop=True), result_b.trades.reset_index(drop=True), check_dtype=False)
    assert_frame_equal(
        result_a.equity_curve.reset_index(drop=True),
        result_b.equity_curve.reset_index(drop=True),
        check_dtype=False,
    )
    assert_frame_equal(
        result_a.price_input_snapshot.reset_index(drop=True),
        result_b.price_input_snapshot.reset_index(drop=True),
        check_dtype=False,
    )
    assert_frame_equal(
        result_a.action_input_snapshot.reset_index(drop=True),
        result_b.action_input_snapshot.reset_index(drop=True),
        check_dtype=False,
    )


def test_event_driven_report_chunked_ledger_outputs_manifest(tmp_path, monkeypatch) -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    actions = pd.DataFrame(
        {
            "timestamp": [start, start + timedelta(minutes=5)],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value, TradeAction.EXIT.value],
            "size": [1.0, 1.0],
            "stop_loss": [0.01, 0.01],
            "take_profit": [0.03, 0.03],
            "reason": ["signal_entry", "signal_exit"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=_build_price_frame(),
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=6.0,
            slippage_bps=3.0,
            initial_equity=1000.0,
        ),
    )
    monkeypatch.setattr(event_driven_module, "_LEDGER_CHUNK_THRESHOLD", 0)
    report_root = tmp_path / "reports" / "event_driven_chunked"
    outputs = write_event_driven_outputs(
        report_root=report_root,
        config=EventDrivenBacktestConfig(symbol="BTCUSDT"),
        result=result,
        price_frame=_build_price_frame(),
        actions=actions,
        signal_interval_ms=60_000,
    )
    assert "ledger_manifest_path" in outputs
    manifest_path = Path(outputs["ledger_manifest_path"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["total_trades"] == int(result.summary.trade_count)
    assert "chunks" in manifest
    assert len(manifest["chunks"]) >= 1
    first_chunk = report_root / manifest["chunks"][0]["file"]
    assert first_chunk.exists()
    run_manifest = json.loads((report_root / "run_manifest.json").read_text(encoding="utf-8"))
    artifact_paths = {str(item.get("path", "")) for item in run_manifest.get("artifacts", [])}
    assert "trade_ledger_manifest.json" in artifact_paths


def test_event_driven_outputs_do_not_generate_hub_or_html_reports(tmp_path) -> None:
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    actions = pd.DataFrame(
        {
            "timestamp": [start, start + timedelta(minutes=5)],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value, TradeAction.EXIT.value],
            "size": [1.0, 1.0],
            "stop_loss": [0.01, 0.01],
            "take_profit": [0.03, 0.03],
            "reason": ["signal_entry", "signal_exit"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=_build_price_frame(),
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=6.0,
            slippage_bps=3.0,
            initial_equity=1000.0,
        ),
    )
    root_a = tmp_path / "reports" / "profile_action" / "20260320T000000Z_case_a"
    root_b = tmp_path / "reports" / "profile_action" / "20260320T000100Z_case_b"
    write_event_driven_outputs(
        report_root=root_a,
        config=EventDrivenBacktestConfig(symbol="BTCUSDT"),
        result=result,
        price_frame=_build_price_frame(),
        actions=actions,
        signal_interval_ms=60_000,
    )
    write_event_driven_outputs(
        report_root=root_b,
        config=EventDrivenBacktestConfig(symbol="BTCUSDT"),
        result=result,
        price_frame=_build_price_frame(),
        actions=actions,
        signal_interval_ms=60_000,
    )
    for root in (root_a, root_b):
        assert (root / "run_manifest.json").exists()
        assert not (root / "event_driven_report.html").exists()
        assert not (root / "event_driven_report.md").exists()
    assert not (root_a.parent / "report_hub.html").exists()
    assert not (root_a.parent / "report_hub_index.json").exists()


def test_event_driven_outputs_write_diagnostics_and_timeline(tmp_path) -> None:
    collection_root = tmp_path / "reports" / "profile_action"
    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    actions = pd.DataFrame(
        {
            "timestamp": [start, start + timedelta(minutes=5)],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value, TradeAction.EXIT.value],
            "size": [1.0, 1.0],
            "stop_loss": [0.01, 0.01],
            "take_profit": [0.03, 0.03],
            "reason": ["signal_entry", "signal_exit"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=_build_price_frame(),
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=6.0,
            slippage_bps=3.0,
            initial_equity=1000.0,
        ),
    )
    new_root = collection_root / "20260320T000500Z_new_case"
    outputs = write_event_driven_outputs(
        report_root=new_root,
        config=EventDrivenBacktestConfig(symbol="BTCUSDT"),
        result=result,
        price_frame=_build_price_frame(),
        actions=actions,
        signal_interval_ms=60_000,
    )
    diagnostics_payload = json.loads((new_root / "diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics_payload["diagnostics"]["scheduled_actions"] >= 1
    assert diagnostics_payload["diagnostics"]["skipped_signals"] >= 0
    timeline = pd.read_parquet(new_root / "timelines" / "signal_execution.parquet")
    assert "lag_ms" in timeline.columns
    assert "status" in timeline.columns
    assert "skip_reason" in timeline.columns
    assert int(len(timeline.index)) >= 1
    assert outputs["signal_execution_path"].endswith("timelines/signal_execution.parquet")


def test_strategy_scoped_report_root_and_outputs(tmp_path) -> None:
    root = build_strategy_report_root(
        strategy_name="Profile Action",
        report_base=tmp_path / "reports" / "backtests" / "strategy",
        run_id="20260320T000500Z_profile_action",
    )
    assert root == (
        tmp_path
        / "reports"
        / "backtests"
        / "strategy"
        / "profile_action"
        / "20260320T000500Z_profile_action"
    )

    start = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    actions = pd.DataFrame(
        {
            "timestamp": [start, start + timedelta(minutes=5)],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "action": [TradeAction.ENTER_LONG.value, TradeAction.EXIT.value],
            "size": [1.0, 1.0],
            "stop_loss": [0.01, 0.01],
            "take_profit": [0.03, 0.03],
            "reason": ["signal_entry", "signal_exit"],
        }
    )
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=_build_price_frame(),
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=6.0,
            slippage_bps=0.0,
            initial_equity=1000.0,
        ),
    )
    outputs = write_strategy_event_driven_outputs(
        strategy_name="Profile Action",
        report_base=tmp_path / "reports" / "backtests" / "strategy",
        run_id="20260320T000500Z_profile_action",
        config=EventDrivenBacktestConfig(symbol="BTCUSDT"),
        result=result,
        price_frame=_build_price_frame(),
        actions=actions,
        signal_interval_ms=60_000,
    )
    assert outputs["report_root"].endswith("reports/backtests/strategy/profile_action/20260320T000500Z_profile_action")
    assert outputs["strategy_collection_root"].endswith("reports/backtests/strategy")
    run_manifest_path = Path(outputs["report_root"]) / "run_manifest.json"
    assert run_manifest_path.exists()
    assert not (Path(outputs["strategy_collection_root"]) / "report_hub_index.json").exists()


def test_profile_action_strategy_backtest_smoke_writes_baseline_artifacts(tmp_path) -> None:
    bars = _build_profile_5m_frame(rows=420)
    strategy = ProfileActionStrategy()
    context = StrategyContext(
        as_of_time=pd.Timestamp(bars["timestamp"].iloc[-1]).to_pydatetime(),
        universe=("BTCUSDT",),
        inputs={"5m": bars},
        meta={"account_context": {"equity": 10_000.0, "open_positions": 0, "daily_pnl_pct": 0.0}},
    )
    strategy_result = strategy.generate_actions(context)
    actions = strategy_result.actions
    result = run_event_driven_backtest(
        actions=actions,
        price_frame=bars,
        config=EventDrivenBacktestConfig(
            symbol="BTCUSDT",
            interval_ms=300_000,
            execution_lag_bars=1,
            taker_fee_bps=6.0,
            slippage_bps=2.0,
            initial_equity=10_000.0,
        ),
    )
    outputs = write_strategy_event_driven_outputs(
        strategy_name="Profile Action",
        report_base=tmp_path / "reports" / "backtests" / "strategy",
        run_id="20260402T000000Z_profile_action_smoke",
        config=EventDrivenBacktestConfig(symbol="BTCUSDT", interval_ms=300_000),
        result=result,
        decision_trace=strategy_result.decision_trace,
        price_frame=bars,
        actions=actions,
        signal_interval_ms=300_000,
    )

    report_root = Path(outputs["report_root"])
    assert (report_root / "summary.json").exists()
    assert (report_root / "diagnostics.json").exists()
    assert (report_root / "ledgers" / "trades.parquet").exists()
    assert (report_root / "curves" / "equity_curve.parquet").exists()
    assert (report_root / "timelines" / "signal_execution.parquet").exists()
    assert (report_root / "timelines" / "decision_trace.parquet").exists()
    assert (report_root / "run_manifest.json").exists()

    summary = json.loads((report_root / "summary.json").read_text(encoding="utf-8"))
    for key in ("trade_count", "win_rate", "max_drawdown", "net_return"):
        assert key in summary

    diagnostics = json.loads((report_root / "diagnostics.json").read_text(encoding="utf-8"))
    assert int(diagnostics["diagnostics"]["scheduled_actions"]) >= 1
