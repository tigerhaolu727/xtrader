# Validation Plan (XTR-SP-017)

## Planned Validation
- [x] `python scripts/task_guard.py check XTR-SP-017` —— 守门检查通过。
- [x] 单元测试：`tests/unit/strategies/test_feature_engine.py` —— 验证现有能力不回归。
- [x] 新增测试：`kama/trix/mfi` family 正例（注册、计算、列命名）。
- [x] 新增测试：`mama/ht_*/frama` family 正例（注册、计算、列命名）。
- [x] 新增测试：`frama` 项目内实现行为（warmup、参数边界、常数 `4.6` 基线）验证。
- [x] 新增测试：state 同源派生反例（缺 source / 跨周期 / 禁用参数）应 fail-fast。
- [x] 迁移测试：`macd/macd_state` 同源派生约束与兼容策略验证。

## Execution Log
- 运行命令与结果（时间、状态、日志要点）
- 2026-04-06 任务初始化：
  - `python scripts/task_guard.py new XTR-SP-017 --title "快速可落地指标接入与同源派生双层结构重构"`
  - 结果：Spec/Validation 模板创建成功。
  - `python scripts/task_guard.py check XTR-SP-017`
  - 结果：通过。
- 2026-04-06 Phase 1（KAMA/TRIX/MFI）实现与回归：
  - `PYTHONPATH=src pytest tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py -q`
  - 结果：通过（`40 passed in 3.53s`）。
  - 日志要点：
    - 新增 `kama/trix/mfi` 指标族实现与 registry 注册完成；
    - 新增指标单测通过；
    - 原有 feature-engine 与 precompile 语义测试未回归。
- 2026-04-06 Phase 2/3（同源派生约束 + macd_state source-bound）实现与回归：
  - `PYTHONPATH=src pytest tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py -q`
  - 结果：通过（`47 passed in 3.15s`）。
  - `PYTHONPATH=src pytest tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategies/test_profile_action_strategy.py -q`
  - 结果：通过（`21 passed in 3.71s`）。
  - 日志要点：
    - precompile 增加 `source_instance_id` 强约束及 `macd_state -> macd` family 校验；
    - `required_indicator_plan_by_tf` 自动包含 state 依赖 source；
    - `macd_state` 计算改为只消费 source `line/signal/hist`，不再独立重算主值；
    - profile `ai_multi_tf_signal_v1/v0.2` 已迁移为 source-bound 参数写法。
- 2026-04-06 任务范围补充（按 `XTR-WS-007` 对齐）：
  - 补充范围：在 `XTR-SP-017` 内追加 `mama/ht_*/frama` 三项指标开发目标；
  - 约束确认：`frama` 采用项目内实现路径，保持 `4.6` 常数基线；
  - 状态：已进入实现与验证。
- 2026-04-06 Phase 1B（MAMA/HT/FRAMA）实现与回归：
  - `PYTHONPATH=src pytest tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py -q`
  - 结果：通过（`53 passed in 4.12s`）。
  - `PYTHONPATH=src pytest tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategies/test_profile_action_strategy.py -q`
  - 结果：通过（`21 passed in 3.72s`）。
  - 日志要点：
    - 新增 `mama/ht_trendline/frama` 指标族实现并接入 registry；
    - 新增 `mama` 多输出映射（`mama/fama`）并接入 pipeline/precompile feature_ref 解析；
    - `frama` 采用项目内实现，保持 `alpha = exp(-4.6 * (D - 1))` 基线；
    - 新增指标与既有 profile 链路回归均通过。

## Evidence
- 链接或附件（如截图、日志路径、CI 链接）
- 已补充：
  - `PYTHONPATH=src pytest tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py -q`
  - 输出：`40 passed in 3.53s`
  - `PYTHONPATH=src pytest tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py -q`
  - 输出：`47 passed in 3.15s`
  - `PYTHONPATH=src pytest tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategies/test_profile_action_strategy.py -q`
  - 输出：`21 passed in 3.71s`
  - `PYTHONPATH=src pytest tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py -q`
  - 输出：`53 passed in 4.12s`
  - `PYTHONPATH=src pytest tests/unit/strategy_profiles/test_regime_scoring_engine.py tests/unit/strategy_profiles/test_signal_engine.py tests/unit/strategies/test_profile_action_strategy.py -q`
  - 输出：`21 passed in 3.72s`
