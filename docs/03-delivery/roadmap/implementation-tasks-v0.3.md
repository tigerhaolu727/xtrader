# FiveMinRegimeMomentumStrategy v0.3 Implementation Tasks

## 0. 说明
- 目标：把 v0.3 大需求拆成可执行、可验收、可追踪的实现任务。
- 命名：统一使用 `XTR-SP-XXX`。
- 排序：按依赖顺序排列，默认前置任务完成后再进入后续任务。
- 本文只定义 implementation tasks，不替代需求主文档中的 FROZEN 条款。
- 统一执行流程见：
  - `docs/05-agent/processes/task_development_process.md`（流程名：`任务开发流程`）。

## 1. 任务总览（依赖顺序）

### XTR-SP-001 StrategyProfile Schema 冻结
- 目标：将 `RegimeSpec/SignalSpec/RiskSpec` 的 v0.3 结构固化为正式 schema 与字段契约。
- 范围：
  - 固化枚举、必填字段、边界规则、`additionalProperties=false`。
  - 将当前需求文档中的 schema 草案沉淀为可校验资产。
- 交付物：
  - `schemas/` 下正式 `.schema.json`（或项目约定目录）。
  - schema 校验入口（precompile 使用）。
- 验收：
  - `configs/strategy-profiles/five_min_regime_momentum/v0.3.json` 校验通过。
  - 错误配置可返回稳定错误码（最小集）。
- 依赖：无。

### XTR-SP-002 Precompile 编译层（Profile）
- 目标：在编译期把“配置可执行性”问题提前阻断。
- 范围：
  - `input_refs` 依赖收集与 `feature_catalog` 映射。
  - `score_fn` 签名/参数白名单/arity 校验。
  - `reason_code_map` 全覆盖校验。
  - `score_range` 区间重叠、覆盖与冲突校验。
  - classifier `inputs` 与 `conditions[].ref` 集合一致性校验。
- 交付物：
  - precompile 报告扩展字段（规则绑定、错误定位、建议）。
- 验收：
  - 正常 profile 编译成功。
  - 构造错误样例能触发对应 FROZEN 错误码。
- 依赖：`XTR-SP-001`。

### XTR-SP-003 FeaturePipeline 依赖驱动扩展
- 目标：根据 profile 编译结果，按需计算指标，不手写策略依赖。
- 范围：
  - 从 `required_indicator_plan_by_tf` 驱动指标计算。
  - 支持 `decision_timeframe` 与多周期对齐输入准备。
  - 纳入 `atr_pct_rank` 等 v0.3 必需指标。
- 交付物：
  - FeaturePipeline 对 profile 编译产物的接入能力。
- 验收：
  - profile 声明的全部 `input_refs` 在运行期可被解析并取值。
- 依赖：`XTR-SP-002`。

### XTR-SP-004 RegimeScoringEngine 实现
- 目标：落地 `Rule -> Group -> Regime -> ScoreSynthesizer` 固定链路。
- 范围：
  - RuleEngine：调用内置 `score_fn` 输出 `rule_score`。
  - GroupAggregator：按 `rule_weights` 聚合 `group_score`。
  - RegimeEngine：执行 classifier 得到 `state`。
  - ScoreSynthesizer：按 `state_group_weights` 合成 `score_total`。
- 交付物：
  - `state`, `group_scores`, `group_weights`, `score_total` 标准输出。
- 验收：
  - 对给定样本输入，结果可复现且满足 `[-1,1]` 约束。
- 依赖：`XTR-SP-003`。

### XTR-SP-005 SignalEngine（conditions 版）
- 目标：按 `SignalSpec` 规则从 `score_total/state` 生成唯一动作。
- 范围：
  - `score_range` 命中判定（含边界开闭）。
  - `state_allow/state_deny` 判定逻辑。
  - `priority_rank` 冲突消解（全局唯一优先级）。
  - `cooldown_bars + cooldown_scope` 执行。
  - `reason_code_map` 输出绑定。
- 交付物：
  - 统一动作结果：`ENTER_LONG/ENTER_SHORT/EXIT/HOLD` + `reason`。
- 验收：
  - 同 bar 多规则命中时动作唯一且可解释。
