from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import pytest

from xtrader.strategies.feature_engine.indicators.registry import build_default_indicator_registry
from xtrader.strategies.feature_engine.pipeline import FeaturePipeline


def _bars(rows: int = 120) -> pd.DataFrame:
    ts = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=rows, freq="5min", tz="UTC")
    close = pd.Series([100.0 + (i * 0.5) for i in range(rows)], dtype="float64")
    frame = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["BTCUSDT"] * rows,
            "open": close - 0.2,
            "high": close + 0.6,
            "low": close - 0.8,
            "close": close,
            "volume": [1000.0 + (i % 7) * 10.0 for i in range(rows)],
        }
    )
    return frame


def _bars_1h(rows: int = 6) -> pd.DataFrame:
    ts = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=rows, freq="1h", tz="UTC")
    close = pd.Series([200.0 + (i * 10.0) for i in range(rows)], dtype="float64")
    frame = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["BTCUSDT"] * rows,
            "open": close - 0.2,
            "high": close + 0.6,
            "low": close - 0.8,
            "close": close,
            "volume": [1500.0 + (i % 5) * 20.0 for i in range(rows)],
        }
    )
    return frame


def _bars_golden(rows: int = 240) -> pd.DataFrame:
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


def test_registry_has_all_v1_families() -> None:
    registry = build_default_indicator_registry()
    assert registry.families() == (
        "atr",
        "atr_pct_rank",
        "bollinger",
        "dmi",
        "ema",
        "frama",
        "ht_trendline",
        "kama",
        "kd",
        "ma",
        "macd",
        "macd_state",
        "mama",
        "mfi",
        "rsi",
        "stddev",
        "support_proximity",
        "trix",
        "volume_ma",
        "volume_variation",
        "wr",
    )


def test_atr_pct_rank_indicator_outputs_expected_range_and_warmup() -> None:
    bars = _bars(rows=520)
    pipeline = FeaturePipeline()
    plan = [
        {"instance_id": "atrpr_252", "family": "atr_pct_rank", "params": {"window": 252}},
    ]

    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)

    col = "atr_pct_rank_252"
    assert col in features.columns

    first_valid = features[col].first_valid_index()
    assert first_valid == 264

    valid = features[col].dropna()
    assert not valid.empty
    assert float(valid.min()) >= 0.0
    assert float(valid.max()) <= 1.0


def test_pipeline_build_model_df_generates_columns_and_preserves_timestamp() -> None:
    bars = _bars()
    pipeline = FeaturePipeline()
    plan = [
        {"instance_id": "ema_12", "family": "ema", "params": {"period": 12}},
        {"instance_id": "ema_26", "family": "ema", "params": {"period": 26}},
        {"instance_id": "macd_1", "family": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}},
        {"instance_id": "bb_1", "family": "bollinger", "params": {"period": 20, "std": 2.3}},
        {"instance_id": "kd_1", "family": "kd", "params": {"k_period": 9, "k_smooth": 3, "d_period": 3}},
        {"instance_id": "dmi_1", "family": "dmi", "params": {"di_period": 14, "adx_period": 14}},
    ]

    model = pipeline.build_model_df(bars_df=bars, indicator_plan=plan)

    expected_cols = {
        "ema_12",
        "ema_26",
        "macd_12_26_9_line",
        "macd_12_26_9_signal",
        "macd_12_26_9_hist",
        "bollinger_20_2.30_mid",
        "bollinger_20_2.30_up",
        "bollinger_20_2.30_low",
        "kd_9_3_3_k",
        "kd_9_3_3_d",
        "kd_9_3_3_j",
        "dmi_14_14_plus_di",
        "dmi_14_14_minus_di",
        "dmi_14_14_adx",
    }
    assert expected_cols.issubset(set(model.columns))
    assert model["timestamp"].equals(bars["timestamp"])
    assert len(model.index) == len(bars.index)


