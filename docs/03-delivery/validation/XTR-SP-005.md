# Validation Plan (XTR-SP-005)

## Planned Validation
- [x] `signal_engine_profile_positive`：使用 `v0.3.json` + RegimeScoring 输出验证可生成唯一动作与 reason_code。
- [x] `signal_engine_score_range_boundary_positive`：验证开闭区间边界命中逻辑。
- [x] `signal_engine_state_deny_precedence_positive`：验证 `state_deny` 优先于 `state_allow`。
- [x] `signal_engine_priority_first_match_positive`：重叠区间下按 `priority_rank` first-match。
- [x] `signal_engine_cooldown_symbol_action_positive`：验证冷却窗口内同 `symbol+action` 被抑制。
- [x] `signal_engine_missing_column_negative`：输入缺少 `score_total/state` 时 fail-fast。
- [x] `unit_tests_for_signal_engine`：新增/更新单测并通过。

## Execution Log
- 2026-04-02：新增 `SignalEngine` 运行时实现
  - 文件：`src/xtrader/strategy_profiles/signal_engine.py`
  - 关键逻辑：`score_range` 判定、`state_allow/state_deny` 过滤、`priority_rank` first-match、`cooldown_scope=symbol_action`、`reason_code_map` 绑定。
- 2026-04-02：新增单测 `tests/unit/strategy_profiles/test_signal_engine.py`
  - 覆盖：profile 正例、区间边界、deny 优先、priority first-match、cooldown、生效列缺失 fail-fast、reason 映射缺失 fail-fast。
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_signal_engine.py`
  - 结果：`7 passed`
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
  - 结果：`36 passed`
- 2026-04-02：`PYTHONPATH=src python -m py_compile src/xtrader/strategy_profiles/signal_engine.py tests/unit/strategy_profiles/test_signal_engine.py`
  - 结果：通过
- 2026-04-02：`python scripts/task_guard.py check XTR-SP-005`
  - 结果：通过（`✓ Spec & Validation check passed.`）

## Evidence
- 代码修改：
  - `src/xtrader/strategy_profiles/signal_engine.py`
  - `src/xtrader/strategy_profiles/__init__.py`
  - `tests/unit/strategy_profiles/test_signal_engine.py`
- 关联回归：
  - `tests/unit/strategy_profiles/test_regime_scoring_engine.py`
  - `tests/unit/strategies/test_feature_engine.py`
  - `tests/unit/strategy_profiles/test_profile_schema_gate.py`
  - `tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