- 依赖：`XTR-SP-004`。

### XTR-SP-006 RiskEngine（v0.3 固定模式）
- 目标：将 `RiskSpec` 转为标准 action 风险参数。
- 范围：
  - `size_model/stop_model/take_profit_model/time_stop/portfolio_guards`。
  - mode 白名单与参数边界校验。
  - 输出单位与字段契约对齐回测执行层。
- 交付物：
  - 风险计算模块与对应单测。
- 验收：
  - 输入 action + 风险配置后，输出 `size/stop_loss/take_profit` 符合契约。
- 依赖：`XTR-SP-005`。

### XTR-SP-007 ProfileActionStrategy 最小闭环
- 目标：打通 profile 驱动执行主链路。
- 范围：
  - `FeaturePipeline -> RegimeScoringEngine -> SignalEngine -> RiskEngine -> Action Output`。
  - 将 `reason_code` 映射到 action 输出 `reason` 字段。
- 交付物：
  - 可被 runtime/backtest 调用的 profile 策略执行入口。
- 验收：
  - 使用 `v0.3.json` 能跑通一次端到端动作生成。
- 依赖：`XTR-SP-006`。

### XTR-SP-008 写死策略下线与入口收敛
- 目标：主链路仅保留 profile 引擎，不保留写死业务逻辑策略。
- 范围：
  - 下线 `ThresholdIntradayStrategy` 在主链路中的职责。
  - 清理导出、入口、脚本与旧测试中的强耦合引用。
  - 保留 legacy 对照配置用于兼容验证（非主链路）。
- 交付物：
  - 唯一执行路径：profile + 引擎。
- 验收：
  - 主流程中无写死阈值策略分支。
- 依赖：`XTR-SP-007`。

### XTR-SP-009 E2E 回测与基线产物
- 目标：验证最小闭环在真实数据上的可运行性与可观测性。
- 范围：
  - 基于 BTCUSDT 5m 数据执行回测 smoke。
  - 产出 summary/trades/equity/signals/diagnostics。
- 交付物：
  - 一份可复现实验产物与运行说明。
- 验收：
  - 端到端 run 成功，关键产物文件齐全。
- 依赖：`XTR-SP-008`。

### XTR-SP-010 文档与运维收口
- 目标：保证后续新增策略可“只改配置少改代码”。
- 范围：
  - 更新架构文档、错误码、调参说明。
  - 增加 profile 编写指南与常见失败排查。
- 交付物：
  - 文档与 checklist 完整闭环。
- 验收：
  - 新同学可按文档独立完成 profile 新增与回测。
- 依赖：`XTR-SP-009`。

## 2. 里程碑建议
- M1（编译可用）：完成 `XTR-SP-001 ~ XTR-SP-002`。
- M2（评分可用）：完成 `XTR-SP-003 ~ XTR-SP-004`。
- M3（动作可用）：完成 `XTR-SP-005 ~ XTR-SP-007`。
- M4（系统收敛）：完成 `XTR-SP-008 ~ XTR-SP-010`。

## 3. 最小闭环定义
- “最小闭环完成”判定：`XTR-SP-001 ~ XTR-SP-007` 全部完成。
- 达成后即可基于 `v0.3` profile 开始策略效果验证与调参。

## 4. 任务细化（开发子项 / 单测清单 / 工作量）

### XTR-SP-001 细化
- 开发子项：
  - 固化 `RegimeSpec/SignalSpec/RiskSpec` 正式 schema 文件。
  - 补齐 schema 版本号与 `$id` 约定。
  - 在 precompile 入口接入 schema 校验。
- 单测清单：
  - 有效 `v0.3.json` 校验通过。
  - 缺字段/错枚举/越界值分别触发失败。
  - `additionalProperties` 非法字段触发失败。
- 预估工作量：`M`

### XTR-SP-002 细化
- 开发子项：
  - 实现 `input_refs` 与 `feature_catalog` 对照校验。
  - 实现 `score_fn` 签名与参数白名单校验。
  - 实现 `reason_code_map` 覆盖与 `priority_rank` 冲突校验。
  - 实现 `score_range` 重叠/覆盖性校验规则。
  - 实现 classifier `inputs` 集合一致性校验。