def test_pipeline_duplicate_instance_id_rejected() -> None:
    bars = _bars()
    pipeline = FeaturePipeline()
    plan = [
        {"instance_id": "dup", "family": "ema", "params": {"period": 12}},
        {"instance_id": "dup", "family": "ema", "params": {"period": 26}},
    ]
    with pytest.raises(ValueError, match=r"XTR018::PLAN_DUPLICATE_INSTANCE_ID::"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_pipeline_duplicate_family_params_rejected() -> None:
    bars = _bars()
    pipeline = FeaturePipeline()
    plan = [
        {"instance_id": "ema_a", "family": "ema", "params": {"period": 12}},
        {"instance_id": "ema_b", "family": "ema", "params": {"period": 12}},
    ]
    with pytest.raises(ValueError, match=r"XTR018::PLAN_DUPLICATE_FAMILY_PARAMS::"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_pipeline_float_param_2_0_collides_with_int_2() -> None:
    bars = _bars()
    pipeline = FeaturePipeline()
    plan = [
        {"instance_id": "bb_2_0", "family": "bollinger", "params": {"period": 20, "std": 2.0}},
        {"instance_id": "bb_2", "family": "bollinger", "params": {"period": 20, "std": 2}},
    ]
    with pytest.raises(ValueError, match=r"XTR018::PLAN_DUPLICATE_FAMILY_PARAMS::"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_pipeline_plan_missing_fields_rejected() -> None:
    bars = _bars()
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "bad", "family": "ema"}]
    with pytest.raises(ValueError, match=r"XTR018::PLAN_MISSING_FIELD::"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_pipeline_unknown_family_rejected() -> None:
    bars = _bars()
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "x", "family": "unknown", "params": {}}]
    with pytest.raises(ValueError, match=r"XTR018::PLAN_UNKNOWN_FAMILY::"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_pipeline_timestamp_duplicate_rejected() -> None:
    bars = _bars()
    bars.loc[1, "timestamp"] = bars.loc[0, "timestamp"]
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "ema_12", "family": "ema", "params": {"period": 12}}]
    with pytest.raises(ValueError, match=r"XTR018::INPUT_TIMESTAMP_DUPLICATE::"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_pipeline_timestamp_invalid_type_rejected() -> None:
    bars = _bars()
    bars["timestamp"] = bars["timestamp"].astype(str)
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "ema_12", "family": "ema", "params": {"period": 12}}]
    with pytest.raises(ValueError, match=r"XTR018::INPUT_TIMESTAMP_INVALID::"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_indicator_compute_returns_dataframe_for_all_families() -> None:
    bars = _bars()
    registry = build_default_indicator_registry()
    for family in registry.families():
        indicator = registry.get(family)
        if family == "macd_state":
            macd = registry.get("macd")
            source_resolved = macd.resolve_params({"fast": 12, "slow": 26, "signal": 9})
            source_cols = macd.build_output_columns(source_resolved, suffixes=("line", "signal", "hist"))
            source_frame = macd.compute(bars, source_resolved)
            input_frame = pd.concat([bars, source_frame], axis=1)
            result = indicator.compute(
                input_frame,
                {
                    "source_instance_id": "macd_main",
                    "__source_line_col": source_cols[0],
                    "__source_signal_col": source_cols[1],
                    "__source_hist_col": source_cols[2],
                },
            )
        else:
            result = indicator.compute(bars, {})
        assert isinstance(result, pd.DataFrame)
        assert len(result.index) == len(bars.index)


def test_non_macd_suffix_dictionary_columns() -> None:
    bars = _bars()
    pipeline = FeaturePipeline()
    plan = [
        {"instance_id": "bb", "family": "bollinger", "params": {"period": 20, "std": 2.3}},
        {"instance_id": "kd", "family": "kd", "params": {"k_period": 9, "k_smooth": 3, "d_period": 3}},
        {"instance_id": "dmi", "family": "dmi", "params": {"di_period": 14, "adx_period": 14}},
    ]

    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)

    assert {"bollinger_20_2.30_mid", "bollinger_20_2.30_up", "bollinger_20_2.30_low"}.issubset(features.columns)
    assert {"kd_9_3_3_k", "kd_9_3_3_d", "kd_9_3_3_j"}.issubset(features.columns)
    assert {"dmi_14_14_plus_di", "dmi_14_14_minus_di", "dmi_14_14_adx"}.issubset(features.columns)


