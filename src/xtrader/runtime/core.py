"""Runtime Core v1 (backtest-first)."""

from __future__ import annotations

import copy
import json
import re
import resource
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from xtrader.backtests import EventDrivenBacktestConfig, EventDrivenBacktestResult, run_event_driven_backtest, write_event_driven_outputs
from xtrader.runtime.config import ConfigLoader, LoadedRuntimeConfig
from xtrader.runtime.errors import RuntimeContractError
from xtrader.runtime.hash_utils import sha256_hex
from xtrader.runtime.precompile import PrecompileEngine, PrecompileResult
from xtrader.strategies import FeaturePipeline, StrategyContext

_TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}
_WARN_POLICY_ALLOWED: tuple[str, ...] = ("record_only", "error")
_CODE_VERSION_PATTERN = re.compile(r"^git:[0-9a-f]{40}(?:\+dirty)?$")


@dataclass(frozen=True, slots=True)
class RuntimeRunResult:
    run_id: str
    status: str
    artifacts_root: str
    manifest_path: str
    summary_path: str
    error_code: str | None = None
    error_message: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)


class RuntimeCore:
    """Runtime orchestrator for backtest mode."""

    def __init__(
        self,
        *,
        config_loader: ConfigLoader | None = None,
        precompile_engine: PrecompileEngine | None = None,
        feature_pipeline: FeaturePipeline | None = None,
    ) -> None:
        self.config_loader = config_loader or ConfigLoader()
        self.precompile_engine = precompile_engine or PrecompileEngine(config_loader=self.config_loader)
        self.feature_pipeline = feature_pipeline or FeaturePipeline()

    def run(
        self,
        config: dict[str, Any] | str | LoadedRuntimeConfig,
        data_source: dict[str, Any],
        mode: str = "backtest",
    ) -> RuntimeRunResult:
        run_root: Path | None = None
        run_id = ""
        started_at = time.perf_counter()
        code_version: str | None = None
        try:
            if mode != "backtest":
                raise RuntimeContractError(
                    code="PC-CFG-003",
                    stage="runtime",
                    path="$.mode",
                    message="v1 only supports mode=backtest",
                )
            loaded = config if isinstance(config, LoadedRuntimeConfig) else self.config_loader.load(config)
            loaded = self._apply_warn_policy_override(loaded=loaded, data_source=data_source)
            trial_plan = self.config_loader.resolve_trials(loaded)
            if not trial_plan:
                raise RuntimeContractError(
                    code="PC-TRI-001",
                    stage="runtime",
                    path="$.trial_config",
                    message="no trials resolved from trial_config",
                )
            code_version = self._resolve_code_version(data_source=data_source)
            run_root = self._resolve_run_root(data_source=data_source, strategy_id=str(loaded.resolved["strategy_id"]))
            run_id = run_root.name
            run_root.mkdir(parents=True, exist_ok=True)

            config_paths = self._write_runtime_config_files(run_root=run_root, loaded=loaded)
            total_trials = int(len(trial_plan))
            succeeded_trial_ids: list[str] = []
            failed_trial_ids: list[str] = []
            skipped_trial_ids: list[str] = []
            trial_errors: dict[str, dict[str, Any]] = {}
            primary_trial_id: str | None = None
            primary_precompile: PrecompileResult | None = None
            primary_loaded: LoadedRuntimeConfig | None = None
            primary_trial_outputs: dict[str, Any] | None = None

            # M2-E: precompile all trials first, then enter execution scheduling.
            precompile_by_trial: dict[str, PrecompileResult] = {}
            for trial in trial_plan:
                trial_id = str(trial["trial_id"])
                selector = trial_id if total_trials > 1 else None
                precompile = self.precompile_engine.compile(loaded, trial_selector=selector)
                precompile_by_trial[trial_id] = precompile
                if precompile.status != "SUCCESS":
                    failed_trial_ids.append(trial_id)
                    trial_errors[trial_id] = {
                        "stage": "precompile",
                        "code": precompile.error_code,
                        "message": precompile.error_message,
                    }
                    if total_trials == 1:
                        precompile_paths = self._write_precompile_files(run_root=run_root, precompile=precompile)
                        return RuntimeRunResult(
                            run_id=run_id,
                            status="FAILED",
                            artifacts_root=str(run_root),
                            manifest_path="",
                            summary_path="",
                            error_code=precompile.error_code,
                            error_message=precompile.error_message,
                            outputs={
                                "config_paths": config_paths,
                                "precompile_paths": precompile_paths,
                                "trial_summary": {
                                    "total_trials": total_trials,
                                    "succeeded_trial_ids": succeeded_trial_ids,
                                    "failed_trial_ids": failed_trial_ids,
                                    "skipped_trial_ids": skipped_trial_ids,
                                },
                                "trial_errors": trial_errors,
                            },
                        )

            for trial in trial_plan:
                trial_id = str(trial["trial_id"])
                precompile = precompile_by_trial[trial_id]
                if precompile.status != "SUCCESS":
                    continue
                trial_loaded = LoadedRuntimeConfig(
                    raw=copy.deepcopy(loaded.raw),
                    resolved=copy.deepcopy(precompile.resolved_config),
                )
                try:
                    trial_outputs = self._execute_trial(
                        loaded=trial_loaded,
                        trial_id=trial_id,
                        data_source=data_source,
                    )
                    succeeded_trial_ids.append(trial_id)
                    if primary_trial_outputs is None:
                        primary_trial_outputs = trial_outputs
                        primary_precompile = precompile
                        primary_loaded = trial_loaded
                        primary_trial_id = trial_id
                except RuntimeContractError as err:
                    failed_trial_ids.append(trial_id)
                    trial_errors[trial_id] = {
                        "stage": "runtime",
                        "code": err.code,
                        "message": err.message,
                    }
                    if total_trials == 1:
                        raise
                except Exception as err:  # pragma: no cover - defensive guard
                    runtime_error = RuntimeContractError(
                        code="RT-RUN-001",
                        stage="runtime",
                        path=f"$.trials.{trial_id}",
                        message=str(err),
                    )
                    failed_trial_ids.append(trial_id)
                    trial_errors[trial_id] = {
                        "stage": "runtime",
                        "code": runtime_error.code,
                        "message": runtime_error.message,
                    }
                    if total_trials == 1:
                        raise runtime_error

            if primary_trial_outputs is None or primary_precompile is None or primary_loaded is None:
                first_error = trial_errors.get(failed_trial_ids[0], {}) if failed_trial_ids else {}
                return RuntimeRunResult(
                    run_id=run_id,
                    status="FAILED",
                    artifacts_root=str(run_root),
                    manifest_path="",
                    summary_path="",
                    error_code=str(first_error.get("code", "PC-TRI-001")),
                    error_message=str(first_error.get("message", "all trials failed")),
                    outputs={
                        "config_paths": config_paths,
                        "trial_summary": {
                            "total_trials": total_trials,
                            "succeeded_trial_ids": succeeded_trial_ids,
                            "failed_trial_ids": failed_trial_ids,
                            "skipped_trial_ids": skipped_trial_ids,
                        },
                        "trial_errors": trial_errors,
                    },
                )

            outputs = write_event_driven_outputs(
                report_root=run_root,
                config=primary_trial_outputs["backtest_config"],
                result=primary_trial_outputs["output_result"],
                decision_trace=primary_trial_outputs.get("decision_trace"),
                resampled_price_frames=primary_trial_outputs["resampled_frames"],
                strategy_name=str(primary_loaded.resolved["strategy_id"]),
            )
            precompile_paths = self._write_precompile_files(run_root=run_root, precompile=primary_precompile)
            viewer_outputs = self._write_viewer_contract_outputs(
                run_root=run_root,
                loaded=primary_loaded,
                precompile_paths=precompile_paths,
                trial_outputs=primary_trial_outputs,
                backtest_outputs=outputs,
                code_version=code_version,
            )
            run_status, exit_code = self._derive_run_outcome(
                succeeded_trial_ids=succeeded_trial_ids,
                failed_trial_ids=failed_trial_ids,
                skipped_trial_ids=skipped_trial_ids,
            )
            performance_log = self._build_performance_log(
                started_at=started_at,
                status=run_status,
                total_trials=total_trials,
                bars_count=int(len(primary_trial_outputs["output_result"].price_input_snapshot.index)),
            )
            self._patch_manifest_v1(
                run_root=run_root,
                loaded=primary_loaded,
                precompile_paths=precompile_paths,
                precompile=primary_precompile,
                run_status=run_status,
                exit_code=exit_code,
                trial_summary={
                    "total_trials": total_trials,
                    "succeeded_trial_ids": succeeded_trial_ids,
                    "failed_trial_ids": failed_trial_ids,
                    "skipped_trial_ids": skipped_trial_ids,
                },
                viewer_outputs=viewer_outputs,
                code_version=code_version,
                performance_log=performance_log,
            )
            manifest_path = str(outputs["run_manifest_path"])
            summary_path = str(outputs["summary_path"])
            return RuntimeRunResult(
                run_id=run_id,
                status=run_status,
                artifacts_root=str(run_root),
                manifest_path=manifest_path,
                summary_path=summary_path,
                outputs={
                    "primary_trial_id": primary_trial_id,
                    "config_paths": config_paths,
                    "precompile_paths": precompile_paths,
                    "backtest_outputs": outputs,
                    "viewer_outputs": viewer_outputs,
                    "trial_summary": {
                        "total_trials": total_trials,
                        "succeeded_trial_ids": succeeded_trial_ids,
                        "failed_trial_ids": failed_trial_ids,
                        "skipped_trial_ids": skipped_trial_ids,
                    },
                    "trial_errors": trial_errors,
                },
            )
        except RuntimeContractError as err:
            if run_root is not None:
                self._write_runtime_error(run_root=run_root, error=err)
            return RuntimeRunResult(
                run_id=run_id or "unknown",
                status="FAILED",
                artifacts_root=str(run_root) if run_root is not None else "",
                manifest_path="",
                summary_path="",
                error_code=err.code,
                error_message=err.message,
            )
        except Exception as err:  # pragma: no cover - defensive guard
            runtime_error = RuntimeContractError(
                code="RT-RUN-001",
                stage="runtime",
                path="$.runtime",
                message=str(err),
            )
            if run_root is not None:
                self._write_runtime_error(run_root=run_root, error=runtime_error)
            return RuntimeRunResult(
                run_id=run_id or "unknown",
                status="FAILED",
                artifacts_root=str(run_root) if run_root is not None else "",
                manifest_path="",
                summary_path="",
                error_code=runtime_error.code,
                error_message=runtime_error.message,
            )

    def _resolve_run_root(self, *, data_source: dict[str, Any], strategy_id: str) -> Path:
        explicit = data_source.get("run_root")
        if explicit is not None:
            return Path(explicit)
        run_id = self._build_run_id(strategy_id=strategy_id)
        return Path("runs") / run_id

    def _build_run_id(self, *, strategy_id: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = "".join(ch if ch.isalnum() else "_" for ch in strategy_id.strip().lower()).strip("_") or "strategy"
        return f"{ts}_{slug}"

    def _write_runtime_config_files(self, *, run_root: Path, loaded: LoadedRuntimeConfig) -> dict[str, str]:
        raw_path = run_root / "strategy_config.raw.json"
        resolved_path = run_root / "strategy_config.resolved.json"
        raw_path.write_text(json.dumps(loaded.raw, ensure_ascii=False, indent=2), encoding="utf-8")
        resolved_path.write_text(json.dumps(loaded.resolved, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "raw_config_path": str(raw_path),
            "resolved_config_path": str(resolved_path),
        }

    def _write_precompile_files(self, *, run_root: Path, precompile: PrecompileResult) -> dict[str, str]:
        catalog_path = run_root / "feature_catalog.json"
        report_path = run_root / "precompile_report.json"
        catalog_path.write_text(json.dumps(precompile.feature_catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path.write_text(json.dumps(precompile.precompile_report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "feature_catalog_path": str(catalog_path),
            "precompile_report_path": str(report_path),
        }

    def _patch_manifest_v1(
        self,
        *,
        run_root: Path,
        loaded: LoadedRuntimeConfig,
        precompile_paths: dict[str, str],
        precompile: PrecompileResult,
        run_status: str,
        exit_code: int,
        trial_summary: dict[str, Any],
        viewer_outputs: dict[str, Any],
        code_version: str,
        performance_log: dict[str, Any],
    ) -> None:
        manifest_path = run_root / "run_manifest.json"
        if not manifest_path.exists():
            return
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["manifest_version"] = 1
        payload["run_status"] = str(run_status)
        payload["exit_code"] = int(exit_code)
        payload["trial_summary"] = copy.deepcopy(trial_summary)
        payload["config_refs"] = {
            "raw_config": "strategy_config.raw.json",
            "resolved_config": "strategy_config.resolved.json",
            "feature_catalog": Path(precompile_paths["feature_catalog_path"]).name,
            "precompile_report": Path(precompile_paths["precompile_report_path"]).name,
        }
        payload["warn_policy"] = str(loaded.resolved.get("warn_policy", "record_only"))
        payload["warn_count"] = int(precompile.precompile_report.get("warn_count", 0) or 0)
        payload["warn_codes"] = list(precompile.precompile_report.get("warn_codes", []))
        payload["config_hash"] = f"sha256:{self._hash_payload(loaded.resolved)}"
        payload["catalog_hash"] = f"sha256:{self._hash_payload(precompile.feature_catalog)}"
        payload["code_version"] = code_version
        artifact_refs = dict(viewer_outputs.get("artifact_refs", {}))
        if artifact_refs:
            payload["artifact_refs"] = artifact_refs
        data_snapshot_refs = dict(viewer_outputs.get("data_snapshot_refs", {}))
        if data_snapshot_refs:
            payload["data_snapshot_refs"] = data_snapshot_refs
        viewer_contract = dict(viewer_outputs.get("viewer_contract", {}))
        if viewer_contract:
            payload["viewer_contract"] = viewer_contract
        data_version = viewer_outputs.get("data_version")
        if isinstance(data_version, str) and data_version:
            payload["data_version"] = data_version
        if "summary" in payload and isinstance(payload["summary"], dict):
            payload["summary"]["code_version"] = code_version
            if isinstance(data_version, str) and data_version:
                payload["summary"]["data_version"] = data_version
        payload["performance_log"] = dict(performance_log)
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_viewer_contract_outputs(
        self,
        *,
        run_root: Path,
        loaded: LoadedRuntimeConfig,
        precompile_paths: dict[str, str],
        trial_outputs: dict[str, Any],
        backtest_outputs: dict[str, str],
        code_version: str,
    ) -> dict[str, Any]:
        artifacts_root = run_root / "artifacts"
        data_snapshot_root = run_root / "data_snapshot"
        raw_root = data_snapshot_root / "raw"
        resampled_root = data_snapshot_root / "resampled"
        artifacts_root.mkdir(parents=True, exist_ok=True)
        data_snapshot_root.mkdir(parents=True, exist_ok=True)
        raw_root.mkdir(parents=True, exist_ok=True)
        resampled_root.mkdir(parents=True, exist_ok=True)

        summary_json_path = Path(str(backtest_outputs["summary_path"]))
        summary_payload = json.loads(summary_json_path.read_text(encoding="utf-8"))

        signals_source_path = Path(str(backtest_outputs["signal_execution_path"]))
        signals_frame = pd.read_parquet(signals_source_path)
        signals_parquet_path = artifacts_root / "signals.parquet"
        signals_frame.to_parquet(signals_parquet_path, index=False)

        decision_trace_source_path = Path(str(backtest_outputs["decision_trace_path"]))
        decision_trace_frame = pd.read_parquet(decision_trace_source_path)
        decision_trace_parquet_path = artifacts_root / "decision_trace.parquet"
        decision_trace_frame.to_parquet(decision_trace_parquet_path, index=False)

        trades_source_path = Path(str(backtest_outputs["trades_parquet_path"]))
        trades_frame = pd.read_parquet(trades_source_path)
        trades_parquet_path = artifacts_root / "trades.parquet"
        trades_frame.to_parquet(trades_parquet_path, index=False)

        equity_source_path = Path(str(backtest_outputs["equity_curve_parquet_path"]))
        equity_frame = pd.read_parquet(equity_source_path)
        equity_parquet_path = artifacts_root / "equity.parquet"
        equity_frame.to_parquet(equity_parquet_path, index=False)

        execution_tf = str(loaded.resolved["execution_timeframe"])
        timeframes = [str(item) for item in loaded.resolved.get("timeframes", [])]
        required_timeframes = list(timeframes)

        price_snapshot = trial_outputs["output_result"].price_input_snapshot.copy(deep=True)
        raw_snapshot_path = raw_root / f"{execution_tf}.parquet"
        price_snapshot.to_parquet(raw_snapshot_path, index=False)

        datasets: list[dict[str, Any]] = []
        datasets.append(
            self._build_dataset_entry(
                kind="raw",
                timeframe=execution_tf,
                path=raw_snapshot_path,
                frame=price_snapshot,
                run_root=run_root,
            )
        )

        resampled_paths: dict[str, str] = {}
        resampled_frames: dict[str, pd.DataFrame] = trial_outputs.get("resampled_frames", {})
        for timeframe in sorted(tf for tf in timeframes if tf != execution_tf):
            frame = resampled_frames.get(timeframe)
            if not isinstance(frame, pd.DataFrame):
                continue
            target = resampled_root / f"{timeframe}.parquet"
            frame_copy = frame.copy(deep=True)
            frame_copy.to_parquet(target, index=False)
            datasets.append(
                self._build_dataset_entry(
                    kind="resampled",
                    timeframe=timeframe,
                    path=target,
                    frame=frame_copy,
                    run_root=run_root,
                )
            )
            resampled_paths[timeframe] = str(target.relative_to(run_root).as_posix())

        dataset_index_path = data_snapshot_root / "dataset_index.json"
        dataset_index_payload = {
            "version": "v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "datasets": sorted(datasets, key=lambda item: (str(item["kind"]), str(item["timeframe"]))),
        }
        dataset_index_path.write_text(json.dumps(dataset_index_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        source_range = self._extract_time_range(price_snapshot)
        snapshot_meta_path = data_snapshot_root / "snapshot_meta.json"
        snapshot_meta_payload = {
            "version": "v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "exchange": "UNKNOWN",
            "market": "backtest",
            "symbol": str(trial_outputs["backtest_config"].symbol),
            "execution_timeframe": execution_tf,
            "timeframes": timeframes,
            "required_timeframes": required_timeframes,
            "source_range": source_range,
            "resample_rule": {
                "provider": "runtime_core_v1",
                "label_semantics": "open_time",
                "timezone": "UTC",
            },
            "data_version": "",
        }
        semantic_dataset_index = {
            "version": dataset_index_payload["version"],
            "datasets": dataset_index_payload["datasets"],
        }
        semantic_snapshot_meta = {
            key: value
            for key, value in snapshot_meta_payload.items()
            if key not in ("generated_at", "data_version")
        }
        data_version = f"data:sha256:{self._hash_payload({'dataset_index': semantic_dataset_index, 'snapshot_meta': semantic_snapshot_meta})}"
        snapshot_meta_payload["data_version"] = data_version
        snapshot_meta_path.write_text(json.dumps(snapshot_meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        summary_payload["code_version"] = code_version
        summary_payload["data_version"] = data_version
        summary_json_path.write_text(json.dumps(summary_payload, ensure_ascii=True, indent=2), encoding="utf-8")
        summary_parquet_path = artifacts_root / "summary.parquet"
        pd.DataFrame([summary_payload]).to_parquet(summary_parquet_path, index=False)

        required_files = [
            "run_manifest.json",
            "artifacts/summary.parquet",
            "artifacts/signals.parquet",
            "artifacts/decision_trace.parquet",
            "artifacts/trades.parquet",
            "artifacts/equity.parquet",
            "data_snapshot/dataset_index.json",
            "data_snapshot/snapshot_meta.json",
            f"data_snapshot/raw/{execution_tf}.parquet",
        ]
        for timeframe in required_timeframes:
            if timeframe == execution_tf:
                continue
            required_files.append(f"data_snapshot/resampled/{timeframe}.parquet")
        optional_files = [
            "artifacts/diagnostics.parquet",
            str(Path(precompile_paths["feature_catalog_path"]).relative_to(run_root).as_posix()),
            str(Path(precompile_paths["precompile_report_path"]).relative_to(run_root).as_posix()),
        ]
        missing_required_files = [path for path in required_files if not (run_root / path).exists()]
        optional_status = [
            {
                "path": path,
                "status": "AVAILABLE" if (run_root / path).exists() else "NOT_AVAILABLE",
            }
            for path in optional_files
        ]
        viewer_status = "INVALID_RUN" if missing_required_files else "READY"

        return {
            "artifact_refs": {
                "summary": str(summary_parquet_path.relative_to(run_root).as_posix()),
                "signals": str(signals_parquet_path.relative_to(run_root).as_posix()),
                "decision_trace": str(decision_trace_parquet_path.relative_to(run_root).as_posix()),
                "trades": str(trades_parquet_path.relative_to(run_root).as_posix()),
                "equity": str(equity_parquet_path.relative_to(run_root).as_posix()),
            },
            "data_snapshot_refs": {
                "raw": {
                    execution_tf: str(raw_snapshot_path.relative_to(run_root).as_posix()),
                },
                "resampled": resampled_paths,
                "dataset_index": str(dataset_index_path.relative_to(run_root).as_posix()),
                "snapshot_meta": str(snapshot_meta_path.relative_to(run_root).as_posix()),
            },
            "viewer_contract": {
                "status": viewer_status,
                "required_files": required_files,
                "missing_required_files": missing_required_files,
                "optional_files": optional_status,
            },
            "data_version": data_version,
        }

    def _build_dataset_entry(
        self,
        *,
        kind: str,
        timeframe: str,
        path: Path,
        frame: pd.DataFrame,
        run_root: Path,
    ) -> dict[str, Any]:
        time_range = self._extract_time_range(frame)
        return {
            "kind": str(kind),
            "timeframe": str(timeframe),
            "path": str(path.relative_to(run_root).as_posix()),
            "row_count": int(len(frame.index)),
            "start": time_range["start"],
            "end": time_range["end"],
            "timezone": "UTC",
            "label_semantics": "open_time",
        }

    def _extract_time_range(self, frame: pd.DataFrame) -> dict[str, str | None]:
        if "timestamp" not in frame.columns:
            return {"start": None, "end": None}
        values = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce").dropna()
        if values.empty:
            return {"start": None, "end": None}
        return {
            "start": values.iloc[0].isoformat(),
            "end": values.iloc[-1].isoformat(),
        }

    def _execute_trial(
        self,
        *,
        loaded: LoadedRuntimeConfig,
        trial_id: str,
        data_source: dict[str, Any],
    ) -> dict[str, Any]:
        execution_tf = str(loaded.resolved["execution_timeframe"])
        strategy = data_source.get("strategy")
        if strategy is None:
            raise RuntimeContractError(
                code="PC-CFG-001",
                stage="runtime",
                path="$.data_source.strategy",
                message="data_source.strategy is required",
            )
        bars_by_timeframe = data_source.get("bars_by_timeframe")
        if not isinstance(bars_by_timeframe, dict):
            raise RuntimeContractError(
                code="PC-CFG-001",
                stage="runtime",
                path="$.data_source.bars_by_timeframe",
                message="data_source.bars_by_timeframe is required and must be an object",
            )
        bars_exec = bars_by_timeframe.get(execution_tf)
        if not isinstance(bars_exec, pd.DataFrame):
            raise RuntimeContractError(
                code="PC-TFM-001",
                stage="runtime",
                path=f"$.data_source.bars_by_timeframe.{execution_tf}",
                message="execution timeframe bars must be provided as DataFrame",
            )
        if bars_exec.empty:
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="runtime",
                path=f"$.data_source.bars_by_timeframe.{execution_tf}",
                message="execution timeframe bars cannot be empty",
            )

        strategy_inputs = data_source.get("strategy_inputs")
        if strategy_inputs is None:
            exec_plan = list(copy.deepcopy(loaded.resolved["indicator_plan_by_tf"].get(execution_tf, [])))
            model_df = self.feature_pipeline.build_model_df(
                bars_df=bars_exec.copy(deep=True),
                indicator_plan=exec_plan,
            )
            strategy_inputs = {"features": model_df}
        if not isinstance(strategy_inputs, dict):
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="runtime",
                path="$.data_source.strategy_inputs",
                message="strategy_inputs must be an object when provided",
            )
        strategy_params = data_source.get("strategy_params") or {}
        if not isinstance(strategy_params, dict):
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="runtime",
                path="$.data_source.strategy_params",
                message="strategy_params must be an object when provided",
            )

        as_of_time = pd.to_datetime(bars_exec["timestamp"], utc=True, errors="coerce").dropna()
        if as_of_time.empty:
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="runtime",
                path=f"$.data_source.bars_by_timeframe.{execution_tf}.timestamp",
                message="bars timestamp is empty or invalid",
            )
        universe_values = tuple(sorted(bars_exec["symbol"].astype(str).str.upper().dropna().unique().tolist()))
        if not universe_values:
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="runtime",
                path=f"$.data_source.bars_by_timeframe.{execution_tf}.symbol",
                message="bars symbol cannot be empty",
            )
        context = StrategyContext(
            as_of_time=as_of_time.iloc[-1].to_pydatetime(),
            universe=universe_values,
            inputs=strategy_inputs,
            params=strategy_params,
            meta={"runtime_mode": "backtest", "trial_id": trial_id},
        )
        action_result = strategy.generate_actions(context)
        action_result.validate_schema()

        backtest_config = data_source.get("backtest_config")
        if backtest_config is None:
            backtest_config = EventDrivenBacktestConfig(
                symbol=str(universe_values[0]),
                interval_ms=self._timeframe_to_ms(execution_tf),
                execution_lag_bars=1,
            )
        if not isinstance(backtest_config, EventDrivenBacktestConfig):
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="runtime",
                path="$.data_source.backtest_config",
                message="backtest_config must be EventDrivenBacktestConfig when provided",
            )

        backtest_result = run_event_driven_backtest(
            actions=action_result.actions,
            price_frame=bars_exec,
            config=backtest_config,
        )
        resampled_frames = {
            str(tf): frame
            for tf, frame in bars_by_timeframe.items()
            if str(tf) != execution_tf and isinstance(frame, pd.DataFrame)
        }
        output_result = EventDrivenBacktestResult(
            trades=backtest_result.trades,
            equity_curve=backtest_result.equity_curve,
            summary=backtest_result.summary,
            diagnostics=backtest_result.diagnostics,
            price_input_snapshot=bars_exec.copy(deep=True),
            action_input_snapshot=backtest_result.action_input_snapshot.copy(deep=True),
        )
        return {
            "backtest_config": backtest_config,
            "resampled_frames": resampled_frames,
            "output_result": output_result,
            "decision_trace": action_result.decision_trace.copy(deep=True),
        }

    def _derive_run_outcome(
        self,
        *,
        succeeded_trial_ids: list[str],
        failed_trial_ids: list[str],
        skipped_trial_ids: list[str],
    ) -> tuple[str, int]:
        if succeeded_trial_ids and (failed_trial_ids or skipped_trial_ids):
            return "PARTIAL_SUCCESS", 2
        if succeeded_trial_ids:
            return "SUCCESS", 0
        return "FAILED", 1

    def _apply_warn_policy_override(self, *, loaded: LoadedRuntimeConfig, data_source: dict[str, Any]) -> LoadedRuntimeConfig:
        override = data_source.get("warn_policy")
        if override is None:
            return loaded
        if not isinstance(override, str) or override not in _WARN_POLICY_ALLOWED:
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="runtime",
                path="$.warn_policy",
                message=f"warn_policy override must be one of: {','.join(_WARN_POLICY_ALLOWED)}",
            )
        current = str(loaded.resolved.get("warn_policy", "record_only"))
        if current == override:
            return loaded
        resolved = copy.deepcopy(loaded.resolved)
        resolved["warn_policy"] = override
        return LoadedRuntimeConfig(
            raw=copy.deepcopy(loaded.raw),
            resolved=resolved,
        )

    def _resolve_code_version(self, *, data_source: dict[str, Any]) -> str:
        override = data_source.get("code_version")
        if isinstance(override, str) and override.strip():
            code_version = override.strip()
            if not _CODE_VERSION_PATTERN.fullmatch(code_version):
                raise RuntimeContractError(
                    code="PC-CFG-003",
                    stage="runtime",
                    path="$.data_source.code_version",
                    message="code_version must match git:<40hex>[+dirty]",
                )
            return code_version

        repo_root = Path.cwd()
        try:
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            dirty_flag = subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=repo_root,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            suffix = "+dirty" if dirty_flag else ""
            code_version = f"git:{head}{suffix}"
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="runtime",
                path="$.code_version",
                message="unable to resolve code_version from git; provide data_source.code_version",
            ) from exc

        if not _CODE_VERSION_PATTERN.fullmatch(code_version):
            raise RuntimeContractError(
                code="PC-CFG-003",
                stage="runtime",
                path="$.code_version",
                message=f"resolved code_version is invalid: {code_version}",
            )
        return code_version

    def _build_performance_log(
        self,
        *,
        started_at: float,
        status: str,
        total_trials: int,
        bars_count: int,
    ) -> dict[str, Any]:
        elapsed_ms = int(round((time.perf_counter() - started_at) * 1000.0))
        return {
            "elapsed_ms": max(0, elapsed_ms),
            "peak_rss_mb": self._peak_rss_mb(),
            "trials_count": int(total_trials),
            "bars_count": int(max(0, bars_count)),
            "status": str(status),
        }

    def _peak_rss_mb(self) -> float:
        try:
            rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        except Exception:  # pragma: no cover - platform dependent
            return 0.0
        # Linux reports KB, macOS reports bytes.
        if rss > 10_000_000:
            return round(rss / (1024.0 * 1024.0), 2)
        return round(rss / 1024.0, 2)

    def _write_runtime_error(self, *, run_root: Path, error: RuntimeContractError) -> None:
        path = run_root / "runtime_error.json"
        path.write_text(json.dumps(error.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _hash_payload(self, payload: Any) -> str:
        return sha256_hex(payload)

    def _timeframe_to_ms(self, timeframe: str) -> int:
        key = str(timeframe).strip().lower()
        if key in _TIMEFRAME_MS:
            return int(_TIMEFRAME_MS[key])
        raise RuntimeContractError(
            code="PC-CFG-003",
            stage="runtime",
            path="$.execution_timeframe",
            message=f"unsupported execution timeframe: {timeframe}",
        )


__all__ = ["RuntimeCore", "RuntimeRunResult"]