- 单测清单：
  - 正常 profile 编译成功并生成 resolved 产物。
  - `SCORE_FN_INPUT_ARITY_MISMATCH` 触发用例。
  - `UNUSED_CLASSIFIER_INPUT/UNDECLARED_CLASSIFIER_REF` 触发用例。
  - 缺失 `reason_code_map` 映射触发用例。
- 预估工作量：`L`

### XTR-SP-003 细化
- 开发子项：
  - 支持按 `required_indicator_plan_by_tf` 生成最小指标计算计划。
  - 接入多周期输入准备与 `decision_timeframe` 对齐前置逻辑。
  - 确认 `atr_pct_rank` 在 pipeline 中可稳定计算。
- 单测清单：
  - 仅声明被引用指标时可完成计算。
  - 多周期输入下能输出对齐后的特征列。
  - 缺失指标计划时给出明确错误。
- 预估工作量：`M`

### XTR-SP-004 细化
- 开发子项：
  - 实现 `score_fn` 执行器（5个内置函数）。
  - 实现 group 聚合与 rule weight 应用。
  - 实现 classifier first-match 语义。
  - 实现 state 权重归一化与 `score_total` 合成。
- 单测清单：
  - 每个 `score_fn` 用固定输入校验输出范围与方向性。
  - classifier priority 命中顺序测试。
  - `NO_TRADE_EXTREME` 全零权重时 `score_total=0`。
- 预估工作量：`L`

### XTR-SP-005 细化
- 开发子项：
  - 实现 `score_range` 命中判定（开闭区间）。
  - 实现 `state_allow/state_deny` 过滤。
  - 实现全局 `priority_rank` first-match。
  - 实现 `cooldown_scope=symbol_action`。
  - 实现 `reason_code_map` 输出映射。
- 单测清单：
  - 多规则同 bar 命中时结果唯一。
  - `state_deny` 命中时规则被拒绝。
  - cooldown 窗口内重复信号被抑制。
- 预估工作量：`M`

### XTR-SP-006 细化
- 开发子项：
  - 实现 `fixed_fraction` 仓位模型。
  - 实现 `fixed_pct/atr_multiple/rr_multiple` 止损止盈模型。
  - 实现 `time_stop/portfolio_guards` 的最小闭环钩子。
  - 对齐 action 输出单位与字段契约。
- 单测清单：
  - 各 mode 参数越界触发失败。
  - `ENTER_*` 输出 `size>0`，`EXIT/HOLD` 输出 `size=0`。
  - 给定价格输入下止损止盈价格计算正确。
- 预估工作量：`M`

### XTR-SP-007 细化
- 开发子项：
  - 新增 `ProfileActionStrategy`（或同等职责模块）。
  - 连接 Feature/Score/Signal/Risk 全链路执行。
  - 标准化输出 `reason=reason_code`。
- 单测清单：
  - `v0.3.json` 端到端动作输出 smoke test。
  - diagnostics 包含核心字段（state/score/action/reason）。
  - 异常 profile 可返回可定位错误信息。
- 预估工作量：`L`

### XTR-SP-008 细化
- 开发子项：
  - 清理主路径中 `ThresholdIntradayStrategy` 依赖。
  - 删除或迁移旧入口脚本/导出/测试。
  - 保留 legacy 对照配置与说明。
- 单测清单：
  - 主执行路径不再依赖写死阈值策略。
  - legacy 配置仍可被旧 runtime 加载。
- 预估工作量：`M`

### XTR-SP-009 细化
- 开发子项：
  - 准备固定数据窗口与回测命令模板。
  - 产出 summary/trades/equity/signals/diagnostics 归档。
  - 记录基线指标（交易数、胜率、回撤等）。
- 单测清单：
  - 端到端 run 成功且产物齐全。
  - 关键产物字段完整性检查通过。
- 预估工作量：`S`

### XTR-SP-010 细化
- 开发子项：
  - 更新架构图与执行流程说明。
  - 增补错误码与排查手册。
  - 增补 profile 模板与“新增策略操作说明”。
- 单测清单：
  - 文档示例配置可被校验器通过。
  - 文档中的命令可在本地复现最小流程。
- 预估工作量：`S`
