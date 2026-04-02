"""Refresh feature engine golden fixture for XTR-018 tests."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xtrader.strategies.feature_engine.pipeline import FeaturePipeline


def _bars_golden(rows: int) -> pd.DataFrame:
    ts = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=rows, freq="5min", tz="UTC")
    close = pd.Series([100.0 + (i * 0.37) + ((i % 11) - 5) * 0.08 for i in range(rows)], dtype="float64")
    frame = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["BTCUSDT"] * rows,
            "open": close - 0.15,
            "high": close + 0.42,
            "low": close - 0.53,
            "close": close,
            "volume": [900.0 + ((i * 17) % 130) for i in range(rows)],
        }
    )
    return frame


def _indicator_plan() -> list[dict[str, Any]]:
    return [
        {"instance_id": "ma_20", "family": "ma", "params": {"period": 20}},
        {"instance_id": "ema_12", "family": "ema", "params": {"period": 12}},
        {"instance_id": "ema_26", "family": "ema", "params": {"period": 26}},
        {"instance_id": "macd_1", "family": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}},
        {"instance_id": "rsi_14", "family": "rsi", "params": {"period": 14}},
        {"instance_id": "kd_9_3_3", "family": "kd", "params": {"k_period": 9, "k_smooth": 3, "d_period": 3}},
        {"instance_id": "wr_14", "family": "wr", "params": {"period": 14}},
        {"instance_id": "atr_14", "family": "atr", "params": {"period": 14}},
        {"instance_id": "bb_20_2_3", "family": "bollinger", "params": {"period": 20, "std": 2.3}},
        {"instance_id": "std_20", "family": "stddev", "params": {"period": 20}},
        {"instance_id": "dmi_14_14", "family": "dmi", "params": {"di_period": 14, "adx_period": 14}},
        {"instance_id": "volma_20", "family": "volume_ma", "params": {"period": 20}},
        {"instance_id": "volvar_20", "family": "volume_variation", "params": {"period": 20}},
    ]


def _to_json_number_or_null(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _build_payload(features: pd.DataFrame, tail_size: int) -> dict[str, Any]:
    columns = list(features.columns)
    first_valid_index: dict[str, int | None] = {}
    for col in columns:
        idx = features[col].first_valid_index()
        first_valid_index[col] = None if idx is None else int(idx)

    observed_tail = features.tail(tail_size).reset_index(drop=True)
    tail_values: dict[str, list[float | None]] = {}
    for col in columns:
        values = observed_tail[col].tolist()
        tail_values[col] = [_to_json_number_or_null(v) for v in values]

    return {
        "schema_version": 1,
        "tail_size": int(tail_size),
        "columns": columns,
        "first_valid_index": first_valid_index,
        "tail_values": tail_values,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh tests/unit/strategies feature engine golden fixture.")
    parser.add_argument(
        "--fixture-path",
        default=str(REPO_ROOT / "tests/unit/strategies/fixtures/feature_engine_golden_v1.json"),
        help="Output fixture path.",
    )
    parser.add_argument("--rows", type=int, default=240, help="Synthetic input bar count.")
    parser.add_argument("--tail-size", type=int, default=30, help="Tail window size saved in snapshot.")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing fixture.")
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.rows <= 0:
        raise ValueError("--rows must be positive")
    if args.tail_size <= 0:
        raise ValueError("--tail-size must be positive")

    bars = _bars_golden(rows=int(args.rows))
    pipeline = FeaturePipeline()
    features = pipeline.compute_features(bars_df=bars, indicator_plan=_indicator_plan())
    payload = _build_payload(features=features, tail_size=int(args.tail_size))

    fixture_path = Path(args.fixture_path).expanduser().resolve()
    if args.dry_run:
        print(
            f"[dry-run] fixture={fixture_path} columns={len(payload['columns'])} "
            f"rows={len(features.index)} tail_size={payload['tail_size']}"
        )
        return 0

    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"refreshed fixture: {fixture_path}\n"
        f"columns={len(payload['columns'])}, rows={len(features.index)}, tail_size={payload['tail_size']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
