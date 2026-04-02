# RegimeScoringEngine 实现 (XTR-SP-004)

## Intent
- `XTR-SP-003` 已能按 precompile 产物输出决策周期输入特征表，但尚缺评分主链路实现。
- 若不补 `RegimeScoringEngine`，`SignalEngine` 无法获取 `score_total/state/group_scores`，M2 无法闭环。
- 本任务目标是实现固定执行链路：`RuleEngine -> GroupAggregator -> RegimeEngine -> ScoreSynthesizer`，并提供稳定诊断输出。

## Requirement
### 功能目标
- 实现 `RegimeScoringEngine`，输入 profile precompile 产物 + 决策周期特征表，输出评分结果表。
- 实现 5 个内置 `score_fn`：
  - `trend_score`
  - `momentum_score`
  - `direction_score`
  - `volume_score`
  - `pullback_score`
- 固化执行语义：
  - Rule 层：按 `score_fn` 计算 `rule_score`，输入缺失/NaN 按 `nan_policy=neutral_zero` 输出 `0.0`；
  - Group 层：按 `group.rule_weights` 聚合 `group_score`；
  - Regime 层：按 `classifier.rules.priority` 升序 first-match + 条件 AND 计算 `state`；
  - Synthesizer 层：按 `state_group_weights[state]` 归一化后合成 `score_total`，并裁剪到 `[-1, 1]`。
- 诊断输出至少包含：
  - `state`
  - `score_total`
  - `group_scores`
  - `group_weights`
  - `rule_scores`

### 非目标 / 范围外
- 不在本任务实现 `SignalEngine`（`XTR-SP-005`）。
- 不在本任务实现 `RiskEngine`（`XTR-SP-006`）。
- 不在本任务接入 runtime/backtest 主入口（`XTR-SP-007` 做端到端接线）。

### 输入输出 / 接口
- 建议接口：
  - `RegimeScoringEngine.run(...) -> pd.DataFrame`
- 输入：
  - `resolved_profile`（来自 precompile 成功产物）
  - `resolved_input_bindings`（`rule_id -> role:feature_ref`）
  - `model_df`（来自 `FeaturePipeline.build_profile_model_df`）
- 输出：
  - 行对齐 `model_df` 的 DataFrame；
  - 包含基础主键列 `timestamp/symbol` 与评分诊断列。

## Design
### 核心思路与架构
- `RegimeScoringEngine` 内部拆 4 步，外部保持单入口：
  1. RuleEngine：按规则逐行计算 `rule_score`；
  2. GroupAggregator：按 `rule_weights` 聚合 `group_score`；
  3. RegimeEngine：对每行执行 classifier 命中状态；
  4. ScoreSynthesizer：按状态权重合成 `score_total`。

### 数据/接口/模型
- `score_fn` 执行来源：
  - 复用 `score_fn_registry` 中的签名与参数边界；
  - 本任务新增运行时实现（数学公式与需求文档 5.1~5.5 一致）。
- `momentum_score/volume_score` 需要滚动标准差：
  - 使用 `std_window` 参数（默认 96）；
  - `std <= eps` 视为无效输入，按 `neutral_zero` 处理。
- classifier 条件算子支持：
  - `> >= < <= == != between`；
  - `between` 语义为闭区间 `[min,max]`；
  - 条件依赖值为 NaN 时条件判定为 `false`。
- 权重合成：
  - group 内按配置线性加权；
  - state 权重先归一化再合成总分；
  - 权重和为 0 时，所有 `group_weights=0` 且 `score_total=0`。

### 风险与权衡
- 风险 1：`score_fn` 数值漂移导致行为不稳定。
  - 处理：全部输出统一 `clip[-1,1]`，并为每个 `score_fn` 增加定向单测。
- 风险 2：classifier 边界判定偏差影响 state。
  - 处理：补 first-match 顺序与 `between` 边界测试。
- 风险 3：零权重状态处理不一致。
  - 处理：固定 `sum(weights)<=eps` 分支输出 `score_total=0`，并补 `NO_TRADE_EXTREME` 用例。

## Acceptance
- `RegimeScoringEngine` 能消费 `XTR-SP-003` 输出，生成 `state/group_scores/group_weights/rule_scores/score_total`。
- 5 个内置 `score_fn` 在固定输入下输出方向与范围符合预期，结果受控在 `[-1,1]`。
- classifier 满足：
  - `priority` 升序 first-match；
  - 单规则 `conditions` 为 AND；
  - 无命中时回退 `default_state`。
- `NO_TRADE_EXTREME` 全零权重状态下 `score_total == 0`。
- 自动化测试覆盖：
  - 正例：基础评分链路 + 多状态切换；
  - 反例：缺失 feature_ref / 非法条件字段 / 权重和为 0 分支。

## Notes
- 依赖：
  - `docs/03-delivery/specs/XTR-SP-003.md`
  - `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
  - `configs/strategy-profiles/five_min_regime_momentum/v0.3.json`
- 里程碑对齐：
  - 本任务完成后，M2（`XTR-SP-003 ~ XTR-SP-004`）达成。
