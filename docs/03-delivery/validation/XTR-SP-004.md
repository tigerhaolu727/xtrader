# Validation Plan (XTR-SP-004)

## Planned Validation
- [x] `regime_scoring_engine_profile_positive`：使用 `v0.3.json` + FeaturePipeline 输出，验证评分主链路可运行并输出关键字段。
- [x] `score_fn_registry_runtime_math_positive`：对 5 个 `score_fn` 做固定输入断言，验证方向性与 `[-1,1]` 约束。
- [x] `classifier_first_match_priority_positive`：同一 bar 命中多条 classifier 规则时，验证按 priority first-match。
- [x] `state_weight_zero_sum_positive`：`NO_TRADE_EXTREME` 权重全 0 时，验证 `score_total=0`。
- [x] `missing_feature_ref_negative`：规则引用在 model_df 缺失时 fail-fast。
- [x] `unit_tests_for_regime_scoring_engine`：新增/更新单测并通过。

## Execution Log
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_regime_scoring_engine.py`
  - 首轮结果：`2 failed, 4 passed`
  - 失败要点：`volume_score` 对标量参数 `vol_scale` 使用 `Series.mask` 导致 shape mismatch。
- 2026-04-02：修复 `src/xtrader/strategy_profiles/regime_scoring.py`
  - 修复点：`volume_score` 中 `vol_scale` 为标量时改用标量分支（`<=eps` 时整列置 NaN，否则直接相除）。
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_regime_scoring_engine.py`
  - 结果：`6 passed`
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
  - 结果：`30 passed`
- 2026-04-02：`python scripts/task_guard.py check XTR-SP-004`
  - 结果：通过（`✓ Spec & Validation check passed.`）

## Evidence
- 代码修改：
  - `src/xtrader/strategy_profiles/regime_scoring.py`
  - `src/xtrader/strategy_profiles/__init__.py`
  - `tests/unit/strategy_profiles/test_regime_scoring_engine.py`
- 用例覆盖：
  - profile 评分链路正例（precompile + feature + regime scoring）
  - 5 个内置 `score_fn` 数学行为与范围约束
  - classifier first-match 优先级语义
  - `NO_TRADE_EXTREME` 零权重语义
  - 缺失 feature_ref fail-fast
