# Signal V1 原语与派生特征扩展 (XTR-WS-004)

- workshop_id: `XTR-WS-004`
- type: `requirement` # requirement | task | bug
- status: `approved` # draft | discussing | review | approved | deferred | rejected
- created_at: `2026-04-04`
- updated_at: `2026-04-04`
- owner: `tiger`
- related_task_ids: `["XTR-SP-014"]`
- source: `docs/02-strategy/discussions/AI_strategy_logic.md + docs/02-strategy/discussions/AI_strategy_feasibility_analysis.md + XTR-SP-013`

## Background
`XTR-SP-013` 已完成 Signal V1 最小闭环，但部分条件仍使用“可运行近似”（如 MACD 柱体连续收窄、即将金叉/死叉、支撑阻力接近度）。当前需要在保持现有框架兼容前提下，补齐原语与派生特征，使 profile 可按策略定义直接表达这些条件。

## Goal / Problem Statement
补齐 `tf_points_score_v1` 的关键表达能力与派生特征口径，消除近似逻辑，使 Signal 条件可“按定义配置、按定义回放、按定义追溯”。

## Scope In
- 新增 `macd_state` 指标族（上游预计算派生列）支持 near/reject/narrow 等条件直接比较消费。
- 新增 `support_proximity` 指标族（上游预计算接近度与强度分级）支持支撑阻力条件直接比较消费。
- profile 侧仅使用现有比较运算符与 `in_set`，不扩展 DSL 原语集合。
- 补充 indicator/trace/viewer 回归与 validation 证据。

## Scope Out
- 不改 action/risk 行为与规则优先级机制。
- 不接入重大数据窗口、连续亏损等外部/账户上下文条件。
- 不在本任务引入新的执行器（仅扩展现有 profile 语义能力）。

## Constraints
- 与现有 `xtrader.strategy_profile.v0.3` 配置保持向后兼容（旧 profile 不受影响）。
- 新增原语必须经过 precompile 守门，非法表达式 fail-fast。
- decision_trace 需保持可追溯，新增字段缺失时仍可降级展示。
- 先完成 Signal 语义能力，不跨到风控状态机扩展。

## Requirement Summary
- REQ-001: 扩展 `tf_points_score_v1` 表达式原语，支持连续收窄与近交叉条件按配置直接表达。
- REQ-002: 增加 MACD 状态派生特征计算与输出约定，统一近交叉与放大/否决判定消费口径。
- REQ-003: 增加支撑阻力接近度派生特征最小实现，支持 `signal_strength` 分级判定。
- REQ-004: 更新 schema/precompile/validation，确保新原语与派生特征可校验、可回放、可追溯。

## Acceptance Criteria
- ACC-001 (REQ-001): `tf_points_score_v1` 可用配置表达 `MACD 绿/红柱连续收窄(>=2)`，并在 runtime 正确命中。
- ACC-002 (REQ-001): `near_cross_up/down` 在给定阈值参数下可一致复现“即将金叉/死叉”判定。
- ACC-003 (REQ-002): `macd_state` 至少输出 `state_code/near_cross/reject_long/reject_short/meta.gap/meta.gap_slope/meta.gap_pct`。
- ACC-004 (REQ-003): 支撑阻力接近度可输出 `distance_pct` 与 `signal_strength`，且支持 `strong/medium/weak/none` 分级。
- ACC-005 (REQ-004): 新增原语/派生特征具备 schema + precompile + runtime + trace + viewer 的验证证据链。

## Reproduction Steps (BUG required)
- precondition: _N/A_
- steps: _N/A_
- expected: _N/A_
- actual: _N/A_

## Risks
- 原语增多后表达式复杂度上升，配置出错概率增加。
- 近交叉与接近度阈值存在参数敏感性，需后续回测校准。
- 若派生特征字段命名不统一，可能导致 trace 与 viewer 展示偏差。

## Open Questions
- Q-001: [Resolved] 支撑阻力最小实现是否必须包含“前高前低+整数关口”？结论：v1 包含，允许先以固定 lookback（20）实现。
- Q-002: [Resolved] 近交叉判定采用绝对阈值还是百分比阈值？结论：两者都支持，默认优先 `gap_pct`。
- Q-003: [Resolved] 新能力是否并入 `XTR-SP-013`？结论：拆分新任务 `XTR-SP-014`，避免影响已收口任务稳定性。

## Discussion Log
- `2026-04-04`: workshop created.
- `2026-04-04`: 明确“先 Spec/Validation，再编码”约束；冻结独立任务范围。
- `2026-04-04`: 根据用户确认，技术路线调整为“feature-first（新增指标族预计算）”，不新增 DSL 原语。

## Quality Gate Checklist
- [x] Structure complete
- [x] No semantic ambiguity
- [x] No conflicts (scope/constraints/acceptance)
- [x] No unclear descriptions
- [x] Open questions resolved

## Promotion Decision
- decision: `approved` # pending | approved | deferred | rejected
- linked_task_id: `XTR-SP-014`
- approved_by: `tiger`
- approved_at: `2026-04-04`
- note: `按用户要求，原语/派生特征扩展必须走独立 spec/validation 流程后再开发。`