def test_macd_state_indicator_outputs_expected_columns_and_flags() -> None:
    bars = _bars(rows=260)
    pipeline = FeaturePipeline()
    plan = [
        {
            "instance_id": "macd_main",
            "family": "macd",
            "params": {
                "fast": 12,
                "slow": 26,
                "signal": 9,
            },
        },
        {
            "instance_id": "macd_state_main",
            "family": "macd_state",
            "params": {
                "source_instance_id": "macd_main",
                "near_gap_pct": 0.01,
                "near_gap_abs": 0.0,
                "slope_min": 0.0,
                "narrow_bars": 2,
            },
        }
    ]

    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)

    expected_cols = {
        "macd_state_macd_main_0.01_0_0_2_state_code_num",
        "macd_state_macd_main_0.01_0_0_2_near_cross_num",
        "macd_state_macd_main_0.01_0_0_2_near_golden_flag",
        "macd_state_macd_main_0.01_0_0_2_near_dead_flag",
        "macd_state_macd_main_0.01_0_0_2_reject_long_flag",
        "macd_state_macd_main_0.01_0_0_2_reject_short_flag",
        "macd_state_macd_main_0.01_0_0_2_gap",
        "macd_state_macd_main_0.01_0_0_2_gap_slope",
        "macd_state_macd_main_0.01_0_0_2_gap_pct",
        "macd_state_macd_main_0.01_0_0_2_green_narrow_2_flag",
        "macd_state_macd_main_0.01_0_0_2_red_narrow_2_flag",
    }
    assert expected_cols.issubset(set(features.columns))
    near_cross = features["macd_state_macd_main_0.01_0_0_2_near_cross_num"].dropna()
    assert not near_cross.empty
    assert set(near_cross.unique()).issubset({-1.0, 0.0, 1.0})
    assert float(near_cross.abs().sum()) >= 1.0


def test_kama_indicator_outputs_column_and_warmup() -> None:
    bars = _bars(rows=240)
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "kama_fast", "family": "kama", "params": {"er_period": 10, "fast_period": 2, "slow_period": 30}}]

    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)
    col = "kama_10_2_30"
    assert col in features.columns
    first_valid = features[col].first_valid_index()
    assert first_valid is not None and first_valid >= 10
    assert features[col].dropna().shape[0] >= 100


def test_trix_indicator_outputs_column_and_finite_values() -> None:
    bars = _bars(rows=320)
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "trix_15", "family": "trix", "params": {"period": 15}}]

    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)
    col = "trix_15"
    assert col in features.columns
    valid = features[col].dropna()
    assert not valid.empty
    assert valid.map(lambda x: pd.notna(x)).all()


def test_mfi_indicator_outputs_column_and_range() -> None:
    bars = _bars(rows=260)
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "mfi_14", "family": "mfi", "params": {"period": 14}}]

    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)
    col = "mfi_14"
    assert col in features.columns
    valid = features[col].dropna()
    assert not valid.empty
    assert float(valid.min()) >= 0.0
    assert float(valid.max()) <= 100.0


def test_mama_indicator_outputs_dual_columns() -> None:
    bars = _bars(rows=260)
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "mama_main", "family": "mama", "params": {"fast_limit": 0.5, "slow_limit": 0.05}}]

    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)
    col_mama = "mama_0.50_0.05_mama"
    col_fama = "mama_0.50_0.05_fama"
    assert col_mama in features.columns
    assert col_fama in features.columns
    assert not features[col_mama].dropna().empty
    assert not features[col_fama].dropna().empty


def test_ht_trendline_indicator_outputs_column() -> None:
    bars = _bars(rows=200)
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "htl", "family": "ht_trendline", "params": {}}]

    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)
    col = "ht_trendline"
    assert col in features.columns
    assert not features[col].dropna().empty


def test_frama_indicator_outputs_column_and_warmup() -> None:
    bars = _bars(rows=260)
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "frama_16", "family": "frama", "params": {"window": 16}}]

    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)
    col = "frama_16_0.01_1"
    assert col in features.columns
    first_valid = features[col].first_valid_index()
    assert first_valid is not None and first_valid >= 15
    assert not features[col].dropna().empty


