# 信号决策回溯 (XTR-WS-002)

- workshop_id: `XTR-WS-002`
- type: `requirement` # requirement | task | bug
- status: `approved` # draft | discussing | review | approved | deferred | rejected
- created_at: `2026-04-02`
- updated_at: `2026-04-02`
- owner: `tiger + codex`
- related_task_ids: `["XTR-SP-012"]`
- source: `用户指令：开启需求研讨流程：信号决策回溯（2026-04-02）`

## Background
- 当前底层运行框架已基本固定，策略逻辑统一通过 `StrategyProfile` 实现。
- 主链路执行顺序已固定：`FeaturePipeline -> RegimeScoringEngine -> SignalEngine -> RiskEngine -> Action Output`。
- 现有产物虽可查看结果，但缺少从 `Feature` 到 `score_total/state` 再到最终 `action` 的完整决策证据链。
- 信号决策回溯是策略调试与优化的核心基础能力，不应因“范围裁剪”而缺失关键证据。

## Goal / Problem Statement
- 建立完整、可复现的“信号决策回溯”能力，支持从单条动作反查：
  - Feature 值
  - 评分规则结果
  - 分组聚合与权重结果
  - `score_total/state`
  - SignalEngine 命中与过滤过程
  - RiskEngine 处理结果与最终动作
- 覆盖 `ENTER/EXIT/HOLD` 全部动作类型，作为信号有效性与准确性判定的统一依据。
- 固化统一证据结构，为回测调试与未来实盘排障提供一致数据保障。

## Scope In
- 定义并冻结信号决策回溯契约（主键、输出字段、错误语义）。
- 记录完整证据链：`Feature -> Rule -> Group -> score_total/state -> Signal -> Risk -> Final Action`。
- `ENTER/EXIT/HOLD` 全量记录，不做动作类型裁剪。
- 提供统一可视化回溯入口（report viewer 联动 + decision trace 独立查询页）与固定验证样例。
- `report viewer` 与 `decision_trace_viewer.html` 同目录放置，支持页面内跳转与手动独立打开两种使用方式。
- 明确回测与未来实盘的口径一致性要求（同一 schema、同类字段语义）。

## Scope Out
- 不在本需求内新增评分函数、信号规则或风险模型。
- 不在本需求内改造实盘 OMS/EMS。
- 不在本需求内引入在线服务或数据库。

## Constraints
- 必须兼容当前 profile 主链路，且不改变现有交易语义。
- 决策证据链属于核心基础能力，关键字段不得因实施范围而删减。
- 需兼顾可追溯性与产物体积/性能成本，避免不可控膨胀。
- 只要发生策略运行，就必须生成决策回溯数据；不同运行上下文仅目录位置不同，字段 schema 必须同构。
- 需求进入开发前，必须先完成 workshop ready 守门与任务资产创建。

## Requirement Summary
- REQ-001: 必须记录 Feature 层证据（含全量指标/特征值 `feature_values_json`，以及参与决策子集 `required_feature_values_json` 与 `required_feature_refs_json`）。
- REQ-002: 必须记录评分层证据（rule 结果、group 聚合、group 权重、`score_total`、`state`）。
- REQ-003: 必须记录信号层证据（候选规则命中、过滤原因、最终动作选择逻辑）。
- REQ-004: 必须记录风险层证据（是否拦截/改写动作，`size/stop_loss/take_profit` 结果）。
- REQ-005: 必须覆盖 `ENTER/EXIT/HOLD` 三类动作的回溯信息，不允许仅覆盖进场信号。
- REQ-006: 必须提供固定可视化查询入口，支持按唯一键定位单条决策并输出完整证据链；首版采用“双页面协同”：在现有 report viewer 支持点击交易记录查看对应进/出场决策链，同时提供 `decision_trace.parquet` 独立 HTML 查询页面。两个页面同目录放置，report viewer 顶部提供跳转按钮，且两个页面支持手动独立打开。
- REQ-007: 对相同输入重复回溯，输出结构与关键字段语义保持一致。

