# 快速可落地指标接入与同源派生双层结构重构 (XTR-SP-017)

## Intent
承接 `XTR-WS-007`，将“快速可落地指标接入”与“同源派生双层结构”从研讨结论落地为可实现任务。

当前痛点：
1. 新指标（KAMA/TRIX/MFI/MAMA/HT/FRAMA）尚未完整进入项目指标族，无法用于 profile 条件扩展；
2. 现有 `macd_state` 仍可独立重算主值，存在值层/状态层参数漂移风险。

本任务目标是在不改变策略业务语义的前提下，完成指标族扩展与架构约束落地，为后续策略实验提供稳定底座。

## Requirement
- 功能目标
  - 新增快速可落地指标值层 family：
    - 第一批：`kama`、`trix`、`mfi`（已落地）；
    - 第二批：`mama`、`ht_*`（Hilbert 族）与 `frama`（本任务补齐）。
  - 指标计算约束：
    - `kama/trix/mfi/mama/ht_*`：可采用 TA-Lib 优先策略（若环境不可用需有明确 fallback 或失败提示策略）；
    - `frama`：采用项目内实现路径（不依赖 TA-Lib 核心函数）。
  - 引入“同源派生”能力：状态层通过 `source_instance_id` 绑定值层实例，不允许重复声明主指标参数。
  - 对现有 `macd/macd_state` 完成同源派生改造（至少在预编译/参数校验层完成约束）。
  - 在预编译或等价校验流程中增加以下规则：
    - source 实例存在且唯一可解析；
    - state 与 source 同周期；
    - state family 与 source family 匹配；
    - state 禁止携带主指标参数；
    - 输出命名可追溯 source。
- 非目标 / 范围外
  - 不实现订单簿/逐笔数据指标（OBI/QI/OFI/VPIN）。
  - 不在本任务中进行 TrackB 回测验证或策略参数调优。
  - 不改动策略积分规则、gate 阈值或风险模型逻辑。
- 输入输出或接口
  - 输入：现有 `indicator_plan_by_tf`、feature-engine registry、precompile 流程。
  - 输出：
    - 新增/更新指标 family 实现与注册；
    - 同源派生参数/校验规则；
    - 对应测试覆盖与验证记录。

## Design
- 核心思路与架构
  - 维持现有指标族接口（`BaseIndicator`）与注册机制不变；
  - 增量接入 `kama/trix/mfi/mama/ht_*/frama` 值层；
  - 状态层统一采用 source 绑定模式，避免第二真源；
  - 通过 precompile/plan 校验拦截“state 独立主参数”配置。
- 数据/接口/模型
  - `kama/trix/mfi/mama/ht_*/frama` 以 `close` 或 `hlcv` 为输入，输出单值/多值列（遵循命名规范）。
  - `state` 族参数分层：
    - 值层主参数：仅出现在 source family；
    - 状态参数：仅用于状态判定（lookback、阈值、连续根数等）。
  - `source_instance_id` 作为统一绑定字段，要求同 timeframe 解析。
- 风险与权衡
  - TA-Lib 依赖风险：不同平台可能存在安装差异；
  - 向后兼容风险：旧配置可能依赖 state 独立参数，需要兼容期或迁移提示；
  - warmup/NaN 对齐风险：新增指标需与现有 pipeline 行对齐，避免回测偏差。

## Development Plan

### Phase 0: 基线与守门
- 冻结任务范围：仅做新指标开发与同源派生双层结构重构，不包含 TrackB 验证。
- 基线验证：
  - `python scripts/task_guard.py check XTR-SP-017`
  - `pytest tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py -q`
- 输出：
  - 记录当前失败/通过基线，作为后续回归对照。

### Phase 1: 新增值层指标家族（KAMA/TRIX/MFI）
- 目标：新增 3 个可注册、可计算、可引用的 value-layer family。
- 代码改动点：
  - 新增指标文件：
    - `src/xtrader/strategies/feature_engine/indicators/trend/kama.py`
    - `src/xtrader/strategies/feature_engine/indicators/trend/trix.py`
    - `src/xtrader/strategies/feature_engine/indicators/volume/mfi.py`
  - 注册与导出：
    - `src/xtrader/strategies/feature_engine/indicators/registry.py`
    - `src/xtrader/strategies/feature_engine/indicators/trend/__init__.py`
    - `src/xtrader/strategies/feature_engine/indicators/volume/__init__.py`
- 设计约束：
  - 统一继承 `BaseIndicator`，沿用 `param_order + params_schema + build_output_columns`。
  - 默认产出单列（`output_key=value`），命名遵循现有列规范。
  - 计算内核采用“TA-Lib 优先 + 明确降级策略（fallback 或 fail-fast 错误信息）”。
- 验收：
  - `build_default_indicator_registry().families()` 包含 `kama/trix/mfi`。
  - `FeaturePipeline.compute_features` 可稳定输出三类指标列。

### Phase 1B: 新增值层指标家族（MAMA/HT/FRAMA）
- 目标：补齐第二批 3 类 family，使 `XTR-WS-007` 指标清单在本任务内闭环。
- 代码改动点：
  - 新增指标文件：
    - `src/xtrader/strategies/feature_engine/indicators/trend/mama.py`
    - `src/xtrader/strategies/feature_engine/indicators/trend/ht_*.py`（按约定输出族选择最小可用子集）
    - `src/xtrader/strategies/feature_engine/indicators/trend/frama.py`
  - 注册与导出：
    - `src/xtrader/strategies/feature_engine/indicators/registry.py`
    - `src/xtrader/strategies/feature_engine/indicators/trend/__init__.py`
