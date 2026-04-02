from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from xtrader.backtests import EventDrivenBacktestConfig
from xtrader.runtime import ConfigLoader, PrecompileEngine, RuntimeContractError, RuntimeCore
from xtrader.strategies import (
    ActionStrategyResult,
    BaseActionStrategy,
    DEFAULT_ACTION_OUTPUT_SCHEMA,
    StrategyContext,
    StrategySpec,
    TradeAction,
)


def _build_runtime_config() -> dict[str, object]:
    return {
        "schema_version": "xtr_runtime_v1",
        "strategy_id": "runtime_single_trial_test",
        "execution_timeframe": "5m",
        "timeframes": ["5m"],
        "indicator_plan_by_tf": {
            "5m": [
                {"family": "ema", "instance_id": "ema_fast", "params": {"period": 5}},
                {"family": "macd", "instance_id": "macd_main", "params": {"fast": 12, "slow": 26, "signal": 9}},
            ]
        },
        "signal_rules": {"entry": {"mode": "dummy"}},
        "risk_rules": {
            "position_size": {"mode": "fixed_fraction", "value": 0.1},
            "stop_loss": {"mode": "atr_multiple", "n": 14, "k": 2.0},
            "take_profit": {"mode": "rr_multiple", "rr": 2.0},
        },
    }


def _build_scenarios_config() -> dict[str, object]:
    config = _build_runtime_config()
    config["trial_config"] = {
        "mode": "scenarios",
        "scenarios": [
            {
                "trial_id": "baseline",
                "changes": [],
            },
            {
                "trial_id": "ema_fast_8",
                "changes": [
                    {
                        "timeframe": "5m",
                        "instance_id": "ema_fast",
                        "params": {"period": 8},
                    }
                ],
            },
        ],
    }
    return config


def _build_runtime_config_with_implicit_feature_ref_warning() -> dict[str, object]:
    config = _build_runtime_config()
    config["signal_rules"] = {"entry": {"lhs": "5m.ema_fast.value"}}
    return config