## Acceptance Criteria
- ACC-001 (REQ-001): 回溯结果可查看全量 Feature 值（`feature_values_json`）与参与决策子集（`required_feature_values_json`），且子集字段可定位到具体 `ref`（`required_feature_refs_json`）。
- ACC-002 (REQ-002): 回溯结果完整呈现 `rule -> group -> score_total/state` 计算链路。
- ACC-003 (REQ-003): 回溯结果可明确区分“命中”“被过滤”“未命中”并给出原因。
- ACC-004 (REQ-004): 回溯结果可判断风险层是否拦截或改写动作及参数。
- ACC-005 (REQ-005): 在固定样例中，`ENTER/EXIT/HOLD` 均可获得可解析回溯记录。
- ACC-006 (REQ-006): 通过唯一键可返回唯一记录或结构化“未命中”错误；report viewer 可从交易记录联动到对应进/出场决策链，独立 HTML 查询页可直接查询并完整展示该条证据链；两个页面同目录部署，支持顶部按钮跳转与手动独立打开。
- ACC-007 (REQ-007): 同一输入重复执行回溯，字段结构一致、关键值语义一致。

## Reproduction Steps (BUG required)
- precondition: _N/A_
- steps: _N/A_
- expected: _N/A_
- actual: _N/A_

## Risks
- 证据链记录完整后，产物体积与读写开销可能显著上升。
- 若唯一键设计不充分，可能出现一键多记录或定位歧义。
- 若回测与未来实盘口径未冻结一致，后续会产生解释漂移。
- 若字段命名与语义未标准化，会增加调试认知成本。

## Open Questions
- Q-001 [Resolved]: 决策证据链为核心基础能力，首版不允许裁剪 `Feature -> Rule -> Group -> score_total/state -> Signal -> Risk -> Final Action` 主链路证据。
- Q-002 [Resolved]: 回溯必须覆盖 `ENTER/EXIT/HOLD` 全动作类型，不仅限于进场信号。
- Q-003 [Resolved]: 唯一定位键采用既有字段 `run_id + symbol + timestamp + action`，首版不引入独立 `decision_id`。
- Q-004 [Resolved]: 决策回溯为运行必备产物；策略研究回测落 `reports/...`，Runtime 编排落 `runs/...`，两侧 schema 保持同构，不做“只支持其一”的裁剪。
- Q-005 [Resolved]: 首版查询形态冻结为可视化双入口：report viewer 内联交易-决策联动 + `decision_trace.parquet` 独立 HTML 查询页；首版不要求新增 CLI 查询命令。
- Q-006 [Resolved]: Feature 回溯字段需同时保留全量与子集：`feature_values_json`（全量）+ `required_feature_values_json`（参与决策子集）+ `required_feature_refs_json`（子集 ref 清单）。
- Q-007 [Resolved]: `report viewer` 与 `decision_trace_viewer.html` 同目录放置；在 report viewer 顶部提供跳转按钮，同时允许两个页面手动独立打开。

## Discussion Log
- `2026-04-02`: workshop created.
- `2026-04-02`: 根据用户“信号决策回溯”需求回填初稿，进入 discussing，等待关键决策确认。
- `2026-04-02`: 用户补充确认“信号决策回溯”为策略调试和优化核心基础，要求完整记录 `Feature -> Score -> Signal -> Risk -> Action` 决策证据链，并覆盖 `ENTER/EXIT/HOLD`。
- `2026-04-02`: 用户确认回溯唯一键采用 `run_id + symbol + timestamp + action`（复用既有数据，便于追溯）。
- `2026-04-02`: 用户确认决策回溯为运行必备产物，不按 `reports/runs` 二选一裁剪；按运行上下文落盘到对应目录并保持同构 schema。
- `2026-04-02`: 用户确认 Feature 回溯需同时保留全量值与参与决策子集，新增字段组合：`feature_values_json` + `required_feature_values_json` + `required_feature_refs_json`。
- `2026-04-02`: 用户确认查询工具采用可视化双入口：report viewer 支持“点击交易记录查看对应进/出场决策链”；`decision_trace.parquet` 另做独立 HTML 查询页面，并复用现有 report viewer 的 parquet 读取方式。
- `2026-04-02`: 用户确认页面组织与入口：report viewer 与 `decision_trace_viewer.html` 同目录放置；report viewer 顶部增加跳转按钮；两个页面也可手动独立打开。

## Quality Gate Checklist
- [x] Structure complete
- [x] No semantic ambiguity
- [x] No conflicts (scope/constraints/acceptance)
- [x] No unclear descriptions
- [x] Open questions resolved

## Promotion Decision
- decision: `approved` # pending | approved | deferred | rejected
- linked_task_id: `XTR-SP-012`
- approved_by: `tiger`
- approved_at: `2026-04-02`
- note: `研讨完成，进入任务资产创建阶段。`
