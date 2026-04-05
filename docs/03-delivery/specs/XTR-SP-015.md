# ProfileAction 回测入口多周期自动装配（RuntimeCore.run） (XTR-SP-015)

## Intent
当前 `StrategyProfile` 已支持多周期共振（如 `5m/15m/1h/4h`），但 `run_profile_action_backtest_smoke.py` 仅加载单周期并直接调用 `ProfileActionStrategy`，导致多周期 profile 在回测时缺失输入。  
本任务目标是将 smoke 回测入口升级为“基于基础周期数据自动装配多周期输入”的执行器，并统一走 `RuntimeCore.run`，实现与主链路一致的回测运行与产物输出。

## Requirement
- 功能目标
- 从 profile precompile 结果自动推导 `required_timeframes` 与 `decision_timeframe`。
- 用户仅提供基础周期行情（如 Bitget BTCUSDT 5m）时，脚本自动完成 snapshot 与高周期重采样（`15m/1h/4h/...`）。
- 将完整 `bars_by_timeframe` 与 `strategy_inputs` 传入 `RuntimeCore.run`，避免 `missing required input`。
- 回测产物保持可追溯：保留 raw/resampled 快照与 run manifest 链路。
- 非目标 / 范围外
- 不在 `RuntimeCore` 主链路新增自动重采样职责。
- 不修改 signal/risk/action 业务逻辑及评分函数。
- 不扩展实盘行情接入能力。
- 输入输出或接口
- 输入：`--profile`、交易所/市场/标的、基础周期、时间范围、数据根目录、费用参数等。
- 输出：运行状态 JSON、report root、summary/diagnostics/decision_trace/trades/equity 等产物路径。

## Design
- 核心思路与架构
- `run_profile_action_backtest_smoke.py` 内新增“profile-driven timeframe assembler”。
- 先执行 `StrategyProfilePrecompileEngine.compile(profile)`，提取 required timeframes。
- 加载基础周期 bars 作为唯一原始输入，先固化 raw snapshot，再按统一规则重采样到所有目标周期。
- 构造 `RuntimeCore.run` 所需 runtime config（adapter），并传入：
- `strategy=ProfileActionStrategy(profile_config=...)`
- `bars_by_timeframe={tf: bars_df}`
- `strategy_inputs=bars_by_timeframe`（显式覆盖默认 `features` 输入模式）
- `backtest_config` 与运行元信息
- 数据/接口/模型
- 重采样规则统一：UTC、`label=right`、`closed=right`、OHLCV/funding 聚合稳定。
- 仅允许“从基础周期向更高周期聚合”；若 required timeframe 比基础周期更细，直接 fail-fast。
- 执行周期与 profile 的 `decision_timeframe` 对齐。
- 风险与权衡
- 风险：重采样边界定义不一致导致信号偏移。
- 风险：大区间回测（3y+）的内存与耗时显著增加。
- 权衡：将复杂性放在入口脚本，保持 `RuntimeCore` 简洁且利于后续实盘多周期数据并行加载。

## Acceptance
- 使用 `configs/strategy-profiles/ai_multi_tf_signal_v1/v0.2.json`，仅提供 5m 基础数据时可回测成功。
- 运行日志/结果中可确认自动识别到 `required_timeframes`（至少 `5m/15m/1h/4h`）。
- 回测不再出现 `missing required input` 错误。
- 产物中包含 raw + resampled 快照，并在 manifest/viewer contract 可追溯。
- 单周期 profile 仍可兼容运行（不引入行为回归）。

## Notes
- 关联研讨：`XTR-WS-005`
- 实现前置：按任务守门完成 spec/validation 文档确认后再改代码。
