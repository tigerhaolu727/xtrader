# SignalEngine（conditions 版）实现 (XTR-SP-005)

## Intent
- `XTR-SP-004` 已产出 `score_total/state/group_scores/rule_scores`，但尚缺将评分映射为唯一动作的运行时引擎。
- 若不实现 `SignalEngine`，M3 的动作闭环无法继续推进，`XTR-SP-006` 也没有稳定输入。
- 本任务目标是落地 `SignalSpec` 的 conditions 执行语义，输出唯一 action 与标准 reason_code。

## Requirement
### 功能目标
- 实现 `SignalEngine`，基于 `SignalSpec` 对每行评分结果生成唯一动作：
  - `ENTER_LONG/ENTER_SHORT/EXIT/HOLD`
- 实现规则命中语义（v0.3 冻结）：
  - `score_range` 命中（含开闭区间边界）；
  - `state_allow/state_deny` 过滤（同时存在时 `state_deny` 优先）；
  - `priority_rank` 全局升序 first-match（同 bar 单动作）；
  - `cooldown_bars + cooldown_scope=symbol_action` 抑制重复动作；
  - `reason_code_map` 映射到 `reason_code`（并输出 `reason=reason_code` 兼容口径）。

### 非目标 / 范围外
- 不在本任务实现风险参数计算（`XTR-SP-006`）。
- 不在本任务打通 runtime/backtest 主入口（`XTR-SP-007`）。
- 不在本任务扩展新 `cooldown_scope` 枚举（v0.3 仅 `symbol_action`）。

### 输入输出 / 接口
- 建议接口：
  - `SignalEngine.run(...) -> pd.DataFrame`
- 输入：
  - `resolved_profile`（`signal_spec`）
  - `scoring_df`（至少包含 `timestamp/symbol/score_total/state`）
- 输出：
  - `timestamp/symbol/action/reason_code/reason/matched_rule_id`
  - 可选保留 `score_total/state` 用于后续引擎串联与诊断。

## Design
### 核心思路与架构
- 规则准备阶段：
  - 收集启用规则（`entry/exit/hold`），按 `priority_rank` 升序排序。
- 逐行执行阶段：
  1. 按排序后的规则列表做 first-match；
  2. 对命中候选执行冷却检查；
  3. 选中即输出并结束该行；
  4. 若无规则可选，兜底输出 `HOLD`。

### 数据/接口/模型
- `score_range` 判定：
  - `min/max` 支持 `null` 无界；
  - 按 `min_inclusive/max_inclusive` 执行边界判断。
- 状态过滤：
  - 若 `state_deny` 命中，规则直接拒绝；
  - 再判断 `state_allow`（若配置且不包含当前 state，则拒绝）。
- 冷却语义：
  - 以 `(symbol, action)` 作为 key；
  - 记录最后触发 bar 位置；
  - 在 `cooldown_bars` 内重复同 action 则跳过该规则继续匹配后续规则。

### 风险与权衡
- 风险 1：区间边界与优先级耦合导致误判。
  - 处理：增加边界测试（闭开、等值边界、重叠区间 first-match）。
- 风险 2：冷却语义歧义导致输出不稳定。
  - 处理：固定为“被抑制规则不终止匹配，继续寻找后续规则”，确保每行仍得到确定动作。
- 风险 3：reason 映射遗漏导致可解释性断层。
  - 处理：运行时对 `reason_code_map` 缺失做 fail-fast（即使 precompile 已守门）。

## Acceptance
- `SignalEngine` 能基于 `score_total/state` 产出唯一动作与 `reason_code`。
- 重叠区间场景按 `priority_rank` first-match 稳定决策。
- `state_allow/state_deny` 同时存在时，`state_deny` 优先。
- `cooldown_scope=symbol_action` 生效：冷却窗口内同 `symbol+action` 被抑制。
- 输出含 `reason=reason_code`，并可追溯 `matched_rule_id`。
- 自动化测试覆盖正例与关键负例。

## Notes
- 依赖：
  - `docs/03-delivery/specs/XTR-SP-004.md`
  - `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
  - `configs/strategy-profiles/five_min_regime_momentum/v0.3.json`
- 里程碑对齐：
  - 本任务完成后进入 M3 的第 2 步（`XTR-SP-005 ~ XTR-SP-007`）。