def test_frama_rejects_odd_window() -> None:
    bars = _bars(rows=120)
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "frama_bad", "family": "frama", "params": {"window": 15}}]
    with pytest.raises(ValueError, match=r"XTR018::PARAM_OUT_OF_RANGE::frama.window must be even"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_profile_feature_pipeline_resolves_macd_state_suffix_ref() -> None:
    bars_5m = _bars(rows=180)
    pipeline = FeaturePipeline()
    result = pipeline.build_profile_model_df(
        bars_by_timeframe={"5m": bars_5m},
        required_indicator_plan_by_tf={
            "5m": [
                {"instance_id": "macd_main", "family": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}},
                {
                    "instance_id": "ms",
                    "family": "macd_state",
                    "params": {"source_instance_id": "macd_main"},
                }
            ]
        },
        required_feature_refs=["f:5m:ms:near_golden_flag", "f:5m:ms:state_code_num"],
        decision_timeframe="5m",
        alignment_policy={"mode": "ffill_last_closed", "max_staleness_bars_by_tf": {}},
    )
    assert "f:5m:ms:near_golden_flag" in result.columns
    assert "f:5m:ms:state_code_num" in result.columns


def test_macd_state_without_source_instance_rejected() -> None:
    bars = _bars(rows=120)
    pipeline = FeaturePipeline()
    plan = [{"instance_id": "ms", "family": "macd_state", "params": {"source_instance_id": "missing"}}]
    with pytest.raises(ValueError, match=r"XTR018::PLAN_SOURCE_INSTANCE_NOT_FOUND::"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_macd_state_source_must_be_computed_first() -> None:
    bars = _bars(rows=120)
    pipeline = FeaturePipeline()
    plan = [
        {"instance_id": "ms", "family": "macd_state", "params": {"source_instance_id": "macd_main"}},
        {"instance_id": "macd_main", "family": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}},
    ]
    with pytest.raises(ValueError, match=r"XTR018::PLAN_SOURCE_ORDER_INVALID::"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_support_proximity_outputs_expected_columns_and_codes() -> None:
    bars = _bars(rows=260)
    pipeline = FeaturePipeline()
    plan = [
        {
            "instance_id": "sp_main",
            "family": "support_proximity",
            "params": {
                "lookback": 20,
                "round_step": 100.0,
                "strong_pct": 0.3,
                "medium_pct": 0.8,
                "weak_pct": 1.5,
            },
        }
    ]
    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)
    expected_cols = {
        "support_proximity_20_100_0.30_0.80_1.50_nearest_support_level",
        "support_proximity_20_100_0.30_0.80_1.50_nearest_resistance_level",
        "support_proximity_20_100_0.30_0.80_1.50_support_distance_pct",
        "support_proximity_20_100_0.30_0.80_1.50_resistance_distance_pct",
        "support_proximity_20_100_0.30_0.80_1.50_support_strength_code",
        "support_proximity_20_100_0.30_0.80_1.50_resistance_strength_code",
    }
    assert expected_cols.issubset(set(features.columns))
    support_code = features["support_proximity_20_100_0.30_0.80_1.50_support_strength_code"].dropna()
    assert not support_code.empty
    assert set(support_code.unique()).issubset({0.0, 1.0, 2.0, 3.0})


def test_profile_feature_pipeline_resolves_support_proximity_suffix_ref() -> None:
    bars_5m = _bars(rows=220)
    pipeline = FeaturePipeline()
    result = pipeline.build_profile_model_df(
        bars_by_timeframe={"5m": bars_5m},
        required_indicator_plan_by_tf={
            "5m": [
                {
                    "instance_id": "sp",
                    "family": "support_proximity",
                    "params": {"lookback": 20, "round_step": 100.0},
                }
            ]
        },
        required_feature_refs=["f:5m:sp:support_strength_code", "f:5m:sp:resistance_distance_pct"],
        decision_timeframe="5m",
        alignment_policy={"mode": "ffill_last_closed", "max_staleness_bars_by_tf": {}},
    )
    assert "f:5m:sp:support_strength_code" in result.columns
    assert "f:5m:sp:resistance_distance_pct" in result.columns


