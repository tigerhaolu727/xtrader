# StrategyProfile 语义校验与预编译阻断 (XTR-SP-002)

## Intent
- `XTR-SP-001` 已完成结构 schema 守门，但仍缺少 profile 级语义一致性校验。
- 若缺失该层，运行时可能出现规则冲突、配置漂移与“可解析但不可执行”的问题。
- 本任务目标是在 precompile 阶段完成关键语义阻断，形成 M1 的完整编译可用能力。

## Requirement
### 功能目标
- 在 `StrategyProfilePrecompileEngine` 中新增语义校验能力：
  - `score_fn` 签名（arity）与参数白名单/边界校验；
  - classifier `inputs` 与启用规则 `conditions[].ref` 集合一致性校验；
  - `SignalSpec.reason_code_map` 覆盖所有启用规则；
  - `SignalSpec.priority_rank` 在 `entry/exit/hold` 全局唯一；
  - `score_range` 语义校验（无界用 `null`、区间非空、覆盖规则）。
- 构建并输出预编译依赖产物：
  - `required_feature_refs`
  - `required_indicator_plan_by_tf`
  - `resolved_input_bindings`（`rule_id -> role:feature_ref`）

### 非目标 / 范围外
- 不在本任务实现规则打分执行与 state 合成（`XTR-SP-004`）。
- 不在本任务实现 SignalEngine 动作输出执行（`XTR-SP-005`）。
- 不在本任务实现 RiskEngine 计算（`XTR-SP-006`）。

### 输入输出 / 接口
- 输入：
  - `StrategyProfileLoader` 已通过 schema 的 profile。
- 输出：
  - precompile 成功：返回 resolved profile + 语义产物；
  - precompile 失败：返回稳定错误码与错误消息。

## Design
### 核心思路与架构
- 在现有 `StrategyProfilePrecompileEngine.compile()` 中追加“语义校验阶段”。
- 采用 fail-fast：任一关键语义失败直接返回 `FAILED`，不进入后续阶段。

### 数据/接口/模型
- `score_fn` 注册表（v0.3 冻结）：
  - `trend_score/momentum_score/direction_score/volume_score/pullback_score`
  - 绑定 `input_roles` 与参数约束。
- feature 引用解析：
  - 解析 `f:<timeframe>:<instance_id>:<output_key>`；
  - 对照 `indicator_plan_by_tf` 验证存在性并构建最小依赖计划。
- 信号规则校验：
  - `priority_rank` 全局唯一（启用规则集合）。
  - `reason_code_map` 覆盖启用规则。
  - 若无启用 `HOLD` 兜底，启用规则区间必须覆盖 `[-1,1]`。

### 风险与权衡
- 风险 1：语义规则一次性收得太多，影响调试效率。
  - 处理：保持错误码精确且首错返回，便于快速修复。
- 风险 2：区间覆盖算法边界处理复杂。
  - 处理：实现严格区间拼接判定，并加边界单测。

## Acceptance
- 给定 `v0.3.json`，precompile 语义阶段通过。
- 能对以下错误返回失败并给出稳定错误码：
  - `SCORE_FN_INPUT_ARITY_MISMATCH`
  - `UNUSED_CLASSIFIER_INPUT`
  - `UNDECLARED_CLASSIFIER_REF`
  - `SIGNAL_PRIORITY_RANK_DUPLICATE`
  - `MISSING_REASON_CODE_MAPPING`
  - `SIGNAL_SCORE_RANGE_COVERAGE_GAP`（无 HOLD 兜底时）
- precompile 成功结果包含：
  - `required_feature_refs`
  - `required_indicator_plan_by_tf`
  - `resolved_input_bindings`
- 自动化测试覆盖正例与主要负例。

## Notes
- 依赖：
  - `docs/03-delivery/specs/XTR-SP-001.md`
  - `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
  - `docs/03-delivery/roadmap/implementation-tasks-v0.3.md`
- 里程碑对齐：
  - 本任务完成后，M1（`XTR-SP-001 ~ XTR-SP-002`）可标记为完成。
