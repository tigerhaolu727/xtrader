# StrategyProfile Schema 冻结与校验接入 (XTR-SP-001)

## Intent
- 当前 `FiveMinRegimeMomentumStrategy v0.3` 已形成稳定需求，但 `RegimeSpec / SignalSpec / RiskSpec` 仍主要停留在需求文档描述层，缺少“可执行 schema 契约 + 统一校验入口”。
- 如果不先冻结 schema 并接入 precompile 校验，后续 `XTR-SP-002+` 会出现配置语义漂移、错误暴露过晚、联调返工成本高的问题。
- 本任务目标是建立“配置先校验、失败前置”的第一道守门，为后续引擎开发提供稳定输入契约。

## Requirement
### 功能目标
- 将 v0.3 需求中的三类配置固化为正式 schema（JSON Schema）：
  - `RegimeSpec`
  - `SignalSpec`
  - `RiskSpec`
- 在 precompile 流程中接入 schema 校验入口，确保 profile 在进入运行链路前完成结构校验。
- 对 schema 失败返回稳定、可定位的错误信息（至少包含路径与原因）。

### 非目标 / 范围外
- 不在本任务实现评分逻辑、信号逻辑、风险计算逻辑（属于 `XTR-SP-004/005/006`）。
- 不在本任务实现完整 feature 依赖编译与规则冲突校验（属于 `XTR-SP-002`）。
- 不在本任务变更 runtime 执行策略（`ThresholdIntradayStrategy` 下线属于 `XTR-SP-008`）。

### 输入输出 / 接口
- 输入：
  - `configs/strategy-profiles/five_min_regime_momentum/v0.3.json`
  - 需求文档中的 v0.3 FROZEN 条款与 schema 草案
- 输出：
  - 正式 schema 文件（项目内固定目录）
  - precompile 侧 schema 校验接入点
  - 基础单测（有效配置通过、无效配置失败）

## Design
### 核心思路与架构
- 采用“双层校验”设计：
  1. Schema 层：校验结构、字段类型、必填项、枚举与边界；
  2. 语义层：保留给 `XTR-SP-002` 做 cross-field 与依赖一致性校验。
- 本任务仅负责第一层，确保“格式正确”先成立。

### 数据/接口/模型
- schema 组织建议（待实现时按项目目录规范落位）：
  - `strategy_profile.v0.3.schema.json`（root schema）
  - `regime_spec.v0.3.schema.json`
  - `signal_spec.v0.3.schema.json`
  - `risk_spec.v0.3.schema.json`
- precompile 接入点：
  - 在 profile 解析早期执行 schema 校验；
  - 失败直接 fail-fast，不进入后续编译步骤。
- 约束来源：
  - 以 `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md` 第 21 节与第 25 节为主，冲突时以第 25 节 FROZEN 为准。

### 风险与权衡
- 风险 1：需求文档中部分字段未来仍可能微调。
  - 处理：schema 版本化（v0.3 固定），后续改动通过版本升级处理。
- 风险 2：过早把语义校验塞进 schema，导致复杂且难维护。
  - 处理：本任务只做结构校验，语义校验放到 `XTR-SP-002`。
- 风险 3：错误码体系尚未完全统一。
  - 处理：本任务先确保错误可定位；错误码细化在 `XTR-SP-002` 完成。

## Acceptance
- 存在正式 schema 文件，并可用于程序化校验。
- `v0.3.json` 通过 schema 校验。
- 人工构造的非法配置（缺字段、错类型、非法枚举、越界值）会在 schema 阶段失败。
- precompile 在 schema 失败时 fail-fast，不进入后续编译步骤。
- 至少有一组自动化测试覆盖通过/失败两条路径。

## Notes
- 依赖文档：
  - `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
  - `docs/03-delivery/roadmap/implementation-tasks-v0.3.md`
- 关联任务：
  - 上游：无
  - 下游：`XTR-SP-002`
- 约束：
  - 本任务完成后，需先做语义冲突审查并经用户确认，再进入编码实现阶段。

## Confirmed Decisions（已确认）
1. Schema 文件落位目录固定为：`src/xtrader/strategy_profiles/schemas/`。
2. 本任务同时提供 `Profile Root Schema`，并引用 `RegimeSpec/SignalSpec/RiskSpec` 子 schema。
3. Root 层保持严格校验（`additionalProperties=false`），仅 `metadata` 放开扩展（`additionalProperties=true`）。
4. Schema 校验失败在 `XTR-SP-001` 统一映射 `PC-CFG-003`，错误码细分在 `XTR-SP-002` 落地。
5. 校验分层冻结：`XTR-SP-001` 仅做结构/字段边界校验；跨对象语义一致性放到 `XTR-SP-002`。
