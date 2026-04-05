# 减少重复特征构建：一次性构建评分与Trace特征超集 (XTR-SP-016)

## Intent
`ProfileActionStrategy.generate_actions` 当前在同一轮执行中存在二次特征构建：
1) `build_profile_model_df`（评分/信号/风控）；
2) `build_model_df`（decision_trace 补充特征）。

该重复构建带来额外指标计算和 DataFrame 合并开销，已在性能分析中成为可优化项。  
本任务目标是在不改变策略语义和可追溯能力前提下，移除二次特征构建。

## Requirement
- 功能目标
  - 统一特征构建流程，一次性产出“评分 + trace 所需”特征超集。
  - 评分链路（regime/signal/risk）与 trace 链路共享同一份特征数据源（或缓存命中结果）。
  - 保持 Signal V1 证据链字段可用（`condition_hits / gate_results / score_adjustment / macd_state`）。
- 非目标 / 范围外
  - 不修改 `RuntimeCore` 主链路职责与接口契约。
  - 不改策略规则、积分公式、action/risk 逻辑。
  - 不新增 profile schema 字段。
- 输入输出或接口
  - 输入：`ProfileActionStrategy` 现有 `bars_by_timeframe` 与 profile precompile 产物。
  - 输出：`ActionStrategyResult`（actions/diagnostics/decision_trace）结构保持兼容。

## Design
- 核心思路与架构
  - 在 `ProfileActionStrategy.generate_actions` 内，先计算 trace 所需特征超集计划。
  - 调用一次统一特征构建，产出 `model_df_superset`。
  - 从 `model_df_superset` 投影出评分所需最小列作为 `model_df_runtime`（避免下游改动面过大）。
  - `decision_trace` 直接使用 `model_df_superset` 对应列，不再调用第二次 `build_model_df`。
- 数据/接口/模型
  - 不改变 `RegimeScoringEngine/SignalEngine/RiskEngine` 输入列语义。
  - 保留现有 trace 字段结构；仅调整其数据来源（同一份特征超集）。
  - 如需缓存，仅允许局部轻量缓存（timeframe + indicator_plan hash），不暴露新外部接口。
- 风险与权衡
  - 特征超集过大可能提高内存峰值；需通过列裁剪控制。
  - 需验证行为等价，避免“性能提升但信号漂移”。
  - 需确保 trace 字段完整性，不可因裁剪导致缺列。

## Acceptance
- 运行路径不再出现用于 trace 的第二次 `build_model_df`。
- 固定样本（建议 2024-01）下，`action`、`score_total`、`reason` 与核心 trace 证据字段保持一致（允许浮点微差）。
- 固定样本下，特征构建相关耗时下降，并在 validation 中给出命令、日志和对比数据。
- `python scripts/task_guard.py check XTR-SP-016` 通过，且验证记录完整。

## Notes
- 研讨输入：[`XTR-WS-006.md`](/Users/tiger/Development/GIt/xtrader/docs/03-delivery/workshops/items/XTR-WS-006.md)
- 关联背景：[`XTR-SP-015.md`](/Users/tiger/Development/GIt/xtrader/docs/03-delivery/specs/XTR-SP-015.md)
- 关键代码路径：
  - [`profile_action.py`](/Users/tiger/Development/GIt/xtrader/src/xtrader/strategies/builtin_strategies/profile_action.py)
  - [`pipeline.py`](/Users/tiger/Development/GIt/xtrader/src/xtrader/strategies/feature_engine/pipeline.py)
