# RiskEngine（v0.3 固定模式）实现 (XTR-SP-006)

## Intent
- `XTR-SP-005` 已能输出唯一动作与 reason_code，但还缺“动作 -> 风险参数”转换层。
- 若不实现 `RiskEngine`，`ProfileActionStrategy` 无法生成完整 action schema（`size/stop_loss/take_profit/reason`）。
- 本任务目标是按 v0.3 固定 mode 实现 RiskSpec 运行时解释，形成可测试的风险输出模块。

## Requirement
### 功能目标
- 实现 `RiskEngine`，支持 v0.3 mode：
  - `size_model.mode=fixed_fraction`
  - `stop_model.mode=fixed_pct|atr_multiple`
  - `take_profit_model.mode=fixed_pct|rr_multiple`
- 执行语义：
  - `ENTER_LONG/ENTER_SHORT` 必须输出 `size > 0`
  - `EXIT/HOLD` 必须输出 `size = 0`
  - `stop_loss/take_profit` 输出绝对价格位
  - `reason` 口径保持 `reason=reason_code`
- 提供 `portfolio_guards` 最小闭环钩子：
  - `daily_loss_limit`
  - `max_concurrent_positions`

### 非目标 / 范围外
- 不在本任务实现账户账本与真实仓位管理（仅消费传入上下文）。
- 不在本任务接入 runtime/backtest 主入口（`XTR-SP-007` 统一打通）。
- 不在本任务扩展 v0.4 额外 mode。

### 输入输出 / 接口
- 建议接口：
  - `RiskEngine.run(...) -> pd.DataFrame`
- 输入：
  - `resolved_profile`（`risk_spec`）
  - `signal_df`（至少含 `timestamp/symbol/action/reason_code`）
  - `market_df`（至少含 `timestamp/symbol/close`，`atr_multiple` 模式需 ATR 列）
  - `account_context`（可选：`equity/daily_pnl_pct/open_positions`）
- 输出：
  - `timestamp,symbol,action,size,stop_loss,take_profit,reason`
  - 可附带 `reason_code/matched_rule_id/score_total/state` 便于后续诊断。

## Design
### 核心思路与架构
- 逐行执行三段式：
  1. Guards：按上下文先执行 `daily_loss_limit/max_concurrent_positions`；
  2. Size：按 `fixed_fraction` 计算 size；
  3. Stop/TP：按 stop/take_profit mode 输出绝对价格位。

### 数据/接口/模型
- `fixed_fraction`：
  - 使用 `equity`（默认 1.0）与 `close` 计算头寸单位（`size = equity * fraction / close`）。
- `fixed_pct`：
  - LONG：`stop = close*(1-pct)`，`tp = close*(1+pct)`
  - SHORT：`stop = close*(1+pct)`，`tp = close*(1-pct)`
- `atr_multiple` + `rr_multiple`：
  - LONG：`stop = close - atr*multiple`，`tp = close + rr*(close-stop)`
  - SHORT：`stop = close + atr*multiple`，`tp = close - rr*(stop-close)`
- rounding：
  - 若配置 `rounding_policy`，按 `price_dp/size_dp` 统一舍入。

### 风险与权衡
- 风险 1：ATR 来源歧义（feature_ref 可能不止一个）。
  - 处理：优先 `atr_value` 列；否则从 `f:*:atr_*:value` 自动识别，若多列则 fail-fast。
- 风险 2：guard 与 signal 冲突。
  - 处理：guard 触发时统一覆盖为保守动作（进入动作降级 HOLD），并写 guard reason_code。
- 风险 3：市场列缺失导致 silent wrong。
  - 处理：`close/atr` 缺失时 fail-fast 返回稳定错误。

## Acceptance
- `RiskEngine` 能基于 `SignalEngine` 输出生成标准 action 风险字段。
- 固定百分比模式下，LONG/SHORT 的止损止盈价格计算正确。
- ATR + RR 模式下，止损止盈价格计算正确。
- `ENTER_*` 输出 `size>0`，`EXIT/HOLD` 输出 `size=0`。
- 缺失必要市场字段（`close` 或 `atr`）时 fail-fast。
- 自动化测试覆盖正例与关键负例。

## Notes
- 依赖：
  - `docs/03-delivery/specs/XTR-SP-005.md`
  - `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
  - `configs/strategy-profiles/five_min_regime_momentum/v0.3.json`
- 里程碑对齐：
  - 本任务完成后，M3 进入 `XTR-SP-007` 端到端串联阶段。