def test_profile_feature_pipeline_resolves_mama_suffix_ref() -> None:
    bars_5m = _bars(rows=220)
    pipeline = FeaturePipeline()
    result = pipeline.build_profile_model_df(
        bars_by_timeframe={"5m": bars_5m},
        required_indicator_plan_by_tf={
            "5m": [
                {
                    "instance_id": "mama_main",
                    "family": "mama",
                    "params": {"fast_limit": 0.5, "slow_limit": 0.05},
                }
            ]
        },
        required_feature_refs=["f:5m:mama_main:mama", "f:5m:mama_main:fama"],
        decision_timeframe="5m",
        alignment_policy={"mode": "ffill_last_closed", "max_staleness_bars_by_tf": {}},
    )
    assert "f:5m:mama_main:mama" in result.columns
    assert "f:5m:mama_main:fama" in result.columns


def test_support_proximity_invalid_threshold_order_rejected() -> None:
    bars = _bars(rows=120)
    pipeline = FeaturePipeline()
    plan = [
        {
            "instance_id": "sp_bad",
            "family": "support_proximity",
            "params": {
                "lookback": 20,
                "round_step": 100.0,
                "strong_pct": 1.2,
                "medium_pct": 0.8,
                "weak_pct": 1.5,
            },
        }
    ]
    with pytest.raises(ValueError, match=r"XTR018::PARAM_OUT_OF_RANGE::support_proximity threshold order requires"):
        pipeline.compute_features(bars_df=bars, indicator_plan=plan)


