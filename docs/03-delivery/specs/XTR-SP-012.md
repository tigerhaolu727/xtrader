# 信号决策回溯与可视化查询工具 (XTR-SP-012)

## Intent
- `XTR-WS-002` 已确认“信号决策回溯”为策略调试与优化的核心基础能力，必须覆盖 `ENTER/EXIT/HOLD` 全动作，并完整保留 `Feature -> Rule -> Group -> score_total/state -> Signal -> Risk -> Final Action` 证据链。
- 当前产物中，`diagnostics.json` 仅提供运行级摘要，缺少按单条决策反查完整链路的结构化数据与可视化入口。
- 目标是在不改动既有策略语义的前提下，补齐“可落盘、可定位、可视化可解释”的决策回溯能力，并与现有离线报告链路协同。

## Requirement
### 功能目标
- 产物层：
  - 为每次策略运行输出 `decision_trace.parquet`（回测在 `reports/...`，runtime 在 `runs/...`，schema 同构）。
  - 每条决策一行，全局定位键采用 `run_id + symbol + execution_time + action`（单 run 目录内查询可省略 `run_id`）。
  - 必须同时记录：
    - `feature_values_json`（全量指标/特征值）
    - `required_feature_refs_json`（参与决策 ref 清单）
    - `required_feature_values_json`（参与决策子集值）
    - 评分、信号、风险、最终动作的链路字段。
- 可视化入口层：
  - 扩展现有 `offline_report_viewer.html`：支持“点击交易记录查看对应进/出场决策链”。
  - 新增独立页面 `decision_trace_viewer.html`：用于直接查询 `decision_trace.parquet` 并展示完整证据链。
  - 两个页面放在同一目录；`report viewer` 顶部提供跳转按钮；两个页面也可手动独立打开。
- 查询与可解释层：
  - 独立查询页支持按 `symbol + execution_time + action`（单 run 目录）精确定位；跨 run 聚合场景可追加 `run_id`。
  - 单 run 目录默认单一 symbol，查询页保留 `symbol` 字段但从数据自动读取并填充（无需手工输入）。
  - 支持对未命中返回结构化错误提示；
  - 支持对单条决策以分层可视化方式展示（Feature/Score/Signal/Risk/Final）。

### 非目标 / 范围外
- 不新增评分函数、信号规则或风险模型。
- 不改造 OMS/EMS 或引入在线服务/数据库。
- 首版不要求新增 CLI 查询命令。

### 输入输出 / 接口
- 输入：
  - `ProfileActionStrategy` 执行过程中已有的中间结果（`model_df/scoring_df/signal_df/risk_df`）。
  - 现有回测产物与 viewer 读取机制（`hyparquet`）。
- 输出：
  - 新增 `decision_trace.parquet`（及必要的 chunk manifest）。
  - `offline_report_viewer.html` 联动能力与跳转按钮。
  - 新增 `decision_trace_viewer.html` 独立查询页面。

## Design
### 核心思路与架构
- 采用“数据先行 + 双页面协同”：
  1. 先冻结 `decision_trace.parquet` 行级 schema；
  2. 再用该 schema 驱动两个 UI 页面：
     - `report viewer` 聚焦“交易联动回看”；
     - `decision_trace_viewer` 聚焦“按键查询与深度解释”。
- `diagnostics.json` 保持运行摘要定位，不承载单条决策明细。

### 数据/接口/模型
- `decision_trace.parquet` 建议字段（首版）：
  - 基础定位：`run_id, symbol, signal_time, execution_time, action, reason, state, score_total`
  - Feature 证据：
    - `feature_values_json`
    - `required_feature_refs_json`
    - `required_feature_values_json`
  - 评分证据：
    - `rule_results_json`
    - `group_scores_json`
    - `group_weights_json`
  - 信号/风险证据：
    - `signal_decision_json`
    - `risk_decision_json`
  - 结果证据：
    - `action_result_json`
- 存储策略：
  - JSON 复杂结构首版以字符串列持久化，降低浏览器端与 parquet 解析兼容风险。
  - 与现有 `signal_execution.parquet` 使用同类分块机制，支持大数据量按时间窗口读取。
- 前端展示约束（针对 `*_json` 字符串列）：
  - 读取时默认执行 `JSON.parse`；解析失败时降级为“原文展示 + 解析错误提示”，不得阻断页面其他模块渲染。
  - 默认展示形态为结构化视图（分层卡片/键值），并提供“查看原始 JSON”切换入口。
  - 大对象默认折叠首层，按需展开；时间统一 UTC 展示，关键数值采用统一格式化规则。
- 页面协同：
  - `report viewer` 点击交易行时，按交易 `entry_time/exit_time` 对齐 `decision_trace.execution_time`，并按动作映射（`ENTER`/`EXIT`）展示对应记录摘要。
  - 交易决策链摘要以弹窗（popup/modal）方式展示，支持主动关闭，避免长期占据主页面布局区域。
  - 顶部按钮跳转到 `decision_trace_viewer.html`，并可通过 URL 参数携带 `symbol/execution_time/action`（同 run 目录内查询可省略 `run_id`；跨 run 聚合场景保留 `run_id` 作为全局定位字段）。
  - 在 `report viewer` 弹窗内点击“在独立页面查看完整决策链”时，应将当前已选记录上下文（`symbol/execution_time/action` 与候选明细）直接 handoff 给 `decision_trace_viewer`，避免二次选择 run 目录导致误选。
  - `decision_trace_viewer` 可在无跳转参数时独立加载并手动查询。

