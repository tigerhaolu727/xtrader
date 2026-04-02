# ThresholdIntradayStrategy 全量下线与 Profile 主链路收敛 (XTR-SP-011)

## Intent
- `XTR-SP-008` 已完成“主入口去导出 + legacy 保留”，当前仓库仍存在 `ThresholdIntradayStrategy` 代码、脚本、配置、测试与文档残留。
- `XTR-WS-001` 已在需求研讨流程中确认：本轮改造采用“完全删除 + 一并下线”策略，不再保留 legacy 兼容入口。
- 本任务目标是将 threshold 相关资产从代码主仓清理到位，并把验证口径收敛到 `ProfileActionStrategy` 主链路。

## Requirement
### 功能目标
- 删除策略与入口：
  - 删除 `src/xtrader/strategies/builtin_strategies/threshold_intraday.py`
  - 删除 `src/xtrader/strategies/intraday.py`
- 删除脚本与配置：
  - 删除 `scripts/backtest_threshold_intraday_15m.py`
  - 删除 `scripts/run_threshold_intraday_runtime_backtest.py`
  - 删除 `configs/runtime/threshold_intraday_btcusdt_5m_3y.strategy.json`
- 清理兼容配置依赖：
  - 处理 `configs/runtime/five_min_regime_momentum_v0.3_legacy.strategy.json` 中 `threshold_intraday` 模式或其兼容标记，避免继续绑定已下线路径。
- 测试收敛：
  - 清理 `tests/unit/strategies/test_intraday.py` 与 `tests/unit/backtests/test_event_driven.py` 中对 `ThresholdIntradayStrategy` 的直接依赖；
  - 保留并增强 `ProfileActionStrategy` 主链路相关验证。
- 文档同步：
  - 更新 `docs/03-delivery/specs/XTR-SP-008.md` 与 `docs/03-delivery/validation/XTR-SP-008.md` 口径，不再描述 legacy 保留。

### 非目标 / 范围外
- 不新增策略功能、指标或信号规则。
- 不改动 `StrategyProfile` 协议与 profile 评分逻辑。
- 不做实盘执行侧功能扩展。

### 输入输出 / 接口
- 输入：
  - `docs/03-delivery/workshops/items/XTR-WS-001.md`（approved）
  - 现有 threshold 相关代码、脚本、配置、测试、文档。
- 输出：
  - 代码库不再提供 `ThresholdIntradayStrategy` 导入路径；
  - 主链路保留 `ProfileActionStrategy`；
  - 验证证据仅覆盖 profile 主链路。

## Design
### 核心思路与架构
- 采用“分层清理 + 回归收敛”：
  1. 删除策略实现与兼容导出层；
  2. 删除专属运行脚本与配置；
  3. 修复测试与文档引用；
  4. 用 profile 主链路 smoke 验证替代 threshold 旧链路验证。

### 数据/接口/模型
- 导入接口变化：
  - `from xtrader.strategies.intraday import ThresholdIntradayStrategy` 将不可用；
  - `from xtrader.strategies import ProfileActionStrategy` 继续作为主链路入口。
- 运行配置变化：
  - threshold 专用 runtime config 下线；
  - legacy 对照 config 保留但移除 `threshold_intraday` 绑定语义（按当前 runtime 能力保持可解释口径）。

### 风险与权衡
- 风险 1：删除后仍有隐式导入导致运行时报错。
  - 处理：全仓检索 + 单测覆盖 + smoke 验证。
- 风险 2：历史文档继续引导旧路径。
  - 处理：同步更新关键 spec/validation 文档并在会话记录中说明。
- 风险 3：测试大幅变动引入漏测。
  - 处理：保持 event-driven 核心行为测试，替换策略来源为 profile 主链路或中性测试策略。

## Acceptance
- 代码层：
  - 仓库中不再存在 `ThresholdIntradayStrategy` 可执行实现与导出入口。
  - `threshold_intraday` 专属脚本与配置文件已下线。
- 配置层：
  - 不再存在依赖 `threshold_intraday` 模式的运行配置入口（含 legacy 对照配置）。
- 测试层：
  - `tests/unit/strategies/test_intraday.py` 中不再测试 threshold 逻辑；
  - `tests/unit/backtests/test_event_driven.py` 不再导入或调用 `ThresholdIntradayStrategy`；
  - Profile 主链路 smoke/单测通过。
- 文档层：
  - `XTR-SP-008` spec/validation 已改为“全量下线”一致口径。
- 流程层：
  - `python scripts/task_guard.py check XTR-SP-011` 通过。

## Notes
- 前置依赖：
  - `docs/03-delivery/workshops/items/XTR-WS-001.md`
  - `docs/05-agent/processes/task_development_process.md`
- 关联文件清单见 workshop 的 `Affected Files Snapshot`。
