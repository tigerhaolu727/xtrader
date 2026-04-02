# Validation Plan (XTR-SP-009)

## Planned Validation
- [x] `task_guard_check_pre_code`：文档阶段守门通过后再进入编码。
- [x] `unit_profile_backtest_smoke_positive`：profile->backtest->writer 链路单测通过并校验关键产物存在。
- [x] `script_btcusdt_5m_smoke_positive`：使用本地 `BTCUSDT 5m` 真实数据执行 smoke 命令成功。
- [x] `artifact_contract_positive`：真实 smoke 产物包含 summary/trades/equity/signals/diagnostics/run_manifest。
- [x] `baseline_metrics_recorded_positive`：记录一次基线指标（trade_count/win_rate/max_drawdown/net_return）。

## Execution Log
- 2026-04-02：`python scripts/task_guard.py check XTR-SP-009`
  - 结果：通过（文档守门，允许进入编码阶段）。
- 2026-04-02：实现 `XTR-SP-009` 交付物
  - 新增脚本：`scripts/run_profile_action_backtest_smoke.py`
  - 新增单测：`test_profile_action_strategy_backtest_smoke_writes_baseline_artifacts`
  - 更新文件：`tests/unit/backtests/test_event_driven.py`
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/backtests/test_event_driven.py -k "profile_action_strategy_backtest_smoke_writes_baseline_artifacts or strategy_scoped_report_root_and_outputs"`
  - 结果：`2 passed, 14 deselected`
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/strategies/test_profile_action_strategy.py`
  - 结果：`3 passed`
- 2026-04-02：`PYTHONPATH=src pytest -q tests/unit/backtests/test_event_driven.py`
  - 结果：`16 passed`
- 2026-04-02：`PYTHONPATH=src python -m py_compile scripts/run_profile_action_backtest_smoke.py tests/unit/backtests/test_event_driven.py`
  - 结果：通过
- 2026-04-02：`PYTHONPATH=src python scripts/run_profile_action_backtest_smoke.py --start 2026-01-01T00:00:00Z --end 2026-01-15T00:00:00Z --run-id 20260402T030500Z_xtr_sp_009_smoke`
  - 结果：成功（`status=SUCCESS`）
  - 数据窗口：`2026-01-01T00:00:00Z` 到 `2026-01-15T00:00:00Z`
  - 输入规模：`bars=4032`，`actions=4032`
  - 基线指标：
    - `trade_count=95`
    - `win_rate=0.12631578947368421`
    - `max_drawdown=-0.003086890324540903`
    - `net_return=-0.0029697348022525993`
  - 备注：运行期出现 `cpu_info.cc` 的 `sysctlbyname` warning，不影响产物生成与任务验收。

## Evidence
- 代码修改：
  - `scripts/run_profile_action_backtest_smoke.py`
  - `tests/unit/backtests/test_event_driven.py`
  - `docs/03-delivery/specs/XTR-SP-009.md`
  - `docs/03-delivery/validation/XTR-SP-009.md`
- 真实 smoke 产物目录：
  - `reports/backtests/strategy/profile_action/20260402T030500Z_xtr_sp_009_smoke`
- 关键产物：
  - `summary.json`
  - `diagnostics.json`
  - `ledgers/trades.parquet`
  - `curves/equity_curve.parquet`
  - `timelines/signal_execution.parquet`
  - `run_manifest.json`
