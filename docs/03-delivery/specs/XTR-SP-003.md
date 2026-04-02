# FeaturePipeline 依赖驱动扩展与多周期对齐输入准备 (XTR-SP-003)

## Intent
- `XTR-SP-002` 已可产出 `required_feature_refs` 与 `required_indicator_plan_by_tf`，但当前 `FeaturePipeline` 仍是单周期接口，无法直接消费这些编译产物。
- 若不补这层能力，后续 `RegimeScoringEngine` 无法在统一入口拿到“按需特征 + 多周期对齐后输入”。
- 本任务目标是在不破坏现有单周期能力的前提下，新增 profile 依赖驱动的多周期特征构建能力。

## Requirement
### 功能目标
- 新增 `FeaturePipeline` profile 模式入口：
  - 输入：`bars_by_timeframe + required_indicator_plan_by_tf + required_feature_refs + decision_timeframe + alignment_policy`
  - 输出：决策周期 DataFrame，包含按 `feature_ref` 命名的可直接取值列。
- 支持 `alignment_policy.mode=ffill_last_closed`：
  - 仅使用“已收盘”高周期值；
  - 对齐到 `decision_timeframe`；
  - 支持 `max_staleness_bars_by_tf` 过期剔除。
- 兼容单周期特例：仅决策周期引用时不做跨周期对齐。

### 非目标 / 范围外
- 不在本任务实现评分计算（`XTR-SP-004`）。
- 不在本任务实现信号与风险输出（`XTR-SP-005/006`）。
- 不在本任务改动 runtime 执行主入口（本任务聚焦 `FeaturePipeline` 能力）。

### 输入输出 / 接口
- 新增接口（建议）：
  - `FeaturePipeline.build_profile_model_df(...) -> pd.DataFrame`
- 输入字段：
  - `bars_by_timeframe: dict[str, pd.DataFrame]`
  - `required_indicator_plan_by_tf: dict[str, list[dict]]`
  - `required_feature_refs: list[str]`
  - `decision_timeframe: str`
  - `alignment_policy: dict`
- 输出字段：
  - 基础列：决策周期 `timestamp/symbol/open/high/low/close/volume`
  - 特征列：以 `feature_ref` 为列名（如 `f:5m:ema_12:value`）

## Design
### 核心思路与架构
- 两阶段执行：
  1. 按 `required_indicator_plan_by_tf` 在各周期独立计算 model_df；
  2. 按 `required_feature_refs` 拉取并对齐到 `decision_timeframe`。
- 对齐策略采用 `merge_asof(backward)` + “已收盘时间戳”约束，杜绝前视。

### 数据/接口/模型
- `feature_ref` 解析：`f:<timeframe>:<instance_id>:<output_key>`。
- 物理列映射：
  - 通过 indicator family + params 计算输出列前缀；
  - 根据 `output_key` 选择目标物理列（如 `macd hist`）。
- staleness 语义：
  - 若配置 `max_staleness_bars_by_tf[tf]=N`，超过 `N` 个决策 bars 置空。

### 风险与权衡
- 风险 1：多周期对齐容易引入前视偏差。
  - 处理：严格用“source open_time + source duration <= decision open_time”判定已收盘。
- 风险 2：feature_ref 到物理列映射不一致。
  - 处理：统一使用 indicator registry 计算输出列名，避免硬编码。
- 风险 3：新增接口影响现有单周期行为。
  - 处理：保留原 `build_model_df` 不变，新增 profile 专用方法。

## Acceptance
- `FeaturePipeline` 可直接消费 `XTR-SP-002` precompile 产物并返回决策周期输入表。
- 单周期场景回归通过（不影响现有测试）。
- 多周期场景满足：
  - 高周期特征在“第一根可用决策 bar”才出现；
  - staleness 超限后特征置空；
  - 缺失必要 timeframe 或 feature_ref 映射时 fail-fast。
- 自动化测试覆盖正例与关键负例。

## Notes
- 依赖：
  - `docs/03-delivery/specs/XTR-SP-002.md`
  - `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
- 默认决策：
  - 本任务无新增阻断待确认项，按流程直接进入实现。
