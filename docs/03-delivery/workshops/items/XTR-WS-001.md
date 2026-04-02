# ThresholdIntradayStrategy策略重构清理 (XTR-WS-001)

- workshop_id: `XTR-WS-001`
- type: `task` # requirement | task | bug
- status: `approved` # draft | discussing | review | approved | deferred | rejected
- created_at: `2026-04-02`
- updated_at: `2026-04-02`
- owner: `tiger + codex`
- related_task_ids: `["XTR-SP-011"]`
- source: `用户指令：启动任务研讨流程（2026-04-02）`

## Background
- 现有框架已形成 `regime -> score -> signal` 判定主链路。
- `ProfileActionStrategy` 已支持基于 `StrategyProfile` 的闭环运行与回测。
- `ThresholdIntradayStrategy` 仍承载部分历史逻辑与入口，存在与新主链路重复或冗余的风险。

## Goal / Problem Statement
- 对 `ThresholdIntradayStrategy` 进行重构清理，移除不再需要或重复的逻辑，降低维护成本。
- 明确并收敛策略入口：以 profile 驱动链路为主，避免同一职责在多个策略实现中重复。
- 在清理过程中保持现有关键链路可运行，避免引入行为回归。

## Scope In
- 完全删除 `ThresholdIntradayStrategy` 及其直接实现文件 `src/xtrader/strategies/builtin_strategies/threshold_intraday.py`。
- 一并下线 `src/xtrader/strategies/intraday.py`，移除该入口在当前运行链路中的职责。
- 一并下线 `scripts/backtest_threshold_intraday_15m.py`，不再保留 threshold 专属回测脚本。
- 一并下线 `scripts/run_threshold_intraday_runtime_backtest.py` 与 `configs/runtime/threshold_intraday_btcusdt_5m_3y.strategy.json`。
- 处理 `configs/runtime/five_min_regime_momentum_v0.3_legacy.strategy.json` 中 `threshold_intraday` 兼容模式字段，避免继续依赖旧逻辑。
- 清理 `tests/unit/strategies/test_intraday.py` 与 `tests/unit/backtests/test_event_driven.py` 中对 `ThresholdIntradayStrategy` 的直接依赖，测试收敛到 Profile 主链路。
- 同步更新 `docs/03-delivery/specs/XTR-SP-008.md` 与 `docs/03-delivery/validation/XTR-SP-008.md`，口径从“legacy 保留”调整为“已下线”。
- 同步清理上述对象的导入、注册、文档与引用，避免残留无效入口。
- 回归验证范围仅覆盖 `Profile` 主链路（不要求 threshold 旧链路回归）。

## Scope Out
- 不在本任务内新增策略功能（不增加新指标/新信号规则）。
- 不在本任务内调整 `StrategyProfile` 协议设计。
- 不在本任务内实现实盘执行侧新能力。
- 不保留 threshold 兼容壳或 legacy 运行入口。

## Constraints
- 必须遵循“先研讨、再任务开发流程”的文档守门约束。
- 重构优先“删除冗余 + 责任收敛”，避免顺带大规模功能扩展。
- 所有变更需有可回归验证（单测/集成测试/脚本 smoke）。

## Requirement Summary
- REQ-001: 完全删除 `ThresholdIntradayStrategy` 及其实现文件，不保留兼容壳。
- REQ-002: 一并下线 `src/xtrader/strategies/intraday.py`，移除旧入口职责。
- REQ-003: 一并下线 `scripts/backtest_threshold_intraday_15m.py` 及其调用链引用。
- REQ-004: 提供仅针对 `Profile` 主链路的可执行验证证据，证明清理后主链路可运行。
- REQ-005: 一并下线 `scripts/run_threshold_intraday_runtime_backtest.py` 与 `configs/runtime/threshold_intraday_btcusdt_5m_3y.strategy.json`。
- REQ-006: 清理 `tests/unit/strategies/test_intraday.py` 与 `tests/unit/backtests/test_event_driven.py` 中的 threshold 直连依赖，并改为 Profile 主链路相关验证。
- REQ-007: 同步修正文档口径（至少覆盖 `XTR-SP-008` spec/validation），避免继续描述 legacy 保留。

