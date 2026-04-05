# Signal V1 派生特征指标族扩展 (XTR-SP-014)

## Intent
`XTR-SP-013` 已落地 Signal V1 最小闭环，但部分策略条件仍以近似方式表达。经讨论确认，本任务不走“扩 DSL 原语”路线，改为“上游新增指标族并预计算特征列”，让 profile 只使用现有比较运算（`>/<===/!=/between/in_set/cross_*`）完成条件判定，降低表达式复杂度与维护成本。

## Requirement
功能目标：
- REQ-001：新增 `macd_state` 指标族（feature-engine），输出可直接比较的派生列，至少包括：
  - `state_code_num`（数值编码）
  - `near_golden_flag`、`near_dead_flag`
  - `reject_long_flag`、`reject_short_flag`
  - `gap`、`gap_slope`、`gap_pct`
  - `green_narrow_2_flag`、`red_narrow_2_flag`（连续收窄预计算）
- REQ-002：新增 `support_proximity` 指标族（feature-engine），输出可直接比较的派生列，至少包括：
  - `support_distance_pct`、`resistance_distance_pct`
  - `support_strength_code`、`resistance_strength_code`（`none=0/weak=1/medium=2/strong=3`）
  - `nearest_support_level`、`nearest_resistance_level`
- REQ-003：profile 侧仅使用现有运算符做比较/集合判断，不新增 `tf_points_score_v1` 原语。
- REQ-004：新指标族可进入 profile required refs、decision trace 与 viewer 证据链，且旧 profile 兼容不破坏。

非目标 / 范围外：
- action/risk 机制升级（本任务不调整风控与执行状态机）。
- 外部事件/账户上下文条件（重大数据、连亏保护）接入。
- 新 profile 的参数优化与收益目标调优（仅保证语义可表达）。

输入输出或接口：
- 输入：OHLCV bars + `indicator_plan_by_tf`（包含新 family）+ profile 配置。
- 输出：预计算特征列（数值型）供 profile 直接比较，并在 trace/viewer 可追溯。
- 兼容：旧 profile（不使用新 family）行为不变；DSL 原语集合不变。

## Design
核心思路与架构：
- D1. Feature-first 路线
  - 在 feature-engine 新增 `macd_state`、`support_proximity` 两个 indicator family。
  - 所有复杂序列/结构逻辑在 indicator 内计算为数值列，profile 侧只做简单布尔对比。
- D2. Profile 不扩语法
  - `tf_points_score_v1` 仍使用当前原语集合与 precompile 规则。
  - 通过 `in_set/eq/gt/lt` 消费派生列（如 `*_flag`、`*_code`、`*_pct`）。
- D3. 证据链一致
  - `condition_results/condition_hits/rule_traces` 继续作为判定证据。
  - `macd_state` 证据从 runtime passthrough 扩展为支持新列映射展示（保持缺字段降级）。

数据/接口/模型：
- `macd_state` family：
  - 输入：`close`（内部计算 EMA12/EMA26/DEA/hist）。
  - 输出：上述 REQ-001 列，默认阈值参数可配置（`near_gap_pct`、`near_gap_abs`、`slope_min`、`narrow_bars`）。
  - 设计约束：优先输出数值列，避免跨周期对齐时字符串 dtype 问题。
- `support_proximity` family：
  - 输入：`high/low/close` + EMA levels。
  - level 集：EMA7/20/60/200 + `prev_high_lookback20` + `prev_low_lookback20` + round number。
  - 分级阈值：`<=0.3% strong`、`<=0.8% medium`、`<=1.5% weak`、其他 `none`。
- trace/viewer：
  - `macd_state` 展示优先读新列；若不存在则回退旧列/N/A。

风险与权衡：
- 新指标族会增加 feature 计算耗时，需要基准回归。
- 阈值对命中敏感，需保留参数化并在回测中校准。
- 为保证兼容，禁止更改旧字段语义；仅新增列与可选展示。

实施分步（推荐）：
- Phase 1：新增 `macd_state` family + 单测。
- Phase 2：新增 `support_proximity` family + 单测。
- Phase 3：profile strict 版替换近似条件（仅比较表达）+ precompile 回归。
- Phase 4：trace/viewer 适配与全链路回归。

## Acceptance
- ACC-001（REQ-001）：`macd_state` family 输出字段完整，且连续收窄/即将金叉死叉可由 flags 直接消费。
- ACC-002（REQ-002）：`support_proximity` family 输出接近度与强度编码，分级规则与阈值一致。
- ACC-003（REQ-003）：strict profile 在不新增 DSL 原语前提下，可表达目标条件并 precompile 通过。
- ACC-004（REQ-004）：trace/viewer 可显示新增证据字段；字段缺失时可降级显示。
- ACC-005（REQ-004）：旧 profile 回归通过，行为不退化。

## Notes
- Workshop：`docs/03-delivery/workshops/items/XTR-WS-004.md`
- 相关任务：`docs/03-delivery/specs/XTR-SP-013.md`（已收口）
- 讨论来源：
  - `docs/02-strategy/discussions/AI_strategy_logic.md`
  - `docs/02-strategy/discussions/AI_strategy_feasibility_analysis.md`
- 本任务采用“feature-first，不扩 DSL 原语”默认决策。
