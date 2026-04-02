# Validation Plan (XTR-SP-008)

> 历史说明（2026-04-02）：本记录对应当时“legacy 保留”阶段性结果；`XTR-SP-011` 已执行更高优先级决策，完成 Threshold 全量下线并替换原兼容路径。

## Planned Validation
- [x] `main_entry_exports_profile_only_positive`：验证主入口仅暴露 `ProfileActionStrategy`。
- [x] `legacy_threshold_import_positive`：验证 `xtrader.strategies.intraday` 仍可导入 `ThresholdIntradayStrategy`。
- [x] `legacy_threshold_behavior_positive`：legacy 阈值策略行为测试仍通过。
- [x] `profile_mainline_regression_positive`：`ProfileActionStrategy` 相关测试回归通过。
- [x] `unit_tests_for_entry_convergence`：导出层与回测相关单测更新并通过。

## Execution Log
- 2026-04-02：执行入口收敛改造（主入口去除 `ThresholdIntradayStrategy` 导出，保留 legacy 兼容路径）
  - 更新文件：
    - `src/xtrader/strategies/__init__.py`
    - `src/xtrader/strategies/builtin.py`
    - `src/xtrader/strategies/builtin_strategies/__init__.py`
  - 保留 legacy：`src/xtrader/strategies/intraday.py`（仍 re-export `ThresholdIntradayStrategy`）。
- 2026-04-02：更新测试导入与断言
  - `tests/unit/strategies/test_builtin.py`：新增“主入口/内建入口不再导出 Threshold”断言。
  - `tests/unit/strategies/test_intraday.py`：改为 legacy 路径导入 Threshold。
  - `tests/unit/backtests/test_event_driven.py`：改为 legacy 路径导入 Threshold。
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategies/test_builtin.py tests/unit/strategies/test_intraday.py tests/unit/strategies/test_profile_action_strategy.py`
  - 结果：`8 passed`
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/backtests/test_event_driven.py tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategy_profiles/test_risk_engine.py tests/unit/strategies/test_feature_engine.py`
  - 结果：`64 passed`
- 2026-04-02：`PYTHONPATH=src python -m py_compile src/xtrader/strategies/__init__.py src/xtrader/strategies/builtin.py src/xtrader/strategies/builtin_strategies/__init__.py tests/unit/strategies/test_builtin.py tests/unit/strategies/test_intraday.py tests/unit/backtests/test_event_driven.py`
  - 结果：通过
- 2026-04-02：`python scripts/task_guard.py check XTR-SP-008`
  - 结果：通过（`✓ Spec & Validation check passed.`）

## Evidence
- 代码修改：
  - `src/xtrader/strategies/__init__.py`
  - `src/xtrader/strategies/builtin.py`
  - `src/xtrader/strategies/builtin_strategies/__init__.py`
  - `tests/unit/strategies/test_builtin.py`
  - `tests/unit/strategies/test_intraday.py`
  - `tests/unit/backtests/test_event_driven.py`
- 兼容路径保留：
  - `src/xtrader/strategies/intraday.py`
- 回归覆盖：
  - `tests/unit/strategies/test_profile_action_strategy.py`
  - `tests/unit/strategy_profiles/test_profile_schema_gate.py`
  - `tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
  - `tests/unit/strategy_profiles/test_regime_scoring_engine.py`
  - `tests/unit/strategy_profiles/test_signal_engine.py`
  - `tests/unit/strategy_profiles/test_risk_engine.py`
  - `tests/unit/strategies/test_feature_engine.py`
