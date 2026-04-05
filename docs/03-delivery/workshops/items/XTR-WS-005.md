# ProfileAction 回测多周期输入自动装配 (XTR-WS-005)

- workshop_id: `XTR-WS-005`
- type: `requirement` # requirement | task | bug
- status: `approved` # draft | discussing | review | approved | deferred | rejected
- created_at: `2026-04-04`
- updated_at: `2026-04-04`
- owner: `tiger + codex`
- related_task_ids: `["XTR-SP-015"]`
- source: `chat://codex-session-2026-04-04`

## Background
当前 `StrategyProfile` 已支持多周期共振（如 `5m/15m/1h/4h`），`ProfileActionStrategy` 也会强制读取全部 required timeframes。  
但现有 `scripts/run_profile_action_backtest_smoke.py` 只加载单一周期并传入 `inputs={interval: bars}`，导致多周期 Profile 运行失败（缺少 `15m/1h/4h` 输入）。  
团队希望回测入口仅指定基础数据（如 Bitget BTCUSDT 5m），由脚本根据 profile 自动推导所需周期并重采样，统一装配后运行回测。

## Goal / Problem Statement
在不改动 RuntimeCore 主链路职责的前提下，增强 smoke 回测入口，使其支持：  
1) 从 profile precompile 结果自动推导 required_timeframes；  
2) 从基础周期数据自动 snapshot + 聚合高周期 bars；  
3) 组装 `bars_by_timeframe` 并传入 runtime 执行一次完整回测。

## Scope In
- 更新 `scripts/run_profile_action_backtest_smoke.py` 为 Profile 驱动的多周期输入装配入口。  
- 增加基础周期到高周期的重采样流程（UTC、OHLCV/funding 聚合规则固定）。  
- 支持从 precompile 结果自动确定 `required_timeframes` 与 `decision_timeframe`。  
- 运行时将完整 `bars_by_timeframe` 作为策略输入（必要时显式传 `strategy_inputs`），确保 `ProfileActionStrategy` 能读取到多周期数据。  
- 输出端保持现有报告产物结构（summary/decision_trace/signal_execution 等）。

## Scope Out
- 不改 `RuntimeCore` 主链路职责，不在主链路内新增自动 resample。  
- 不改 signal/action/risk 逻辑与评分公式。  
- 不处理实盘接入与外部行情拉取能力扩展（仅本地回测入口）。

## Constraints
- 必须兼容现有单周期 profile 与多周期 profile。  
- 基础周期必须不大于所需最高频周期（只能向高周期聚合，不能向低周期还原）。  
- 重采样语义必须稳定可复现（UTC + `label=right` + `closed=right`）。  
- 不破坏现有产物目录与 viewer 可读性。

## Requirement Summary
- REQ-001: 回测入口需能从 profile precompile 自动识别 required_timeframes。  
- REQ-002: 当仅提供基础周期数据时，系统需自动生成所需高周期 bars（snapshot 后聚合）。  
- REQ-003: 回测执行时需向策略提供完整多周期输入，避免 `missing required input`。  
- REQ-004: 输出报告需保留并标识多周期数据快照信息，便于追溯。

## Acceptance Criteria
- ACC-001 (REQ-001): 使用多周期 profile（如 `ai_multi_tf_signal_v1/v0.2`）时，脚本日志/结果能显示自动识别到 `5m/15m/1h/4h`。  
- ACC-002 (REQ-002): 在仅提供 5m 基础数据的前提下，回测流程可自动生成 `15m/1h/4h` 数据并参与策略计算。  
- ACC-003 (REQ-003): 回测执行成功，不再出现 `missing required input: <tf>`。  
- ACC-004 (REQ-004): 结果产物中可见多周期数据快照（raw + resampled）并可用于复盘追溯。

## Reproduction Steps (BUG required)
- precondition: _N/A_
- steps: _N/A_
- expected: _N/A_
- actual: _N/A_

## Risks
- 重采样边界定义不一致可能导致信号漂移（特别是 1h/4h 边界）。  
- 若 `strategy_inputs` 装配不当，仍可能触发策略输入键不匹配。  
- 长区间回测（3 年+）下，多周期计算的耗时与内存需关注。

## Open Questions
- Q-001 [Resolved]: 统一走 `RuntimeCore.run`，不再直接运行 `ProfileActionStrategy`。  
- Q-002 [Resolved]: 高周期数据统一由基础周期实时重采样生成。

## Discussion Log
- `2026-04-04`: workshop created.
- `2026-04-04`: 明确目标为“入口脚本装配多周期输入”，不改 RuntimeCore 主链路职责。
- `2026-04-04`: 决议采用 `RuntimeCore.run` 执行回测；高周期统一由基础周期实时重采样生成。

## Quality Gate Checklist
- [x] Structure complete
- [x] No semantic ambiguity
- [x] No conflicts (scope/constraints/acceptance)
- [x] No unclear descriptions
- [x] Open questions resolved

## Promotion Decision
- decision: `approved` # pending | approved | deferred | rejected
- linked_task_id: `_TBD_`
- approved_by: `tiger`
- approved_at: `2026-04-04`
- note: `进入任务开发流程前需创建 task_id 并补齐 spec/validation。`