- 设计约束：
  - `mama/ht_*` 采用 TA-Lib 优先 + fallback/fail-fast 一致策略；
  - `frama` 使用项目内实现，默认保留 `4.6` 常数，不在本任务调整；
  - 输出列命名需与现有 feature_ref 解析规则兼容。
- 验收：
  - `build_default_indicator_registry().families()` 包含 `mama/ht_*/frama`；
  - `FeaturePipeline.compute_features` 可稳定输出第二批指标列；
  - `frama` 的 warmup/NaN 行为可预测且有测试覆盖。

### Phase 2: 同源派生约束落地（Precompile）
- 目标：在 profile 预编译阶段强制 state/source 绑定规则，杜绝双参数漂移。
- 代码改动点：
  - `src/xtrader/strategy_profiles/precompile.py`
- 新增校验规则：
  - `source_instance_id` 必填且可解析；
  - `state.timeframe == source.timeframe`；
  - `state family ↔ source family` 匹配（先落地 `macd_state -> macd`）；
  - state 禁止声明主参数（`fast/slow/signal`）；
  - source 需存在于同周期 `indicator_plan_by_tf` 且实例唯一。
- 依赖闭包处理：
  - 当规则仅引用 state 特征时，`required_indicator_plan_by_tf` 仍需自动包含 source 实例，保证执行期可计算。
- 验收：
  - 缺 source / 跨周期 / family 不匹配 / 禁用参数命中时，`compile()` 返回 `FAILED` 且错误路径可定位。

### Phase 3: `macd_state` 同源派生重构
- 目标：`macd_state` 仅消费 source 输出，不再独立重算主值。
- 代码改动点：
  - `src/xtrader/strategies/feature_engine/indicators/trend/macd_state.py`
  - `src/xtrader/strategies/feature_engine/pipeline.py`（按最小改动支持 state 读取 source 产物）
- 关键实现：
  - `macd_state.params_schema` 改为：
    - 必填：`source_instance_id`
    - 状态参数：`near_gap_pct/near_gap_abs/slope_min/narrow_bars`
    - 禁止主参数：`fast/slow/signal`
  - 计算路径改为基于 source 的 `line/signal/hist` 列派生状态。
  - 输出命名需包含 source 绑定信息，保证追溯性。
- 验收：
  - 同一 source 下 state 输出与预期一致；
  - 主参数漂移场景在 precompile 被拦截，执行期不再出现“第二真源”。

### Phase 4: 测试补齐与配置迁移
- 测试改动点：
  - `tests/unit/strategies/test_feature_engine.py`
  - `tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
- 必补测试集：
  - 新指标正例：注册、输出列、warmup 与值域基本正确性；
  - 同源派生反例：缺 source、跨周期、禁用参数、family 不匹配；
  - `macd_state` 正例：source 绑定后输出稳定；
  - 依赖闭包：仅引用 state 的 profile 仍能自动带出 source 计划。
- 配置迁移：
  - 更新测试用 profile/fixture 的 `macd_state` 参数写法为 `source_instance_id` 绑定模式；
  - 必要时同步更新最小示例配置模板。

### Phase 5: 交付与记录
- 回归命令：
  - `python scripts/task_guard.py check XTR-SP-017`
  - `pytest tests/unit/strategies/test_feature_engine.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py -q`
- 文档回填：
  - 更新 `docs/03-delivery/validation/XTR-SP-017.md` 的 Execution Log 和 Evidence。
  - 会话结束补记 `docs/05-agent/session-notes/<YYYY-MM>.md` 并关联 `XTR-SP-017`。

### Milestone Exit Criteria
- M1: `kama/trix/mfi` 完成并通过单测。
- M2: precompile 同源约束全部生效。
- M3: `macd_state` 完成 source-bound 改造并通过回归。
- M4: 文档与验证证据补齐，可进入评审/提交。
- M5: `mama/ht_*/frama` 完成实现、注册与单测，任务范围闭环。

## Acceptance
- `python scripts/task_guard.py check XTR-SP-017` 通过。
- `kama/trix/mfi` 在 registry 可注册、可计算并输出稳定列名。
- `mama/ht_*/frama` 在 registry 可注册、可计算并输出稳定列名。
- 同源派生约束生效：状态层缺失 source、跨周期 source、携带禁用主参数时，校验失败并给出明确错误码/错误信息。
- `macd/macd_state` 至少在配置校验层满足同源派生约束（不再允许双参数体系漂移）。
- 关键单测通过（feature engine + 新增/改造 family 相关测试）。

## Notes
- 研讨来源：[`XTR-WS-007.md`](/Users/tiger/Development/GIt/xtrader/docs/03-delivery/workshops/items/XTR-WS-007.md)
- 知识库基线：[`indicator_family_knowledge_base_v1.md`](/Users/tiger/Development/GIt/xtrader/docs/02-strategy/knowledge-base/indicator_family_knowledge_base_v1.md)
- 关联代码路径：
  - `src/xtrader/strategies/feature_engine/indicators/`
  - `src/xtrader/strategies/feature_engine/pipeline.py`
  - `src/xtrader/strategies/feature_engine/indicators/registry.py`
