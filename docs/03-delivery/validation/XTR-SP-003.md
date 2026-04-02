# Validation Plan (XTR-SP-003)

## Planned Validation
- [x] `profile_feature_pipeline_single_tf_positive`：单周期 profile 输入构建成功且不影响旧接口。
- [x] `profile_feature_pipeline_multi_tf_positive`：多周期对齐成功，验证“仅已收盘可见”。
- [x] `profile_feature_pipeline_staleness_positive`：staleness 超限后特征置空。
- [x] `profile_feature_pipeline_missing_tf_negative`：缺失必要 timeframe 触发 fail-fast。
- [x] `profile_feature_pipeline_unresolved_feature_ref_negative`：无法映射 feature_ref 触发 fail-fast。
- [x] `unit_tests_for_feature_pipeline_profile_mode`：新增/更新单测并通过。

## Execution Log
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategies/test_feature_engine.py`
  - 首轮结果：`3 failed, 15 passed`
  - 失败要点：`build_profile_model_df` 中 `feature_ref -> physical_col` 映射错误（单输出指标被错误映射为 `*_value` 列）。
- 2026-04-02：修复 `src/xtrader/strategies/feature_engine/pipeline.py`
  - 修复 1：`decision_frame[list(_REQUIRED_INPUT_COLUMNS)]`（避免 tuple 取列 KeyError）。
  - 修复 2：`_resolve_physical_col` 对单输出指标固定映射 `output_key=value -> indicator_prefix`，多输出指标仍按 suffix 映射。
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategies/test_feature_engine.py`
  - 结果：`18 passed`
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
  - 结果：`12 passed`

## Evidence
- 代码修改：
  - `src/xtrader/strategies/feature_engine/pipeline.py`
  - `tests/unit/strategies/test_feature_engine.py`
- 通过用例覆盖：
  - `test_profile_feature_pipeline_single_tf_positive`
  - `test_profile_feature_pipeline_multi_tf_alignment_uses_last_closed`
  - `test_profile_feature_pipeline_staleness_masks_expired_values`
  - `test_profile_feature_pipeline_missing_timeframe_bars_rejected`
  - `test_profile_feature_pipeline_unresolved_feature_ref_rejected`