def test_feature_engine_golden_snapshot_alignment() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "feature_engine_golden_v1.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    bars = _bars_golden()
    pipeline = FeaturePipeline()
    plan = [
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
    features = pipeline.compute_features(bars_df=bars, indicator_plan=plan)

    assert list(features.columns) == payload["columns"]
    for col, expected_idx in payload["first_valid_index"].items():
        actual = features[col].first_valid_index()
        if expected_idx is None:
            assert actual is None
        else:
            assert actual == int(expected_idx)

    tail_size = int(payload["tail_size"])
    observed_tail = features.tail(tail_size).reset_index(drop=True)
    for col, expected_values in payload["tail_values"].items():
        observed_values = observed_tail[col].tolist()
        assert len(observed_values) == len(expected_values)
        for observed, expected in zip(observed_values, expected_values):
            if expected is None:
                assert pd.isna(observed)
            else:
                assert observed == pytest.approx(float(expected), abs=1e-10, rel=1e-10)


def test_profile_feature_pipeline_single_tf_positive() -> None:
    bars_5m = _bars(rows=40)
    pipeline = FeaturePipeline()
    result = pipeline.build_profile_model_df(
        bars_by_timeframe={"5m": bars_5m},
        required_indicator_plan_by_tf={
            "5m": [{"instance_id": "ema_12", "family": "ema", "params": {"period": 12}}]
        },
        required_feature_refs=["f:5m:ema_12:value"],
        decision_timeframe="5m",
        alignment_policy={"mode": "ffill_last_closed", "max_staleness_bars_by_tf": {}},
    )
    assert len(result.index) == len(bars_5m.index)
    assert "f:5m:ema_12:value" in result.columns
    assert result["timestamp"].equals(bars_5m["timestamp"])


def test_profile_feature_pipeline_can_include_decision_tf_feature_superset() -> None:
    bars_5m = _bars(rows=80)
    pipeline = FeaturePipeline()
    result = pipeline.build_profile_model_df(
        bars_by_timeframe={"5m": bars_5m},
        required_indicator_plan_by_tf={
            "5m": [
                {"instance_id": "ema_12", "family": "ema", "params": {"period": 12}},
                {"instance_id": "rsi_14", "family": "rsi", "params": {"period": 14}},
            ]
        },
        required_feature_refs=["f:5m:ema_12:value"],
        decision_timeframe="5m",
        alignment_policy={"mode": "ffill_last_closed", "max_staleness_bars_by_tf": {}},
        include_decision_tf_features=True,
    )
    assert "f:5m:ema_12:value" in result.columns
    assert "ema_12" in result.columns
    assert "rsi_14" in result.columns


def test_profile_feature_pipeline_multi_tf_alignment_uses_last_closed() -> None:
    bars_5m = _bars(rows=36)  # 3h
    bars_1h = _bars_1h(rows=4)  # 00:00, 01:00, 02:00, 03:00
    pipeline = FeaturePipeline()
    result = pipeline.build_profile_model_df(
        bars_by_timeframe={"5m": bars_5m, "1h": bars_1h},
        required_indicator_plan_by_tf={
            "5m": [{"instance_id": "ema_1", "family": "ema", "params": {"period": 1}}],
            "1h": [{"instance_id": "ema_1", "family": "ema", "params": {"period": 1}}],
        },
        required_feature_refs=["f:5m:ema_1:value", "f:1h:ema_1:value"],
        decision_timeframe="5m",
        alignment_policy={"mode": "ffill_last_closed", "max_staleness_bars_by_tf": {"1h": 24}},
    )
    # 1h 00:00 bar becomes visible starting at 01:00 (index 12 on 5m axis).
    assert pd.isna(result.loc[11, "f:1h:ema_1:value"])
    assert result.loc[12, "f:1h:ema_1:value"] == pytest.approx(200.0)
    # 1h 01:00 bar becomes visible starting at 02:00 (index 24).
    assert result.loc[24, "f:1h:ema_1:value"] == pytest.approx(210.0)


def test_profile_feature_pipeline_staleness_masks_expired_values() -> None:
    bars_5m = _bars(rows=30)
    bars_1h = _bars_1h(rows=1)  # only 00:00 bar
    pipeline = FeaturePipeline()
    result = pipeline.build_profile_model_df(
        bars_by_timeframe={"5m": bars_5m, "1h": bars_1h},
        required_indicator_plan_by_tf={
            "5m": [{"instance_id": "ema_1", "family": "ema", "params": {"period": 1}}],
            "1h": [{"instance_id": "ema_1", "family": "ema", "params": {"period": 1}}],
        },
        required_feature_refs=["f:1h:ema_1:value"],
        decision_timeframe="5m",
        alignment_policy={"mode": "ffill_last_closed", "max_staleness_bars_by_tf": {"1h": 2}},
    )
    assert result.loc[12, "f:1h:ema_1:value"] == pytest.approx(200.0)
    assert result.loc[14, "f:1h:ema_1:value"] == pytest.approx(200.0)
    assert pd.isna(result.loc[15, "f:1h:ema_1:value"])


def test_profile_feature_pipeline_missing_timeframe_bars_rejected() -> None:
    pipeline = FeaturePipeline()
    with pytest.raises(ValueError, match=r"XTR018::PROFILE_MISSING_TIMEFRAME_BARS::1h"):
        pipeline.build_profile_model_df(
            bars_by_timeframe={"5m": _bars(rows=30)},
            required_indicator_plan_by_tf={
                "5m": [{"instance_id": "ema_1", "family": "ema", "params": {"period": 1}}],
                "1h": [{"instance_id": "ema_1", "family": "ema", "params": {"period": 1}}],
            },
            required_feature_refs=["f:1h:ema_1:value"],
            decision_timeframe="5m",
            alignment_policy={"mode": "ffill_last_closed", "max_staleness_bars_by_tf": {"1h": 8}},
        )


def test_profile_feature_pipeline_unresolved_feature_ref_rejected() -> None:
    pipeline = FeaturePipeline()
    with pytest.raises(ValueError, match=r"XTR018::PROFILE_UNRESOLVED_FEATURE_REF::"):
        pipeline.build_profile_model_df(
            bars_by_timeframe={"5m": _bars(rows=30)},
            required_indicator_plan_by_tf={
                "5m": [{"instance_id": "ema_1", "family": "ema", "params": {"period": 1}}]
            },
            required_feature_refs=["f:5m:ema_1:foo"],
            decision_timeframe="5m",
            alignment_policy={"mode": "ffill_last_closed", "max_staleness_bars_by_tf": {}},
        )
