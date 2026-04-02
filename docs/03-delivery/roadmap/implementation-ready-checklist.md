# 实现前定稿清单（Ready Checklist）

## 目标
在进入策略实现阶段前，冻结关键契约与规则，避免实现过程中反复返工。

## 使用方式
- 每条清单在讨论达成共识后，将状态从 `[ ]` 改为 `[x]`。
- 若某条暂缓，注明“暂缓原因 + 关联 backlog ID”。
- 全部勾选后，再进入对应 `XTR-xxx` 的 spec/validation 与编码阶段。

## A. 动作与风险契约
- [x] `stop_loss / take_profit` 语义冻结：v1 统一输出绝对价格位（float64）；策略内部可用 `%/ATR` 推导，但输出前必须换算完成，执行层不做二次解释。
- [x] `size` 口径冻结：v1 定义为账户权益占比（`0~1`）的仓位指令；方向由 `action` 决定（`size` 不承载方向），`ENTER_*` 需 `size>0`，`EXIT/HOLD` 需 `size=0`，执行层据此换算实际下单数量。
- [ ] `reason` 规范冻结：统一 reason code 枚举（禁止自由文本漂移）。

## B. 信号与执行顺序
- [x] 信号到动作映射冻结：v1 `action` 枚举固定为 `ENTER_LONG/ENTER_SHORT/EXIT/HOLD`（不启用 `REVERSE`）；`BUY/SELL/HOLD` 按“当前持仓 + 单 bar 单动作”规则映射到该枚举。
- [ ] `SignalSpec` schema 冻结：`entry_rules/exit_rules/hold_rules + rule.score_range + state_allow/state_deny + rule.priority_rank + cooldown_scope + reason_code_map` 字段与语义定稿（不使用自由文本 `expr`）。
- [ ] 同时刻冲突优先级冻结：策略信号 vs 风控强平（谁优先）。
- [ ] 同 bar 行为顺序冻结：`signal_time`、`execution_time`、risk check 的执行先后。

## C. 评分与状态机制
- [ ] 评分缺失处理冻结：warmup/NaN 时的统一策略（中性分/降权/跳过）。
- [ ] 市场状态切换规则冻结：阈值、连续确认 `N`、防抖参数。
- [ ] 动态权重规则冻结：乘子矩阵、边界裁剪、归一化与异常回退。
- [x] `score_fn registry` 冻结：v0.3 仅内置 `trend_score/momentum_score/direction_score/volume_score/pullback_score`，签名顺序固定、`params` 白名单与边界固定、默认参数固定、`custom_udf` 禁用。

## D. 时间与可解释性
- [ ] 时间语义冻结：`timestamp` 全链路口径（与 `BLG-0002` 对齐后关闭）。
- [x] 评分型策略输出诊断字段冻结：最小 `diagnostics` 字段集（`score/state/weight/signal/reason`），并约定缺失降级为 `NOT_AVAILABLE`、schema 异常仅影响 diagnostics 子面板。
- [ ] 报告可解释性冻结：UI/回测产物中要能追溯“为何入场/为何离场”。

## E. 风险参数编排
- [ ] `RiskSpec` schema 冻结：`size_model/stop_model/take_profit_model/time_stop/portfolio_guards` 字段与单位口径定稿。
- [ ] 风险输出契约冻结：`ENTER_*` 必须 `size>0`，`EXIT/HOLD` 必须 `size=0`，并统一 `stop_loss/take_profit` 单位与类型。
- [ ] 风险优先级冻结：风险约束触发时，对信号层动作的覆盖策略（拦截/降级/替换）定稿。

## 关联 backlog
- `BLG-0002` timestamp 语义一致性
- `BLG-0005` 维度三（技术指标）
- `BLG-0006` 维度四（趋势强度）
- `BLG-0007` 维度五（波动率）
- `BLG-0008` 动态权重机制
- `BLG-0009` 评分型策略接口

## 复核结论（待填写）
- 结论日期：
- 冻结版本：
- 可启动实现的任务 ID：
