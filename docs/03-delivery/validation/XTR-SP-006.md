# Validation Plan (XTR-SP-006)

## Planned Validation
- [x] `risk_engine_fixed_pct_positive`：验证 fixed_pct 模式 LONG/SHORT 止损止盈价格计算。
- [x] `risk_engine_atr_rr_positive`：验证 atr_multiple + rr_multiple 模式价格计算。
- [x] `risk_engine_action_size_contract_positive`：验证 `ENTER_* size>0`、`EXIT/HOLD size=0`。
- [x] `risk_engine_portfolio_guards_positive`：验证 `daily_loss_limit/max_concurrent_positions` 最小钩子行为。
- [x] `risk_engine_missing_close_negative`：缺失 `close` 时 fail-fast。
- [x] `risk_engine_missing_atr_negative`：`atr_multiple` 模式缺失 ATR 列时 fail-fast。
- [x] `unit_tests_for_risk_engine`：新增/更新单测并通过。

## Execution Log
- 2026-04-02：新增 `RiskEngine` 运行时实现
  - 文件：`src/xtrader/strategy_profiles/risk_engine.py`
  - 关键逻辑：`fixed_fraction/fixed_pct/atr_multiple/rr_multiple`、`symbol+action` 风险输出契约、`portfolio_guards` 最小钩子。
- 2026-04-02：新增单测 `tests/unit/strategy_profiles/test_risk_engine.py`
  - 覆盖：fixed_pct、atr+rr、size 合约、guards、缺失 close fail-fast、缺失 atr fail-fast。
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_risk_engine.py`
  - 首轮结果：`1 failed, 5 passed`
  - 失败要点：`itertuples` 对列名 `__atr__` 重命名，导致 ATR 读取为 NaN。
- 2026-04-02：修复 `src/xtrader/strategy_profiles/risk_engine.py`
  - 修复点：内部 ATR 列名改为 `atr_runtime_value`，避免 `itertuples` 列名重写。
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_risk_engine.py`
  - 结果：`6 passed`
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
  - 结果：`43 passed`
- 2026-04-02：`PYTHONPATH=src python -m py_compile src/xtrader/strategy_profiles/risk_engine.py tests/unit/strategy_profiles/test_risk_engine.py`
  - 结果：通过
- 2026-04-02：`python scripts/task_guard.py check XTR-SP-006`
  - 结果：通过（`✓ Spec & Validation check passed.`）

## Evidence
- 代码修改：
  - `src/xtrader/strategy_profiles/risk_engine.py`
  - `src/xtrader/strategy_profiles/__init__.py`
  - `tests/unit/strategy_profiles/test_risk_engine.py`
- 关联回归：
  - `tests/unit/strategy_profiles/test_signal_engine.py`
  - `tests/unit/strategy_profiles/test_regime_scoring_engine.py`
  - `tests/unit/strategies/test_feature_engine.py`
  - `tests/unit/strategy_profiles/test_profile_schema_gate.py`
  - `tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
