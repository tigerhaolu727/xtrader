# E2E 回测与基线产物 (XTR-SP-009)

## Intent
- `XTR-SP-008` 已完成主链路入口收敛，当前推荐执行路径是 `ProfileActionStrategy`。
- 仍缺少“真实本地数据上的可复现实验”与“统一产物落盘基线”，导致后续调参与回归缺少对照面板。
- 本任务目标是在 `BTCUSDT 5m` 数据上完成一次 profile 引擎端到端 smoke，并沉淀固定命令与关键产物约定。

## Requirement
### 功能目标
- 提供可复现的 `ProfileActionStrategy` 回测 smoke 运行方式（脚本 + 固定参数示例）。
- 使用本地 `BTCUSDT 5m` K 线驱动完整链路：
  - `ProfileActionStrategy.generate_actions`
  - `run_event_driven_backtest`
  - `write_strategy_event_driven_outputs`
- 输出并归档以下关键产物：
  - `summary.json`
  - `diagnostics.json`
  - `ledgers/trades.parquet`
  - `curves/equity_curve.parquet`
  - `timelines/signal_execution.parquet`
  - `run_manifest.json`
- 记录一份基线指标（至少包含：`trade_count/win_rate/max_drawdown/net_return`）。

### 非目标 / 范围外
- 不在本任务做策略参数寻优或收益目标承诺。
- 不在本任务引入新的风险模型或评分函数。
- 不在本任务替换 event-driven 产物 schema（沿用现有 writer 协议）。

### 输入输出 / 接口
- 输入：
  - profile：`configs/strategy-profiles/five_min_regime_momentum/v0.3.json`
  - 数据：`data/klines/bitget/linear_swap/BTCUSDT/5m/**/*.parquet`
  - 回测配置：`EventDrivenBacktestConfig`（`interval_ms=300000`，含 fee/slippage 参数）
- 输出：
  - strategy-scoped 报告目录（`reports/backtests/strategy/profile_action/<run_id>`）
  - 标准 event-driven 产物与 summary 指标。

## Design
### 核心思路与架构
- 复用现有事件回测与产物写出能力，不新增并行框架：
  1. 从本地 parquet 读取并清洗 `BTCUSDT 5m` bars；
  2. 构造 `StrategyContext(inputs={"5m": bars})`；
  3. 调用 `ProfileActionStrategy` 产出 action；
  4. 调用 `run_event_driven_backtest` 计算 trades/equity/summary；
  5. 调用 `write_strategy_event_driven_outputs` 写出标准产物。
- 新增一个可直接运行的 smoke 脚本，固定输入输出协议，便于后续回归复用。

### 数据/接口/模型
- 新脚本默认 strategy 名称采用 `Profile Action`（写入 strategy-scoped 路径）。
- bars 最小列契约：
  - `timestamp,symbol,open,high,low,close,volume`
  - 缺失 `funding_rate` 时补 `0.0`。
- summary 基线从 `EventDrivenBacktestSummary` 直接提取，避免重复口径计算。

### 风险与权衡
- 风险 1：本地数据窗口无数据导致 smoke 失败。
  - 处理：脚本 fail-fast，报出区间与数据路径，便于快速排查。
- 风险 2：profile 输出 action 与回测输入列契约不一致。
  - 处理：沿用 `ActionStrategyResult` schema + 回测入参校验双层守门。
- 风险 3：产物路径不一致影响后续自动化读取。
  - 处理：统一使用 `write_strategy_event_driven_outputs`，禁止手写自定义落盘结构。

## Acceptance
- 在固定数据窗口执行 smoke 命令可成功完成端到端回测。
- strategy-scoped 报告目录中存在关键产物文件：
  - `summary.json`
  - `diagnostics.json`
  - `ledgers/trades.parquet`
  - `curves/equity_curve.parquet`
  - `timelines/signal_execution.parquet`
  - `run_manifest.json`
- `summary.json` 包含 `trade_count/win_rate/max_drawdown/net_return` 字段。
- 自动化测试覆盖 profile->backtest->writer 的最小正例链路（含关键产物存在性断言）。

## Notes
- 依赖：
  - `docs/03-delivery/specs/XTR-SP-007.md`
  - `docs/03-delivery/specs/XTR-SP-008.md`
  - `docs/03-delivery/roadmap/implementation-tasks-v0.3.md`
- 里程碑对齐：
  - 本任务完成后，M4 进入 `XTR-SP-010`（文档与运维收口）。
