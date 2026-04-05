# Validation Plan (XTR-SP-013)

## Planned Validation
- [x] `python scripts/task_guard.py check XTR-SP-013` —— 确认 Spec/Validation 守门通过。
- [x] 表达式层校验：新增 `eq/neq/in_set` 的正反例（schema + precompile）。
- [x] `macd_state` 语义校验：near-cross 与 reject 条件可由单次状态计算派生。
- [x] 支撑阻力接近度校验：`0.3/0.8/1.5` 百分比分级与 `near_support` 命中一致。
- [x] Gate 聚合校验：`all_of/n_of_m/cross_tf` 命中统计与预期一致。
- [x] Trace 校验：输出包含条件命中、gate 命中、`macd_state` 核心字段。
- [x] Viewer 校验（decision_trace）：`decision_trace_viewer.html` 可展示 `condition_hits / gate_results / score_adjustment / macd_state` 四项证据链信息。
- [x] Viewer 校验（report 联动）：`offline_report_viewer.html` 交易决策弹窗可展示上述四项摘要，并保持 “在独立页面查看完整决策链” 跳转可用。
- [x] Viewer 回归：在缺失上述字段时保持降级兼容（不报错，可继续查询/查看）。
- [x] 证据链字段落位校验：四项信息可从现有 JSON 容器（`rule_results` / `signal_decision`）被 viewer 正确解析展示。
- [x] `condition_hits` 结构校验：同时包含命中列表与全量结果（`hits` + `results`）。
- [x] `gate_results` 结构校验：包含 `gate_id/mode/min_hit/hit_count/hit_keys/miss_keys/passed`。
- [x] `score_adjustment` 结构校验：包含 `score_base/score_adjustment/score_final` 及 `fn/params`。
- [x] `macd_state` 最小字段校验：`state_code/near_cross/reject_long/reject_short/meta.gap/meta.gap_slope/meta.gap_pct` 可见。

## Execution Log
- 2026-04-04: `python scripts/task_guard.py new XTR-SP-013 --title "Signal V1 最小实现范围落地"` -> PASS（已生成 Spec/Validation 模板）。
- 2026-04-04: 补齐 Spec/Validation 初稿，待执行 `task_guard check` 守门。
- 2026-04-04: `python scripts/task_guard.py check XTR-SP-013` -> PASS（Spec/Validation 守门通过）。
- 2026-04-04: 补充 Viewer 适配验证项（Signal V1 证据链四项展示与联动回归），待实现后执行。
- 2026-04-04: 补充 viewer 默认决策对应验证断言（字段落位/结构键/降级兼容），待实现后执行。
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py` -> PASS（29 passed，完成 Step 1 契约层回归）。
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategies/test_profile_action_strategy.py` -> PASS（35 passed，完成 Step 2 运行时与 trace 产出回归）。
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/backtests/test_offline_viewer.py` -> PASS（2 passed，完成 Step 3 viewer 资产回归）。
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategies/test_profile_action_strategy.py tests/unit/backtests/test_offline_viewer.py` -> PASS（37 passed，完成 Step 1-3 合并回归）。
- 2026-04-04: 对 `decision_trace_viewer.html` 与 `offline_report_viewer.html` 新增 Signal V1 证据链渲染逻辑进行静态检查（字段兼容降级分支、N/A 回退、按钮联动路径）-> PASS（未发现语法/结构性问题）。
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategies/test_profile_action_strategy.py tests/unit/backtests/test_offline_viewer.py tests/unit/backtests/test_event_driven.py tests/unit/runtime/test_runtime_v1.py` -> PASS（75 passed，完成 Step 4 跨模块回归）。
- 2026-04-04: `python -m py_compile src/xtrader/strategy_profiles/models.py src/xtrader/strategy_profiles/precompile.py src/xtrader/strategy_profiles/regime_scoring.py src/xtrader/strategy_profiles/score_fn_registry.py src/xtrader/strategy_profiles/signal_engine.py src/xtrader/strategies/builtin_strategies/profile_action.py src/xtrader/backtests/offline_viewer.py` -> PASS（语法编译检查通过）。
- 2026-04-04: Planned Validation 勾选状态与执行证据同步完成（交付前收口检查）。

## Evidence
- Spec: `docs/03-delivery/specs/XTR-SP-013.md`
- Validation: `docs/03-delivery/validation/XTR-SP-013.md`
- Workshop: `docs/03-delivery/workshops/items/XTR-WS-003.md`