## Acceptance Criteria
- ACC-001 (REQ-001): 代码库中已不存在 `ThresholdIntradayStrategy` 可执行入口，相关文件/注册已清理。
- ACC-002 (REQ-002): `src/xtrader/strategies/intraday.py` 已下线，且无运行路径继续依赖该模块。
- ACC-003 (REQ-003): `scripts/backtest_threshold_intraday_15m.py` 已下线，相关文档与调用引用已同步移除。
- ACC-004 (REQ-004): 至少完成 1 组 `Profile` 主链路 smoke 验证并记录结果；本次不要求 threshold 旧链路回归。
- ACC-005 (REQ-005): `scripts/run_threshold_intraday_runtime_backtest.py` 与 `configs/runtime/threshold_intraday_btcusdt_5m_3y.strategy.json` 已下线，且运行入口不存在对它们的引用依赖。
- ACC-006 (REQ-006): `tests/unit/strategies/test_intraday.py` 与 `tests/unit/backtests/test_event_driven.py` 已去除 `ThresholdIntradayStrategy` 导入与调用，测试语义与 Profile 主链路一致。
- ACC-007 (REQ-007): `XTR-SP-008` 的 spec/validation 文档已反映“threshold 全量下线”结论，不再描述 legacy 保留路径。

## Reproduction Steps (BUG required)
- precondition: _N/A_
- steps: _N/A_
- expected: _N/A_
- actual: _N/A_

## Risks
- 下线后若仍有隐式引用，会在运行时触发导入错误。
- 历史文档或脚本仍指向旧入口时，可能造成使用者认知偏差。
- 若未充分清理注册层，可能出现“代码已删但配置仍可选”的不一致状态。

## Affected Files Snapshot (2026-04-02)
- 直接下线对象：
  - `src/xtrader/strategies/builtin_strategies/threshold_intraday.py`
  - `src/xtrader/strategies/intraday.py`
  - `scripts/backtest_threshold_intraday_15m.py`
  - `scripts/run_threshold_intraday_runtime_backtest.py`
  - `configs/runtime/threshold_intraday_btcusdt_5m_3y.strategy.json`
- 兼容配置处理对象：
  - `configs/runtime/five_min_regime_momentum_v0.3_legacy.strategy.json`
- 测试改造对象：
  - `tests/unit/strategies/test_intraday.py`
  - `tests/unit/backtests/test_event_driven.py`
- 文档同步对象：
  - `docs/03-delivery/specs/XTR-SP-008.md`
  - `docs/03-delivery/validation/XTR-SP-008.md`

## Open Questions
- Q-001 [Resolved]: `ThresholdIntradayStrategy` 采用“完全删除”方案。
- Q-002 [Resolved]: `scripts/backtest_threshold_intraday_15m.py` 一并下线。
- Q-003 [Resolved]: `src/xtrader/strategies/intraday.py` 一并下线。
- Q-004 [Resolved]: 回归范围仅 `Profile` 主链路。

## Discussion Log
- `2026-04-02`: workshop created.
- `2026-04-02`: 基于用户输入形成研讨初稿，进入 discussing。
- `2026-04-02`: 用户确认 4 项关键决策：完全删除 ThresholdIntradayStrategy、下线 intraday.py、下线阈值回测脚本、回归仅 Profile 主链路。
- `2026-04-02`: 追加仓库扫描结果，将 `run_threshold_intraday_runtime_backtest.py`、threshold runtime config、相关测试与文档同步纳入清理范围。
- `2026-04-02`: Open Questions 全部关闭，研讨进入 approved。

## Quality Gate Checklist
- [x] Structure complete
- [x] No semantic ambiguity
- [x] No conflicts (scope/constraints/acceptance)
- [x] No unclear descriptions
- [x] Open questions resolved

## Promotion Decision
- decision: `approved` # pending | approved | deferred | rejected
- linked_task_id: `XTR-SP-011`
- approved_by: `tiger`
- approved_at: `2026-04-02`
- note: `按用户确认口径通过，任务已创建：XTR-SP-011。`
