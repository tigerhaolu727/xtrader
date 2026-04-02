# ProfileActionStrategy 最小闭环 (XTR-SP-007)

## Intent
- `XTR-SP-003/004/005/006` 已分别实现 Feature/Score/Signal/Risk 模块，但尚未形成可直接被 runtime/backtest 调用的统一策略入口。
- 若缺少 `ProfileActionStrategy`，当前仍需手工串联模块，不满足“最小闭环可运行”目标。
- 本任务目标是实现单一策略类，完成 `FeaturePipeline -> RegimeScoringEngine -> SignalEngine -> RiskEngine -> Action Output` 串联并输出标准 action schema。

## Requirement
### 功能目标
- 新增 `ProfileActionStrategy`（或等价模块）并实现 `BaseActionStrategy` 接口。
- 启动时加载并 precompile `StrategyProfile`（支持 `dict` 与 JSON 文件路径）。
- 运行时执行固定链路：
  - Feature：按 precompile 产物计算所需特征；
  - Score：产出 `state/score_total/group_scores/rule_scores/group_weights`；
  - Signal：产出唯一 `action/reason_code`；
  - Risk：产出 `size/stop_loss/take_profit/reason`。
- 输出 `ActionStrategyResult`，满足 schema：
  - `timestamp,symbol,action,size,stop_loss,take_profit,reason`
- diagnostics 至少包含核心字段可观测性：
  - `state`
  - `score_total`
  - `action`
  - `reason`

### 非目标 / 范围外
- 不在本任务下线 `ThresholdIntradayStrategy`（由 `XTR-SP-008` 执行）。
- 不在本任务做真实账户持仓同步（仅消费传入上下文）。
- 不在本任务实现多策略调度。

### 输入输出 / 接口
- 输入（`StrategyContext`）：
  - `inputs`：按 timeframe 提供 OHLCV DataFrame（如 `5m`）；
  - `meta.account_context`：可选风控上下文（`equity/daily_pnl_pct/open_positions`）。
- 输出：
  - `ActionStrategyResult.actions`：标准 action DataFrame；
  - `ActionStrategyResult.diagnostics`：链路统计与核心字段预览。

## Design
### 核心思路与架构
- 在策略构造阶段完成 profile 预编译，缓存：
  - `resolved_profile`
  - `required_feature_refs`
  - `required_indicator_plan_by_tf`
  - `resolved_input_bindings`
- 在 `generate_actions` 中依次调用：
  - `FeaturePipeline.build_profile_model_df`
  - `RegimeScoringEngine.run`
  - `SignalEngine.run`
  - `RiskEngine.run`
- 最终按 `DEFAULT_ACTION_OUTPUT_SCHEMA` 截取字段并返回。

### 数据/接口/模型
- `required_inputs` 由 profile 所需 timeframe 自动推导（如 `("5m",)`）。
- `context.universe` 若存在，则在 bars 输入阶段按 symbol 过滤。
- diagnostics 输出建议：
  - `input_rows/output_rows`
  - `state_distribution`
  - `action_distribution`
  - `diagnostics_columns`（包含 `state/score_total/action/reason`）
  - `preview`（少量样本行）

### 风险与权衡
- 风险 1：profile 无效导致运行期才失败。
  - 处理：构造阶段 precompile fail-fast，并抛出带 error_code/path 的错误。
- 风险 2：跨模块字段命名不一致导致链路断裂。
  - 处理：统一在策略内部对中间 DataFrame 做最小契约检查。
- 风险 3：多 timeframe 输入缺失导致不可定位失败。
  - 处理：沿用 `context.require_input` + engine 错误码，保持可定位报错。

## Acceptance
- 使用 `configs/strategy-profiles/five_min_regime_momentum/v0.3.json` 可跑通端到端动作输出 smoke test。
- 返回结果满足 `ActionStrategyResult` schema 校验。
- diagnostics 包含核心字段可观测性（`state/score_total/action/reason`）。
- 非法 profile（precompile 失败）能返回可定位错误信息（含 error code/path 线索）。
- 自动化测试覆盖正例与关键反例。

## Notes
- 依赖：
  - `docs/03-delivery/specs/XTR-SP-003.md`
  - `docs/03-delivery/specs/XTR-SP-004.md`
  - `docs/03-delivery/specs/XTR-SP-005.md`
  - `docs/03-delivery/specs/XTR-SP-006.md`
  - `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
- 里程碑对齐：
  - 本任务完成后，M3（`XTR-SP-005 ~ XTR-SP-007`）达成。