### 页面与交互规范
- `decision_trace_viewer.html` 页面布局（首版固定）：
  - 顶部查询区：`Run目录选择`、`symbol`（自动填充）、`execution_time`、`action`、`查询`、`清空`。
  - 中部结果区：左侧“候选记录列表”（按 `execution_time` 倒序），右侧“单条决策详情”。
  - 底部状态区：显示加载状态、命中数、未命中提示、解析告警。
- 详情区块顺序（首版固定）：
  1. 基本信息（`symbol/execution_time/action/state/score_total/reason`）
  2. Feature 全量（`feature_values_json`）
  3. Feature 子集（`required_feature_refs_json` + `required_feature_values_json`）
  4. 评分链（`rule_results_json` + `group_scores_json` + `group_weights_json`）
  5. 信号链（`signal_decision_json`）
  6. 风险链（`risk_decision_json`）
  7. 最终结果（`action_result_json`）
- 查询与反馈细节：
  - 查询键：单 run 目录默认 `symbol + execution_time + action`；若 `action` 缺省，返回候选列表并提示用户选择动作后再精确定位。
  - 未命中：显示结构化未命中信息（含当前查询键）。
  - 多命中：显示“多命中告警 + 候选列表（时间/动作/reason）”。
  - JSON 解析失败：仅当前区块降级为原文展示，不影响其它区块渲染。

### Trade Ledger 可检索优化（v1）
- 在 `offline_report_viewer` 的 `Trade Ledger` 区域增加轻量检索工具条，支持：
  - 关键词过滤（时间/方向）
  - 方向过滤（全部/LONG/SHORT）
  - PnL 过滤（全部/盈利/亏损 + 最小/最大值）
  - 开仓时间范围过滤（起始/结束 UTC）
  - 排序切换（开仓时间、新旧；净收益、高低）
  - 页码跳转与时间定位（定位到最接近交易）
  - 时间定位支持“最大偏差(分钟)”阈值；当最近交易超出阈值时给出结构化提示，不执行错误聚焦。
  - 时间相关输入（起始时间/结束时间/时间定位）采用 `datetime picker`（`datetime-local`），固定输入格式，避免手动文本格式差异导致匹配失败。
  - 工具条布局按“Label + Control 同组”渲染，保证跨屏换行时标签与控件不分离错位。
- 联动约束：
  - 仅增强表格检索，不改动既有“点击交易 -> K线/资金曲线/时间线聚焦”主链路。
  - 若筛选导致当前已选交易不在结果集中，自动回退到 `global` 模式并清理聚焦态，避免联动歧义。

### 风险与权衡
- 风险 1：全量特征入 trace 后文件体积增长。
  - 处理：使用 parquet + chunk，UI 默认按键定位与窗口加载，不做全量一次性渲染。
- 风险 2：交易记录与决策记录映射歧义。
  - 处理：全局定位键采用 `run_id + symbol + execution_time + action`（run 内查询可省略 `run_id`），联动时显示命中条数与歧义提示。
- 风险 3：复杂 JSON 列在前端解析不稳定。
  - 处理：首版统一采用 JSON 字符串列并在前端显式 `JSON.parse` + 错误保护。

## Acceptance
- 数据产物：
  - 策略运行后必定产生 `decision_trace.parquet`；
  - 单条记录可完整还原 `Feature -> Rule -> Group -> score_total/state -> Signal -> Risk -> Final Action`。
- 联动能力：
  - `report viewer` 点击交易记录可通过 popup 查看对应进/出场决策链摘要，并可关闭 popup；
  - 页面顶部存在跳转按钮，可打开 `decision_trace_viewer.html`。
  - 在 popup 中点击“在独立页面查看完整决策链”时，`decision_trace_viewer` 可直接加载当前记录上下文，无需重复选择 run 目录。
- Ledger 可检索：
  - `Trade Ledger` 支持关键词/方向/PnL/时间范围/排序筛选、页码跳转与时间定位；
  - 筛选后点击交易记录仍可保持与 K 线、资金曲线、时间线的联动聚焦行为。
- 独立查询能力：
  - `decision_trace_viewer.html` 可单独打开并查询 `decision_trace.parquet`；
  - 在单 run 目录场景下，`symbol` 可自动从数据读取并填充；
  - 按主键命中时展示完整链路，详情区块顺序与设计定义一致；
  - 未命中返回结构化错误信息，多命中返回候选列表与告警提示；
  - 当 `action` 未指定时，系统可返回候选并支持二次精确定位。
- 一致性：
  - `reports/...` 与 `runs/...` 的 `decision_trace` schema 同构；
  - `ENTER/EXIT/HOLD` 三类动作均有可解析回溯记录。
- 流程：
  - `python scripts/task_guard.py check XTR-SP-012` 通过；
  - 实施后验证记录写入 `docs/03-delivery/validation/XTR-SP-012.md`。

## Notes
- 需求来源：`docs/03-delivery/workshops/items/XTR-WS-002.md`
- 相关实现参考：
  - `src/xtrader/strategies/builtin_strategies/profile_action.py`
  - `src/xtrader/backtests/event_driven.py`
  - `src/xtrader/backtests/assets/offline_report_viewer.html`