def _build_bars(rows: int = 120) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=5 * idx) for idx in range(rows)]
    close_values = [100.0 + (idx * 0.15) + (((idx // 10) % 2) * 0.6) for idx in range(rows)]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": ["BTCUSDT"] * rows,
            "open": [value - 0.1 for value in close_values],
            "high": [value + 0.2 for value in close_values],
            "low": [value - 0.3 for value in close_values],
            "close": close_values,
            "volume": [1000.0 + (idx % 7) * 10.0 for idx in range(rows)],
        }
    )
    return frame


def _code_version() -> str:
    return "git:0123456789abcdef0123456789abcdef01234567"


@dataclass(slots=True)
class EmaTrendActionStrategy(BaseActionStrategy):
    strategy_id: str = "ema_trend_action"
    version: str = "v1"
    input_name: str = "features"
    ema_col: str = "ema_5"

    def spec(self) -> StrategySpec:
        return StrategySpec(
            strategy_id=self.strategy_id,
            version=self.version,
            required_inputs=(self.input_name,),
            output_schema=DEFAULT_ACTION_OUTPUT_SCHEMA,
            params_schema={},
        )

    def generate_actions(self, context: StrategyContext) -> ActionStrategyResult:
        features = context.require_input(self.input_name).copy()
        required = {"timestamp", "symbol", "close", self.ema_col}
        if not required.issubset(features.columns):
            missing = ",".join(sorted(required.difference(features.columns)))
            raise ValueError(f"missing columns for strategy inputs: {missing}")

        features["timestamp"] = pd.to_datetime(features["timestamp"], utc=True, errors="coerce")
        features["symbol"] = features["symbol"].astype(str).str.upper()
        features["close"] = pd.to_numeric(features["close"], errors="coerce")
        features[self.ema_col] = pd.to_numeric(features[self.ema_col], errors="coerce")
        features = features.dropna(subset=["timestamp", "symbol", "close", self.ema_col]).sort_values("timestamp").reset_index(drop=True)

        rows: list[dict[str, object]] = []
        for row in features.itertuples(index=False):
            close = float(row.close)
            ema = float(getattr(row, self.ema_col))
            if close > ema:
                action = TradeAction.ENTER_LONG.value
                size = 1.0
                reason = "trend_up"
            elif close < ema:
                action = TradeAction.EXIT.value
                size = 0.0
                reason = "trend_down"
            else:
                action = TradeAction.HOLD.value
                size = 0.0
                reason = "trend_flat"
            rows.append(
                {
                    "timestamp": row.timestamp,
                    "symbol": row.symbol,
                    "action": action,
                    "size": size,
                    "stop_loss": 0.01,
                    "take_profit": 0.02,
                    "reason": reason,
                }
            )

        actions = pd.DataFrame(
            rows,
            columns=["timestamp", "symbol", "action", "size", "stop_loss", "take_profit", "reason"],
        )
        result = ActionStrategyResult(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            actions=actions,
        )
        result.validate_schema(self.spec().output_schema)
        return result


def test_config_loader_applies_defaults() -> None:
    loader = ConfigLoader()
    loaded = loader.load(_build_runtime_config())
    assert loaded.resolved["warn_policy"] == "record_only"
    assert loaded.resolved["trial_config"] == {"mode": "single"}


def test_config_loader_rejects_unknown_top_level_fields() -> None:
    loader = ConfigLoader()
    config = _build_runtime_config()
    config["unknown_field"] = 1
    with pytest.raises(RuntimeContractError) as exc:
        loader.load(config)
    assert exc.value.code == "PC-CFG-002"


def test_config_loader_accepts_scenarios_mode_and_keeps_order() -> None:
    loader = ConfigLoader()
    loaded = loader.load(_build_scenarios_config())
    trial_config = loaded.resolved["trial_config"]
    assert trial_config["mode"] == "scenarios"
    assert [item["trial_id"] for item in trial_config["scenarios"]] == ["baseline", "ema_fast_8"]


def test_config_loader_rejects_duplicate_trial_id_with_tri_002() -> None:
    loader = ConfigLoader()
    config = _build_scenarios_config()
    config["trial_config"]["scenarios"][1]["trial_id"] = "baseline"
    with pytest.raises(RuntimeContractError) as exc:
        loader.load(config)
    assert exc.value.code == "PC-TRI-002"


def test_config_loader_rejects_duplicate_scenario_target_with_tri_002() -> None:
    loader = ConfigLoader()
    config = _build_scenarios_config()
    config["trial_config"]["scenarios"][1]["changes"].append(
        {
            "timeframe": "5m",
            "instance_id": "ema_fast",
            "params": {"period": 13},
        }
    )
    with pytest.raises(RuntimeContractError) as exc:
        loader.load(config)
    assert exc.value.code == "PC-TRI-002"


def test_config_loader_rejects_unknown_scenario_target_with_tri_001() -> None:
    loader = ConfigLoader()
    config = _build_scenarios_config()
    config["trial_config"]["scenarios"][1]["changes"][0]["instance_id"] = "ema_missing"
    with pytest.raises(RuntimeContractError) as exc:
        loader.load(config)
    assert exc.value.code == "PC-TRI-001"


def test_config_loader_resolve_trials_returns_stable_sequence() -> None:
    loader = ConfigLoader()
    loaded = loader.load(_build_scenarios_config())
    trials = loader.resolve_trials(loaded)
    assert [item["trial_id"] for item in trials] == ["baseline", "ema_fast_8"]
    baseline = next(item for item in trials if item["trial_id"] == "baseline")
    optimized = next(item for item in trials if item["trial_id"] == "ema_fast_8")

    def _find_period(trial: dict[str, object]) -> int:
        indicator_plan = trial["resolved_config"]["indicator_plan_by_tf"]["5m"]
        for item in indicator_plan:
            if item["instance_id"] == "ema_fast":
                return int(item["params"]["period"])
        raise AssertionError("ema_fast not found")

    assert _find_period(baseline) == 5
    assert _find_period(optimized) == 8


def test_precompile_engine_builds_feature_catalog_for_v1_feature_refs() -> None:
    config = _build_runtime_config()
    result = PrecompileEngine().compile(config)
    assert result.status == "SUCCESS"
    refs = [item["feature_ref"] for item in result.feature_catalog]
    assert "5m.ema_fast.value" in refs
    assert "5m.macd_main.line" in refs
    assert "5m.macd_main.signal" in refs
    assert "5m.macd_main.hist" in refs
    assert all(str(item["params_hash"]).startswith("sha256:") for item in result.feature_catalog)


def test_precompile_engine_requires_selector_for_scenarios() -> None:
    result = PrecompileEngine().compile(_build_scenarios_config())
    assert result.status == "FAILED"
    assert result.error_code == "PC-TRI-001"


def test_precompile_engine_compiles_selected_scenario() -> None:
    result = PrecompileEngine().compile(_build_scenarios_config(), trial_selector="ema_fast_8")
    assert result.status == "SUCCESS"
    assert result.precompile_report["trial_id"] == "ema_fast_8"
    ema_fast_rows = [item for item in result.feature_catalog if item["feature_ref"] == "5m.ema_fast.value"]
    assert len(ema_fast_rows) == 1
    assert int(ema_fast_rows[0]["resolved_params"]["period"]) == 8


def test_precompile_engine_rejects_unknown_trial_selector() -> None:
    result = PrecompileEngine().compile(_build_scenarios_config(), trial_selector="unknown_trial")
    assert result.status == "FAILED"
    assert result.error_code == "PC-TRI-001"


def test_precompile_engine_record_only_keeps_success_with_warnings() -> None:
    config = _build_runtime_config_with_implicit_feature_ref_warning()
    result = PrecompileEngine().compile(config)
    assert result.status == "SUCCESS"
    assert result.precompile_report["warn_policy"] == "record_only"
    assert int(result.precompile_report["warn_count"]) >= 1
    assert "PC-REF-101" in result.precompile_report["warn_codes"]


def test_precompile_engine_warn_policy_error_blocks_on_warning() -> None:
    config = _build_runtime_config_with_implicit_feature_ref_warning()
    config["warn_policy"] = "error"
    result = PrecompileEngine().compile(config)
    assert result.status == "FAILED"
    assert result.error_code == "PC-REF-101"
    assert result.precompile_report["warn_policy"] == "error"
    assert int(result.precompile_report["warn_count"]) >= 1


def test_precompile_engine_rejects_unresolved_feature_ref_with_pc_ref_001() -> None:
    config = _build_runtime_config()
    config["signal_rules"] = {"entry": {"feature_ref": "5m.ema_missing.value"}}
    result = PrecompileEngine().compile(config)
    assert result.status == "FAILED"
    assert result.error_code == "PC-REF-001"
    err = result.precompile_report["errors"][0]
    assert err["feature_ref"] == "5m.ema_missing.value"
    assert err["timeframe"] == "5m"
    assert err["instance_id"] == "ema_missing"
    assert "suggestion" in err


def test_precompile_engine_rejects_invalid_output_key_with_pc_out_001() -> None:
    config = _build_runtime_config()
    config["signal_rules"] = {"entry": {"feature_ref": "5m.macd_main.foo"}}
    result = PrecompileEngine().compile(config)
    assert result.status == "FAILED"
    assert result.error_code == "PC-OUT-001"
    err = result.precompile_report["errors"][0]
    assert err["feature_ref"] == "5m.macd_main.foo"
    assert err["timeframe"] == "5m"
    assert err["instance_id"] == "macd_main"


def test_runtime_core_run_backtest_single_trial_success(tmp_path) -> None:
    config = _build_runtime_config()
    bars = _build_bars()
    run_root = tmp_path / "runs" / "runtime_single_trial"

    core = RuntimeCore()
    result = core.run(
        config=config,
        data_source={
            "strategy": EmaTrendActionStrategy(),
            "bars_by_timeframe": {"5m": bars},
            "run_root": run_root,
            "code_version": _code_version(),
            "backtest_config": EventDrivenBacktestConfig(
                symbol="BTCUSDT",
                interval_ms=300_000,
                execution_lag_bars=1,
                taker_fee_bps=0.0,
                slippage_bps=0.0,
                initial_equity=1000.0,
            ),
        },
        mode="backtest",
    )

    assert result.status == "SUCCESS"
    assert result.run_id == "runtime_single_trial"
    assert result.artifacts_root == str(run_root)
    assert run_root.exists()
    assert (run_root / "strategy_config.raw.json").exists()
    assert (run_root / "strategy_config.resolved.json").exists()
    assert (run_root / "feature_catalog.json").exists()
    assert (run_root / "precompile_report.json").exists()
    assert (run_root / "run_manifest.json").exists()
    assert (run_root / "summary.json").exists()
    assert (run_root / "artifacts" / "summary.parquet").exists()
    assert (run_root / "artifacts" / "signals.parquet").exists()
    assert (run_root / "artifacts" / "decision_trace.parquet").exists()
    assert (run_root / "artifacts" / "trades.parquet").exists()
    assert (run_root / "artifacts" / "equity.parquet").exists()
    assert (run_root / "data_snapshot" / "raw" / "5m.parquet").exists()
    assert (run_root / "data_snapshot" / "dataset_index.json").exists()
    assert (run_root / "data_snapshot" / "snapshot_meta.json").exists()

    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1
    assert manifest["run_status"] == "SUCCESS"
    assert manifest["trial_summary"]["total_trials"] == 1
    assert "config_refs" in manifest
    assert manifest["artifact_refs"]["summary"] == "artifacts/summary.parquet"
    assert manifest["artifact_refs"]["signals"] == "artifacts/signals.parquet"
    assert manifest["artifact_refs"]["decision_trace"] == "artifacts/decision_trace.parquet"
    assert manifest["data_snapshot_refs"]["raw"]["5m"] == "data_snapshot/raw/5m.parquet"
    assert manifest["viewer_contract"]["status"] == "READY"
    assert manifest["viewer_contract"]["missing_required_files"] == []
    optional_status = {item["path"]: item["status"] for item in manifest["viewer_contract"]["optional_files"]}
    assert optional_status["artifacts/diagnostics.parquet"] == "NOT_AVAILABLE"
    assert optional_status["feature_catalog.json"] == "AVAILABLE"
    assert optional_status["precompile_report.json"] == "AVAILABLE"
    assert manifest["code_version"] == _code_version()
    assert str(manifest["data_version"]).startswith("data:sha256:")
    perf = manifest["performance_log"]
    assert int(perf["elapsed_ms"]) >= 0
    assert float(perf["peak_rss_mb"]) >= 0.0
    assert int(perf["trials_count"]) == 1
    assert int(perf["bars_count"]) == int(len(bars.index))
    assert perf["status"] == "SUCCESS"

    dataset_index = json.loads((run_root / "data_snapshot" / "dataset_index.json").read_text(encoding="utf-8"))
    assert len(dataset_index["datasets"]) == 1
    assert dataset_index["datasets"][0]["kind"] == "raw"
    assert dataset_index["datasets"][0]["timeframe"] == "5m"
    assert dataset_index["datasets"][0]["path"] == "data_snapshot/raw/5m.parquet"
    assert dataset_index["datasets"][0]["timezone"] == "UTC"
    assert dataset_index["datasets"][0]["label_semantics"] == "open_time"

    snapshot_meta = json.loads((run_root / "data_snapshot" / "snapshot_meta.json").read_text(encoding="utf-8"))
    assert snapshot_meta["execution_timeframe"] == "5m"
    assert snapshot_meta["required_timeframes"] == ["5m"]
    assert snapshot_meta["timeframes"] == ["5m"]
    assert str(snapshot_meta["data_version"]).startswith("data:sha256:")
    assert snapshot_meta["data_version"] == manifest["data_version"]

    summary_payload = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
    assert summary_payload["code_version"] == _code_version()
    assert summary_payload["data_version"] == manifest["data_version"]
    summary_frame = pd.read_parquet(run_root / "artifacts" / "summary.parquet")
    assert str(summary_frame.loc[0, "code_version"]) == _code_version()
    assert str(summary_frame.loc[0, "data_version"]) == manifest["data_version"]


def test_runtime_core_aborts_when_single_trial_execution_fails(tmp_path) -> None:
    bars = _build_bars()
    core = RuntimeCore()
    run_root = tmp_path / "runs" / "runtime_single_trial_fail"
    result = core.run(
        config=_build_runtime_config(),
        data_source={
            "strategy": EmaTrendActionStrategy(ema_col="ema_not_found"),
            "bars_by_timeframe": {"5m": bars},
            "run_root": run_root,
            "code_version": _code_version(),
        },
        mode="backtest",
    )
    assert result.status == "FAILED"
    assert result.error_code in {"RT-RUN-001", "PC-CFG-003"}


def test_runtime_core_warn_policy_override_cli_over_config(tmp_path) -> None:
    bars = _build_bars()
    core = RuntimeCore()
    run_root = tmp_path / "runs" / "runtime_warn_override"
    config = _build_runtime_config_with_implicit_feature_ref_warning()
    config["warn_policy"] = "error"
    result = core.run(
        config=config,
        data_source={
            "strategy": EmaTrendActionStrategy(),
            "bars_by_timeframe": {"5m": bars},
            "run_root": run_root,
            "code_version": _code_version(),
            "warn_policy": "record_only",
        },
        mode="backtest",
    )
    assert result.status == "SUCCESS"
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["warn_policy"] == "record_only"
    assert int(manifest["warn_count"]) >= 1


def test_runtime_core_warn_policy_override_to_error_blocks(tmp_path) -> None:
    bars = _build_bars()
    core = RuntimeCore()
    config = _build_runtime_config_with_implicit_feature_ref_warning()
    result = core.run(
        config=config,
        data_source={
            "strategy": EmaTrendActionStrategy(),
            "bars_by_timeframe": {"5m": bars},
            "run_root": tmp_path / "runs" / "runtime_warn_override_error",
            "code_version": _code_version(),
            "warn_policy": "error",
        },
        mode="backtest",
    )
    assert result.status == "FAILED"
    assert result.error_code == "PC-REF-101"


def test_runtime_core_continues_on_multi_trial_failures(tmp_path) -> None:
    bars = _build_bars()
    core = RuntimeCore()
    run_root = tmp_path / "runs" / "runtime_multi_trial_partial"
    result = core.run(
        config=_build_scenarios_config(),
        data_source={
            "strategy": EmaTrendActionStrategy(),
            "bars_by_timeframe": {"5m": bars},
            "run_root": run_root,
            "code_version": _code_version(),
        },
        mode="backtest",
    )
    assert result.status == "PARTIAL_SUCCESS"
    assert result.manifest_path
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_status"] == "PARTIAL_SUCCESS"
    assert int(manifest["exit_code"]) == 2
    assert manifest["trial_summary"]["total_trials"] == 2
    assert manifest["trial_summary"]["succeeded_trial_ids"] == ["baseline"]
    assert manifest["trial_summary"]["failed_trial_ids"] == ["ema_fast_8"]


def test_runtime_core_marks_viewer_contract_invalid_when_required_snapshot_missing(tmp_path) -> None:
    bars = _build_bars()
    core = RuntimeCore()
    run_root = tmp_path / "runs" / "runtime_missing_resampled_snapshot"
    config = _build_runtime_config()
    config["timeframes"] = ["5m", "15m"]
    result = core.run(
        config=config,
        data_source={
            "strategy": EmaTrendActionStrategy(),
            "bars_by_timeframe": {"5m": bars},
            "run_root": run_root,
            "code_version": _code_version(),
        },
        mode="backtest",
    )
    assert result.status == "SUCCESS"
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["viewer_contract"]["status"] == "INVALID_RUN"
    missing = set(manifest["viewer_contract"]["missing_required_files"])
    assert "data_snapshot/resampled/15m.parquet" in missing


def test_runtime_core_rejects_invalid_code_version_override(tmp_path) -> None:
    bars = _build_bars()
    core = RuntimeCore()
    result = core.run(
        config=_build_runtime_config(),
        data_source={
            "strategy": EmaTrendActionStrategy(),
            "bars_by_timeframe": {"5m": bars},
            "run_root": tmp_path / "runs" / "runtime_bad_code_version",
            "code_version": "git:bad",
        },
        mode="backtest",
    )
    assert result.status == "FAILED"
    assert result.error_code == "PC-CFG-003"


def test_runtime_core_is_stable_for_traceability_hashes(tmp_path) -> None:
    bars = _build_bars()
    core = RuntimeCore()
    config = _build_runtime_config()
    run_root_a = tmp_path / "runs" / "runtime_traceability_a"
    run_root_b = tmp_path / "runs" / "runtime_traceability_b"
    run_root_c = tmp_path / "runs" / "runtime_traceability_c"
    data_source_base = {
        "strategy": EmaTrendActionStrategy(),
        "bars_by_timeframe": {"5m": bars},
        "code_version": _code_version(),
    }
    result_a = core.run(
        config=config,
        data_source={**data_source_base, "run_root": run_root_a},
        mode="backtest",
    )
    result_b = core.run(
        config=config,
        data_source={**data_source_base, "run_root": run_root_b},
        mode="backtest",
    )
    result_c = core.run(
        config=config,
        data_source={**data_source_base, "run_root": run_root_c},
        mode="backtest",
    )
    assert result_a.status == "SUCCESS"
    assert result_b.status == "SUCCESS"
    assert result_c.status == "SUCCESS"
    manifest_a = json.loads((run_root_a / "run_manifest.json").read_text(encoding="utf-8"))
    manifest_b = json.loads((run_root_b / "run_manifest.json").read_text(encoding="utf-8"))
    manifest_c = json.loads((run_root_c / "run_manifest.json").read_text(encoding="utf-8"))
    for key in ("run_status", "config_hash", "catalog_hash", "data_version"):
        assert manifest_a[key] == manifest_b[key]
        assert manifest_a[key] == manifest_c[key]
