# Validation Plan (XTR-SP-016)

## Planned Validation
- [x] `python scripts/task_guard.py check XTR-SP-016` —— 守门检查通过。
- [x] 单元/组件验证：执行 profile action 相关测试 —— 确保行为兼容。
- [ ] 冒烟回测：`scripts/run_profile_action_backtest_smoke.py`（2024-01）—— 对比改造前后输出一致性。
- [ ] 性能对比：记录 `build_profile_model_df` 与 decision_trace 构建阶段耗时 —— 验证重复构建移除后收益。
- [ ] 结果核对：`action`、`score_total`、`reason`、Signal V1 证据链字段（`condition_hits/gate_results/score_adjustment/macd_state`）存在且可追溯。

## Execution Log
- 运行命令与结果（时间、状态、日志要点）
- 2026-04-04 任务初始化：
  - `python scripts/task_guard.py new XTR-SP-016 --title "减少重复特征构建：一次性构建评分与Trace特征超集"`
  - 结果：Spec/Validation 模板创建成功。
  - `python scripts/task_guard.py check XTR-SP-016`
  - 结果：通过。
- 2026-04-04 实现后验证：
  - `PYTHONPATH=src pytest -q tests/unit/strategies/test_feature_engine.py tests/unit/strategies/test_profile_action_strategy.py`
  - 结果：`28 passed in 3.82s`。
  - `PYTHONPATH=src python scripts/run_profile_action_backtest_smoke.py --profile configs/strategy-profiles/ai_multi_tf_signal_v1/v0.2.json --exchange bitget --market-type futures --symbol BTCUSDT --interval 5m --start 2024-01-01T00:00:00Z --end 2024-01-03T00:00:00Z --run-suffix xtr_sp_016_smoke`
  - 结果：失败，`FileNotFoundError: no parquet files found under data/klines/bitget/futures/BTCUSDT/5m`（当前环境缺少该行情目录）。
  - `python scripts/task_guard.py check XTR-SP-016`
  - 结果：通过。

## Evidence
- 链接或附件（如截图、日志路径、CI 链接）
- 单测输出：`28 passed in 3.82s`
- 待补充：
  - 回测报告目录路径（需补齐本地行情数据后执行）
  - 性能计时对比日志
  - 关键 diff/测试输出
