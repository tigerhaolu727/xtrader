# Validation Plan (XTR-SP-014)

## Planned Validation
- [x] `python scripts/task_guard.py check XTR-SP-014` —— Spec/Validation 守门通过。
- [x] indicator family 正例：`macd_state` 在 feature_engine 可注册、可计算并输出约定列。
- [x] indicator family 正例：`support_proximity` 在 feature_engine 可注册、可计算并输出约定列。
- [x] indicator 参数反例：非法阈值/窗口参数 fail-fast，错误信息明确。
- [x] `macd_state` 业务校验：`near_golden/near_dead/reject_long/reject_short/green_narrow_2/red_narrow_2` 命中与样例一致。
- [x] `support_proximity` 分级校验：`distance_pct` 与 `strength_code(0/1/2/3)` 在 `0.3/0.8/1.5` 阈值下分级一致。
- [x] profile 兼容校验：strict profile 使用新特征列并仅使用现有 DSL 运算符（不新增原语）可 precompile 通过。
- [x] trace 校验：`condition_results/condition_hits/rule_traces/macd_state` 可追溯新增条件命中。
- [ ] viewer 校验：证据字段存在时可展示，不存在时降级 `N/A` 且查询/跳转不受影响。
- [x] 回归校验：`XTR-SP-013` 既有用例（strategy_profiles/profile_action/offline_viewer/runtime）通过。

## Execution Log
- 2026-04-04: `python scripts/workshop_guard.py new --auto-id --title "Signal V1 原语与派生特征扩展" --type requirement` -> PASS（创建 `XTR-WS-004`）。
- 2026-04-04: 完成 `XTR-WS-004` 内容补全与 ready gate 修订（移除语义歧义词）。
- 2026-04-04: `python scripts/workshop_guard.py check XTR-WS-004 --ready` -> PASS。
- 2026-04-04: `python scripts/task_guard.py new XTR-SP-014 --title "Signal V1 原语与派生特征扩展"` -> PASS（生成 Spec/Validation 模板）。
- 2026-04-04: 补齐 `XTR-SP-014` Spec/Validation 初稿，待执行 `task_guard check`。
- 2026-04-04: 根据用户确认，方案从“扩 DSL 原语”切换为“feature-first（新增指标族预计算）”；Spec/Validation 已同步重写。
- 2026-04-04: 实现 `macd_state` 指标族并接入 `registry/pipeline/precompile suffix map`。
- 2026-04-04: 实现 `support_proximity` 指标族并接入 `registry/pipeline/precompile suffix map`。
- 2026-04-04: 扩展 `regime_scoring` 的 `macd_state` 提取逻辑，支持从 `f:*:macd_state*:*` 特征列自动识别并落入 trace。
- 2026-04-04: 新增/更新单测：
  - `tests/unit/strategies/test_feature_engine.py`（registry、macd_state、support_proximity、profile feature ref 解析）
  - `tests/unit/strategy_profiles/test_profile_semantic_precompile.py`（macd_state/support_proximity suffix feature_ref 接受）
  - `tests/unit/strategy_profiles/test_regime_scoring_engine.py`（macd_state from feature_refs trace 提取）
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py` -> PASS（31 passed）。
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategies/test_profile_action_strategy.py` -> PASS（25 passed）。
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py tests/unit/strategy_profiles/test_regime_scoring_engine.py` -> PASS（44 passed）。
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategies/test_profile_action_strategy.py tests/unit/backtests/test_offline_viewer.py tests/unit/backtests/test_event_driven.py tests/unit/runtime/test_runtime_v1.py` -> PASS（101 passed）。
- 2026-04-04: 新增 strict profile `configs/strategy-profiles/ai_multi_tf_signal_v1/v0.2.json`（使用 `macd_state/support_proximity` 预计算特征替换近似条件）。
- 2026-04-04: `PYTHONPATH=src python -c "…StrategyProfilePrecompileEngine().compile(v0.2)…"` -> PASS（`status=SUCCESS`，`required_refs=24`）。
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_profile_semantic_precompile.py tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_regime_scoring_engine.py` -> PASS（45 passed）。
- 2026-04-04: `PYTHONPATH=src pytest -q tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategies/test_profile_action_strategy.py tests/unit/backtests/test_offline_viewer.py tests/unit/backtests/test_event_driven.py tests/unit/runtime/test_runtime_v1.py` -> PASS（102 passed）。

## Evidence
- Workshop: `docs/03-delivery/workshops/items/XTR-WS-004.md`
- Spec: `docs/03-delivery/specs/XTR-SP-014.md`
- Validation: `docs/03-delivery/validation/XTR-SP-014.md`
