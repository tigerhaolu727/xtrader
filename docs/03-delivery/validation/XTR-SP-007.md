# Validation Plan (XTR-SP-007)

## Planned Validation
- [x] `profile_action_strategy_e2e_smoke_positive`：`v0.3.json` 跑通端到端动作输出。
- [x] `profile_action_strategy_schema_positive`：输出满足 `ActionStrategyResult` schema。
- [x] `profile_action_strategy_diagnostics_positive`：diagnostics 包含 `state/score_total/action/reason` 核心字段。
- [x] `profile_action_strategy_invalid_profile_negative`：非法 profile 返回可定位错误信息。
- [x] `unit_tests_for_profile_action_strategy`：新增/更新单测并通过。

## Execution Log
- 2026-04-02：新增 `ProfileActionStrategy` 运行时入口
  - 文件：`src/xtrader/strategies/builtin_strategies/profile_action.py`
  - 链路：`FeaturePipeline -> RegimeScoringEngine -> SignalEngine -> RiskEngine -> ActionStrategyResult`
- 2026-04-02：更新导出入口
  - `src/xtrader/strategies/builtin_strategies/__init__.py`
  - `src/xtrader/strategies/builtin.py`
  - `src/xtrader/strategies/__init__.py`
- 2026-04-02：新增单测
  - `tests/unit/strategies/test_profile_action_strategy.py`
  - `tests/unit/strategies/test_builtin.py`（补 ProfileActionStrategy 导出用例）
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategies/test_profile_action_strategy.py tests/unit/strategies/test_builtin.py`
  - 结果：`5 passed`
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_risk_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategies/test_profile_action_strategy.py tests/unit/strategies/test_builtin.py`
  - 首轮结果：`1 error`
  - 原因：`risk_engine -> strategies.base -> strategies.__init__ -> profile_action -> strategy_profiles` 循环依赖。
- 2026-04-02：修复循环依赖
  - 文件：`src/xtrader/strategy_profiles/risk_engine.py`
  - 修复：移除 `TradeAction` 跨包依赖，改本地动作常量，打断循环引用。
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_risk_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategies/test_profile_action_strategy.py tests/unit/strategies/test_builtin.py`
  - 结果：`24 passed`
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
  - 结果：`30 passed`
- 2026-04-02：`PYTHONPATH=src python -m py_compile src/xtrader/strategies/builtin_strategies/profile_action.py src/xtrader/strategies/builtin.py src/xtrader/strategies/builtin_strategies/__init__.py src/xtrader/strategies/__init__.py tests/unit/strategies/test_profile_action_strategy.py tests/unit/strategies/test_builtin.py`
  - 结果：通过
- 2026-04-02：`python scripts/task_guard.py check XTR-SP-007`
  - 结果：通过（`✓ Spec & Validation check passed.`）

## Evidence
- 代码修改：
  - `src/xtrader/strategies/builtin_strategies/profile_action.py`
  - `src/xtrader/strategies/builtin_strategies/__init__.py`
  - `src/xtrader/strategies/builtin.py`
  - `src/xtrader/strategies/__init__.py`
  - `src/xtrader/strategy_profiles/risk_engine.py`（循环依赖修复）
  - `tests/unit/strategies/test_profile_action_strategy.py`
  - `tests/unit/strategies/test_builtin.py`
- 关联回归：
  - `tests/unit/strategy_profiles/test_risk_engine.py`
  - `tests/unit/strategy_profiles/test_signal_engine.py`
  - `tests/unit/strategy_profiles/test_regime_scoring_engine.py`
  - `tests/unit/strategies/test_feature_engine.py`
  - `tests/unit/strategy_profiles/test_profile_schema_gate.py`
  - `tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
