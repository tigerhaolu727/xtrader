# Validation Plan (XTR-SP-015)

## Planned Validation
- [x] `python scripts/task_guard.py check XTR-SP-015` —— 守门检查 Spec/Validation 完整性
- [ ] `python -m pytest tests/strategy_profiles tests/strategies` —— 回归核心 profile/strategy 单测（避免行为回归）
- [x] `PYTHONPATH=src python scripts/run_profile_action_backtest_smoke.py --profile configs/strategy-profiles/ai_multi_tf_signal_v1/v0.2.json --exchange bitget --market-type linear_swap --symbol BTCUSDT --interval 5m --start 2023-01-01T00:00:00Z --end 2026-03-20T00:00:00Z --run-suffix btcusdt_5m_ai_multi_tf_v02_e2e` —— 端到端多周期回测验证（全区间，按三段执行收口）
- [x] 校验运行产物 —— 验证 report root 下 raw/resampled 快照、summary、decision_trace、run_manifest 完整（短区间样例）
- [x] 兼容性样例 —— 使用单周期 profile 执行 smoke，确认未回归

## Execution Log
- 运行命令与结果（时间、状态、日志要点）
- `2026-04-04` `python scripts/task_guard.py check XTR-SP-015` -> `PASS`
- `2026-04-04` `python -m py_compile scripts/run_profile_action_backtest_smoke.py` -> `PASS`
- `2026-04-04` `PYTHONPATH=src python scripts/run_profile_action_backtest_smoke.py --profile configs/strategy-profiles/ai_multi_tf_signal_v1/v0.2.json --exchange bitget --market-type linear_swap --symbol BTCUSDT --interval 5m --start 2026-01-01T00:00:00Z --end 2026-01-08T00:00:00Z --run-suffix ai_multi_tf_v02_runtimecore_short` -> `PASS`
  - 结果要点：自动识别并装配 `required_timeframes=[5m,15m,1h,4h]`；运行状态 `SUCCESS`；输出 `actions=2016`、`trades=105`。
  - 产物路径：`reports/backtests/strategy/profile_action/20260403T184022Z_profile_action_ai_multi_tf_v02_runtimecore_short/`
- `2026-04-04` 全区间命令（`2023-01-01`~`2026-03-20`）已发起；因执行时长显著偏长，本轮未完成收口记录，待下一轮补齐最终结果与产物核验。
- `2026-04-04` `PYTHONPATH=src python scripts/run_profile_action_backtest_smoke.py --profile configs/strategy-profiles/five_min_regime_momentum/v0.3.json --exchange bitget --market-type linear_swap --symbol BTCUSDT --interval 5m --start 2026-01-01T00:00:00Z --end 2026-01-03T00:00:00Z --run-suffix five_min_v03_runtimecore_compat` -> `PASS`
  - 结果要点：`required_timeframes=[5m]`，运行状态 `SUCCESS`，`actions=576`，`trades=6`。
  - 产物路径：`reports/backtests/strategy/profile_action/20260403T190202Z_profile_action_five_min_v03_runtimecore_compat/`
- `2026-04-04` 全区间按三段收口（等价覆盖 `2023-01-01`~`2026-03-20`）：
  - `seg_2023`：`2023-01-01`~`2024-01-01` -> `reports/backtests/strategy/profile_action/20260404T042944Z_profile_action_ai_multi_tf_v02_seg_2023/`
  - `seg_2024`：`2024-01-01`~`2025-01-01` -> `reports/backtests/strategy/profile_action/20260404T044658Z_profile_action_ai_multi_tf_v02_seg_2024/`
  - `seg_2025_2026`：`2025-01-01`~`2026-03-20` -> `reports/backtests/strategy/profile_action/20260404T045525Z_profile_action_ai_multi_tf_v02_seg_2025_2026/`
  - 汇总：`actions_total=338112`，`trades_total=9681`，`sample_count_total=338112`

## Evidence
- 链接或附件（如截图、日志路径、CI 链接）
- 短区间成功样例：
  - `reports/backtests/strategy/profile_action/20260403T184022Z_profile_action_ai_multi_tf_v02_runtimecore_short/summary.json`
  - `reports/backtests/strategy/profile_action/20260403T184022Z_profile_action_ai_multi_tf_v02_runtimecore_short/timelines/decision_trace.parquet`
  - `reports/backtests/strategy/profile_action/20260403T184022Z_profile_action_ai_multi_tf_v02_runtimecore_short/data_snapshot/dataset_index.json`
  - `reports/backtests/strategy/profile_action/20260403T184022Z_profile_action_ai_multi_tf_v02_runtimecore_short/data_snapshot/snapshot_meta.json`
- 单周期兼容样例：
  - `reports/backtests/strategy/profile_action/20260403T190202Z_profile_action_five_min_v03_runtimecore_compat/summary.json`
  - `reports/backtests/strategy/profile_action/20260403T190202Z_profile_action_five_min_v03_runtimecore_compat/run_manifest.json`
- 全区间三段证据：
  - `reports/backtests/strategy/profile_action/20260404T042944Z_profile_action_ai_multi_tf_v02_seg_2023/summary.json`
  - `reports/backtests/strategy/profile_action/20260404T044658Z_profile_action_ai_multi_tf_v02_seg_2024/summary.json`
  - `reports/backtests/strategy/profile_action/20260404T045525Z_profile_action_ai_multi_tf_v02_seg_2025_2026/summary.json`
