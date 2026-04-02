# Validation Plan (XTR-SP-011)

## Planned Validation
- [x] `python scripts/task_guard.py check XTR-SP-011` —— 文档守门通过（开发前/交付前）。
- [x] `rg -n "ThresholdIntradayStrategy|threshold_intraday"`（限定代码/脚本/配置目录）—— 确认下线对象无残留可执行引用。
- [x] `PYTHONPATH=src pytest -q tests/unit/strategies` —— 策略层单测回归通过（Profile 主链路仍可用）。
- [x] `PYTHONPATH=src pytest -q tests/unit/backtests/test_event_driven.py` —— 回测核心行为未回归。
- [x] `PYTHONPATH=src python scripts/run_profile_action_backtest_smoke.py --start 2026-01-01T00:00:00Z --end 2026-01-08T00:00:00Z` —— Profile 主链路 smoke 验证。

## Execution Log
- 2026-04-02：`python scripts/task_guard.py check XTR-SP-011` -> PASS（文档结构完整，允许进入开发）。
- 2026-04-02：执行 threshold 关联引用扫描：
  - 命令：`rg -n 'ThresholdIntradayStrategy|xtrader\.strategies\.intraday|builtin_strategies\.threshold_intraday|threshold_intraday' src scripts configs tests/unit/strategies tests/unit/backtests/test_event_driven.py`
  - 结果：仅剩 `tests/unit/strategies/test_builtin.py` 的“负向断言”引用（验证主入口不再导出）；无可执行路径残留。
- 2026-04-02：执行策略层单测：
  - 命令：`PYTHONPATH=src pytest -q tests/unit/strategies`
  - 结果：`40 passed in 3.05s`。
- 2026-04-02：执行回测核心单测：
  - 命令：`PYTHONPATH=src pytest -q tests/unit/backtests/test_event_driven.py`
  - 结果：`15 passed in 4.06s`。
- 2026-04-02：执行 profile 主链路 smoke：
  - 命令：`PYTHONPATH=src python scripts/run_profile_action_backtest_smoke.py --start 2026-01-01T00:00:00Z --end 2026-01-08T00:00:00Z`
  - 结果：`SUCCESS`，bars=`2016`，actions=`2016`，trades=`36`，产物落盘到 `reports/backtests/strategy/profile_action/20260402T083929Z_profile_action_btcusdt_5m_profile_smoke_v03/`。
- 2026-04-02：交付前守门：
  - 命令：`python scripts/task_guard.py check XTR-SP-011`
  - 结果：`✓ Spec & Validation check passed.`。

## Evidence
- Spec: `docs/03-delivery/specs/XTR-SP-011.md`
- Workshop: `docs/03-delivery/workshops/items/XTR-WS-001.md`
- 代码变更：
  - 删除：`src/xtrader/strategies/builtin_strategies/threshold_intraday.py`
  - 删除：`src/xtrader/strategies/intraday.py`
  - 删除：`scripts/backtest_threshold_intraday_15m.py`
  - 删除：`scripts/run_threshold_intraday_runtime_backtest.py`
  - 删除：`configs/runtime/threshold_intraday_btcusdt_5m_3y.strategy.json`
  - 删除：`tests/unit/strategies/test_intraday.py`
  - 更新：`tests/unit/backtests/test_event_driven.py`
  - 更新：`configs/runtime/five_min_regime_momentum_v0.3_legacy.strategy.json`
  - 更新：`docs/03-delivery/specs/XTR-SP-008.md`
  - 更新：`docs/03-delivery/validation/XTR-SP-008.md`
- 回测产物：
  - `reports/backtests/strategy/profile_action/20260402T083929Z_profile_action_btcusdt_5m_profile_smoke_v03/run_manifest.json`
