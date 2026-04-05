# 减少重复特征构建：一次性构建评分与Trace特征超集 (XTR-WS-006)

- workshop_id: `XTR-WS-006`
- type: `task` # requirement | task | bug
- status: `approved` # draft | discussing | review | approved | deferred | rejected
- created_at: `2026-04-04`
- updated_at: `2026-04-04`
- owner: `tiger + codex`
- related_task_ids: `["XTR-SP-016"]`
- source: `chat://codex-session-2026-04-04`

## Background
当前 `ProfileActionStrategy.generate_actions` 在同一次运行中会进行两次特征构建：
1) `build_profile_model_df` 用于评分/信号/风控；
2) `build_model_df` 用于补全 decision_trace 特征展示。

这会导致重复指标计算、额外 DataFrame merge、更高内存占用，已在性能分析中表现为显著开销。

## Goal / Problem Statement
减少重复特征构建，通过“一次性构建评分 + trace 所需特征超集”替代二次 `build_model_df`，在不改变策略语义和输出口径前提下提升运行效率。

## Scope In
- 梳理 `ProfileActionStrategy` 中评分路径与 decision_trace 路径的特征列需求并建立“超集列清单”。
- 调整特征构建流程：一次构建主模型特征后复用于 scoring/signal/risk/trace。
- 保持 Signal V1 证据链字段能力（`condition_hits / gate_results / score_adjustment / macd_state`）不退化。
- 对关键性能指标增加验证记录（至少包含总耗时、特征构建阶段耗时对比）。

## Scope Out
- 不改 `RuntimeCore` 主链路职责与输入契约。
- 不修改策略判定规则、积分公式、action/risk 行为。
- 不引入新的指标定义或改动 profile schema。

## Constraints
- 结果行为等价：同输入下 action 结果、关键评分字段需保持一致（允许浮点微小误差）。
- 决策追溯不降级：decision_trace 关键证据字段必须可追溯。
- 改造优先落在 `ProfileActionStrategy` 内部，不扩散到无关模块。
- 必须补齐 spec/validation 后才能进入代码改动。

## Requirement Summary
- REQ-001: 消除同一轮回测中的二次特征构建（避免额外 `build_model_df`）。
- REQ-002: 评分链路与 trace 链路共享同一份特征数据源（或共享缓存），避免重复计算与重复 merge。
- REQ-003: 改造后结果可追溯性不下降，Signal V1 证据链字段继续可用。
- REQ-004: 提供性能对比证据，证明该改造带来可观收益。

## Acceptance Criteria
- ACC-001 (REQ-001): 运行路径中不再出现用于 trace 的第二次 `build_model_df` 构建。
- ACC-002 (REQ-002): 评分、信号、风控与 trace 所需特征均来自同一轮特征构建产物（或缓存命中）。
- ACC-003 (REQ-003): 回测输出的 `action`、`score_total`、`reason` 与核心 decision_trace 字段在基准样本上保持一致。
- ACC-004 (REQ-004): 在固定样本窗口（建议 2024-01）中，特征构建相关耗时有可记录的下降，并在 validation 中给出命令和结果。

## Reproduction Steps (BUG required)
- precondition: _N/A_
- steps: _N/A_
- expected: _N/A_
- actual: _N/A_

## Risks
- 过度合并特征可能引入不必要列，导致内存峰值上升。
- 若列选择/命名处理不严谨，可能影响 trace 中字段完整性。
- 若行为等价验证不足，可能出现“性能提升但语义漂移”的隐患。

## Open Questions
- Q-001 [Resolved]: 是否允许引入轻量缓存（按 timeframe + indicator_plan hash）作为共享机制的一部分？  
  A: 允许，只要不改变外部接口与策略语义。

## Discussion Log
- `2026-04-04`: workshop created.
- `2026-04-04`: 明确优化目标为“减少重复特征构建”，优先在 `ProfileActionStrategy` 内收敛实现。
- `2026-04-04`: 约束确认为“语义不变 + 追溯不降级 + 性能可量化”。

## Quality Gate Checklist
- [x] Structure complete
- [x] No semantic ambiguity
- [x] No conflicts (scope/constraints/acceptance)
- [x] No unclear descriptions
- [x] Open questions resolved

## Promotion Decision
- decision: `approved` # pending | approved | deferred | rejected
- linked_task_id: `XTR-SP-016`
- approved_by: `tiger`
- approved_at: `2026-04-04`
- note: `同意进入任务开发流程，先创建 task 并补齐 spec/validation。`
