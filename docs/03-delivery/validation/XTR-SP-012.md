# Validation Plan (XTR-SP-012)

## Planned Validation
- [x] `python scripts/task_guard.py check XTR-SP-012`  
  目的：确认 Spec/Validation 资产完整，满足“先文档后开发”守门要求。
- [ ] `PYTHONPATH=src python scripts/run_profile_action_backtest_smoke.py --profile configs/strategy-profiles/five_min_regime_momentum/v0.3.json --start 2026-01-01T00:00:00Z --end 2026-01-15T00:00:00Z --run-id xtr_sp_012_trace_smoke`  
  目的：生成带 `decision_trace` 的回测产物并验证文件落盘。
- [ ] `python - <<'PY' ... pd.read_parquet('.../decision_trace.parquet') ... PY`  
  目的：校验 `decision_trace` 字段完整性（含 `feature_values_json`、`required_feature_values_json`、`required_feature_refs_json` 与 score/signal/risk/action 链路字段）。
- [ ] `offline_report_viewer` 手工验证（浏览器）  
  目的：确认交易列表点击后以 popup 形式显示进/出场决策链摘要，支持关闭，且顶部按钮可跳转 `decision_trace_viewer.html`。
- [ ] `Trade Ledger` 检索与联动手工验证（浏览器）  
  目的：确认关键词/方向/PnL/时间范围/排序/页码跳转/时间定位可用；时间输入使用 `datetime picker` 且格式稳定；定位偏差阈值生效；筛选后点击交易仍能联动图表聚焦。
- [ ] `decision_trace_viewer.html` 手工验证（浏览器）  
  目的：确认独立页面可加载 parquet、按主键查询命中、未命中给出结构化错误；并验证从 `report viewer` popup 的“在独立页面查看完整决策链”可直接加载上下文而无需二次选择 run 目录。
- [x] `PYTHONPATH=src pytest -q tests/unit/backtests/test_offline_viewer.py tests/unit/backtests/test_event_driven.py tests/unit/runtime/test_runtime_v1.py`  
  目的：覆盖 decision_trace 产物写入、runtime 透传、viewer 资产初始化与脚本输出的回归验证。
- [ ] 数据或环境准备  
  - 准备单 run 目录（含 `run_manifest.json`、`timelines/signal_execution.parquet`、`ledgers/trades.parquet`、`decision_trace.parquet`）。
  - 浏览器本地文件访问环境（与现有离线 viewer 一致）。

## Execution Log
- `2026-04-02`: `python scripts/task_guard.py check XTR-SP-012` -> PASS（文档守门通过，进入实现前评审阶段）。
- `2026-04-02`: `PYTHONPATH=src pytest -q tests/unit/backtests/test_offline_viewer.py tests/unit/backtests/test_event_driven.py tests/unit/runtime/test_runtime_v1.py` -> PASS（`40 passed in 14.57s`）。
- `2026-04-02`: `python scripts/task_guard.py check XTR-SP-012` -> PASS（实现后复检通过）。
- `2026-04-02`: `run_profile_action_backtest_smoke` 与浏览器手工验证未执行（当前仅完成代码与单测验证，待补实测证据与截图）。
- `2026-04-02`: `PYTHONPATH=src pytest -q tests/unit/backtests/test_offline_viewer.py tests/unit/backtests/test_event_driven.py tests/unit/runtime/test_runtime_v1.py` -> PASS（`40 passed in 9.15s`，覆盖 popup/handoff 调整后回归）。
- `2026-04-02`: `python scripts/task_guard.py check XTR-SP-012` -> PASS（popup/handoff 文档与实现一致性复检通过）。
- `2026-04-02`: `PYTHONPATH=src pytest -q tests/unit/backtests/test_offline_viewer.py tests/unit/backtests/test_event_driven.py tests/unit/runtime/test_runtime_v1.py` -> PASS（`40 passed in 11.11s`，覆盖 Trade Ledger 检索增强后回归）。
- `2026-04-02`: `python scripts/task_guard.py check XTR-SP-012` -> PASS（Trade Ledger v1 交互文档与实现一致性复检通过）。
- `2026-04-02`: `PYTHONPATH=src pytest -q tests/unit/backtests/test_offline_viewer.py tests/unit/backtests/test_event_driven.py tests/unit/runtime/test_runtime_v1.py` -> PASS（`40 passed in 9.68s`，覆盖 datetime picker 与工具条对齐优化后回归）。
- `2026-04-02`: `python scripts/task_guard.py check XTR-SP-012` -> PASS（datetime picker 与布局优化文档一致性复检通过）。

## Evidence
- Spec: `docs/03-delivery/specs/XTR-SP-012.md`
- Workshop: `docs/03-delivery/workshops/items/XTR-WS-002.md`
- 实施后补充：
  - `decision_trace.parquet` 实际路径
  - UI 截图（report viewer 联动、decision_trace_viewer 查询页）
  - 相关测试日志/CI 链接
