# Signal V1 最小实现范围落地 (XTR-SP-013)

## Intent
基于 `XTR-WS-003` 与 `AI_strategy_feasibility_analysis.md` 的冻结结论，落地 Signal V1 最小可执行能力（不含 action/risk），将第 5 节信号条件转化为可计算、可校验、可回放的规则链路。

## Requirement
功能目标：
- 完成多周期（`4H/1H/15M/5M`）Signal 判定最小闭环：条件积分 + 门槛聚合 + 分数输出。
- 落地三组核心衍生条件：
  - 支撑阻力接近度（EMA/前高前低/整数关口 + 百分比分级）。
  - `macd_state`（合并“即将金叉/死叉”与“放大状态否决”）。
  - 跨周期条件聚合（如 `价格 > EMA60（至少1个周期）`）。
- 在表达式层扩展 `eq/neq/in_set`，支持直接判定离散状态（如 `macd_state_code`）。
- 决策回溯查看器适配：在 `decision_trace_viewer.html` 与 `offline_report_viewer.html` 中增加 Signal V1 证据链展示能力，覆盖 `condition_hits / gate_results / score_adjustment / macd_state`。

范围外：
- Action 与 Risk 引擎联动策略。
- 重大数据窗口过滤、连续亏损保护等外部/账户维度条件。
- 分批止盈、移动止损等风控状态机。

输入输出/接口：
- 输入：`model_df` 多周期特征、profile 中 `regime_spec`/`signal_spec`。
- 输出：`state`、`rule_scores`、`group_scores`、`score_total`、gate 命中结果、trace 诊断字段。

## Design
核心思路：
- 维持 `Rule -> Group -> Regime -> Signal` 主链路。
- `tf_points_score_v1` 继续作为积分引擎，新增离散表达能力（`eq/neq/in_set`）。
- 通过一次 `macd_state` 计算派生 near-cross 与 reject 条件，避免重复判断。

数据与模型：
- 条件映射基线：`docs/02-strategy/discussions/AI_strategy_feasibility_analysis.md` 第 27 节真值表。
- 支撑阻力口径：同文档第 25.3 节（已按原始策略函数更新）。
- `macd_state` 口径：同文档第 31 节（统一状态码输出）。

实现切片（Signal-only）：
- Schema/Model：支持表达式 `eq/neq/in_set` 与必要参数校验。
- Precompile：校验 `in_set` 集合合法性、类型兼容性、条件引用闭环。
- Runtime：表达式执行器支持离散比较；`macd_state` 与 proximity 特征可消费。
- Trace：记录条件命中、gate 命中、`macd_state` 核心字段与得分链路。
- Viewer：在不破坏现有离线回测产物结构的前提下，新增 Signal V1 证据链展示分区与摘要，优先复用现有 JSON 字段承载信息。

风险与权衡：
- 增加离散原语可提升表达力，但需严格 precompile 守门避免配置歧义。
- `macd_state` 统一后逻辑更一致，但参数（如 `near_pct/slope_min`）仍需后续回测校准。

## Default Decisions
本节为当前任务已确认的默认实现约束，后续编码与验收按此执行：

1. 字段落位：
   - Signal V1 证据链优先落入现有 JSON 容器（`rule_results` / `signal_decision`），不强制新增 decision_trace 顶层列。
2. `condition_hits` 结构：
   - 同时提供“命中列表 + 全量结果”两类信息（建议键：`hits` + `results`）。
3. `gate_results` 结构：
   - 统一输出键：`gate_id`、`mode`、`min_hit`、`hit_count`、`hit_keys`、`miss_keys`、`passed`。
4. `score_adjustment` 粒度：
   - 至少包含 `score_base`、`score_adjustment`、`score_final`，并带 `fn`/`params`。
5. `macd_state` 最小展示字段：
   - `state_code`、`near_cross`、`reject_long`、`reject_short`、`meta.gap`、`meta.gap_slope`、`meta.gap_pct`。
6. `offline_report_viewer` 展示深度：
   - 交易决策弹窗显示摘要；完整结构通过“在独立页面查看完整决策链”进入 `decision_trace_viewer`。
7. 缺字段降级策略：
   - 字段缺失时保留证据链区块，展示 `N/A`/空值，不中断查询与跳转流程。
8. 本任务边界：
   - 本任务包含 viewer 展示适配；Signal 计算与 trace 生产逻辑按主开发切片推进，不在 viewer 侧做业务推断补算。

## Implementation Checklist
- [ ] C1. 在 scoring/trace 输出中按约定落位四项证据链信息：`condition_hits / gate_results / score_adjustment / macd_state`（优先落入 `rule_results` / `signal_decision`）。
- [ ] C2. `condition_hits` 输出结构包含 `hits` 与 `results` 两部分，并可被 viewer 直接读取展示。
- [ ] C3. `gate_results` 输出结构包含 `gate_id/mode/min_hit/hit_count/hit_keys/miss_keys/passed`。
- [ ] C4. `score_adjustment` 输出结构包含 `score_base/score_adjustment/score_final` 与 `fn/params`。
- [ ] C5. `macd_state` 至少输出：`state_code/near_cross/reject_long/reject_short/meta.gap/meta.gap_slope/meta.gap_pct`。
- [ ] C6. `decision_trace_viewer.html` 新增“Signal V1 证据链”展示区块，集中展示四项核心证据。
- [ ] C7. `offline_report_viewer.html` 交易决策弹窗增加四项摘要展示，并保持跳转到 `decision_trace_viewer` 的完整链路可用。
- [ ] C8. 缺字段时两类 viewer 均执行降级展示（`N/A`/空值），不抛错、不影响查询和跳转。
- [ ] C9. 回归确认：现有 decision trace 基础展示（Feature/评分链/信号链/风险链/最终结果）不退化。

## Acceptance
- ACC-001：Signal 规则可表达第 5 节对应的 29 条条件映射（以真值表为准）。
- ACC-002：`macd_state` 一次计算可同时支撑 near-cross 与 reject 判定条件消费。
- ACC-003：`cond_structure_near_support` 可按 `strong/medium/weak/none` 分级驱动命中。
- ACC-004：`eq/neq/in_set` 可通过 schema/precompile/runtime 全链路校验与执行。
- ACC-005：decision_trace 能复盘 `feature -> condition -> gate -> score_total` 关键证据链。
- ACC-006：离线查看器可展示 Signal V1 证据链关键项（`condition_hits / gate_results / score_adjustment / macd_state`），并保持现有查询与跳转链路可用。

## Notes
- Workshop: `docs/03-delivery/workshops/items/XTR-WS-003.md`
- 讨论主文档：`docs/02-strategy/discussions/AI_strategy_feasibility_analysis.md`
- 关键参考章节：25.3、27、31、33
- Viewer 资产：`src/xtrader/backtests/assets/decision_trace_viewer.html`、`src/xtrader/backtests/assets/offline_report_viewer.html`
