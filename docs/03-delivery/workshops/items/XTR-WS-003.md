# Signal V1 最小实现范围实现 (XTR-WS-003)

- workshop_id: `XTR-WS-003`
- type: `requirement` # requirement | task | bug
- status: `approved` # draft | discussing | review | approved | deferred | rejected
- created_at: `2026-04-04`
- updated_at: `2026-04-04`
- owner: `tiger`
- related_task_ids: `["XTR-SP-013"]`
- source: `docs/02-strategy/discussions/AI_strategy_logic.md + docs/02-strategy/discussions/AI_strategy_feasibility_analysis.md`

## Background
当前已完成对 `AI_strategy_logic.md` 第 5 节信号条件的逐条拆解，形成了 `condition_id` 真值表，并明确了 Signal V1 的实施边界：仅实现基础指标信号链路，不进入 action/risk 与外部事件条件。

## Goal / Problem Statement
在现有 `regime/group/rule` 架构上落地 Signal V1 最小实现能力，确保多周期信号条件可以被一致表达、校验与回放，避免手工配置错误与口径漂移。

## Scope In
- Signal V1（不含 action/risk）范围冻结并可执行
- `tf_points_score_v1` 支持 Signal 条件积分与命中输出
- `entry_gate_spec` 支持 `all_of / n_of_m / cross_tf`
- 三组核心衍生条件：支撑阻力接近度、`macd_state`（合并 near + expand/reject）
- decision_trace 输出条件命中与 gate 命中证据

## Scope Out
- action 与 risk 规则联动实现
- 重大数据发布前观望（事件日历接入）
- 连续亏损 2 笔后观望（账户状态接入）
- 分批止盈、移动止损等风控状态机

## Constraints
- 保持现有 `classifier` 机制兼容
- 先实现 Signal 最小闭环，再扩展外部与账户维度
- 条件定义必须可追溯到统一 `condition_id` 映射表
- 所有信号判定需要可在 trace 中复盘

## Requirement Summary
- REQ-001: 提供 Signal V1 可执行语义层，支持多周期条件积分、跨周期门槛与统一条件命中输出。
- REQ-002: 落地 `macd_state` 单次计算结果，统一支撑“即将金叉/死叉”和“放大状态否决”两类条件消费。
- REQ-003: 按原始策略口径落地支撑阻力接近度计算（EMA/前高前低/整数关口 + 0.3/0.8/1.5 百分比分级）。
- REQ-004: 输出可复盘的 decision_trace 字段，覆盖 feature -> condition -> gate -> score 链路。

## Acceptance Criteria
- ACC-001 (REQ-001): `tf_points_score_v1` 与 `entry_gate_spec` 可表达第 5 节信号条件并产出命中结果。
- ACC-002 (REQ-002): `macd_state` 可直接派生 `near_cross` 与 `reject_long/reject_short` 判定，避免重复计算。
- ACC-003 (REQ-003): `cond_structure_near_support` 使用 `signal_strength in {strong, medium}` 判定可复现。
- ACC-004 (REQ-004): decision_trace 包含条件命中、gate 命中、`macd_state` 关键字段与分数链路。

## Reproduction Steps (BUG required)
- precondition: _N/A_
- steps: _N/A_
- expected: _N/A_
- actual: _N/A_

## Risks
- 条件配置量上升后，手工编写易出错
- 多周期对齐口径不一致可能导致回测偏差
- `macd_state` 参数初始值需要后续数据验证与调整

## Open Questions
- Q-001: [Resolved] Signal V1 阶段是否纳入重大数据与连续亏损条件？结论：不纳入，延期到后续阶段。

## Discussion Log
- `2026-04-04`: workshop created.
- `2026-04-04`: 明确 Signal V1 实施边界与 REQ/ACC 映射；确认可进入任务开发流程。

## Quality Gate Checklist
- [x] Structure complete
- [x] No semantic ambiguity
- [x] No conflicts (scope/constraints/acceptance)
- [x] No unclear descriptions
- [x] Open questions resolved

## Promotion Decision
- decision: `approved` # pending | approved | deferred | rejected
- linked_task_id: `XTR-SP-013`
- approved_by: `tiger`
- approved_at: `2026-04-04`
- note: `Signal V1 workshop passed ready gate; task initialized as XTR-SP-013.`
