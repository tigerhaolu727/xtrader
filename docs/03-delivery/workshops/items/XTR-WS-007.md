# 快速可落地指标接入与双层结构同源派生规范 (XTR-WS-007)

- workshop_id: `XTR-WS-007`
- type: `requirement` # requirement | task | bug
- status: `approved` # draft | discussing | review | approved | deferred | rejected
- created_at: `2026-04-05`
- updated_at: `2026-04-06`
- owner: `codex`
- related_task_ids: `["XTR-SP-017"]`
- source: `docs/02-strategy/knowledge-base/indicator_family_knowledge_base_v1.md; user discussion(2026-04-05)`

## Background
- 当前策略 `ai_multi_tf_signal_v1` 已完成 TrackA/TrackB（secondary 与高周期条件）验证，后续进入“可替代传统指标”的扩展阶段。
- 已整理快速可落地指标候选（KAMA/MAMA/HT/TRIX/MFI/FRAMA）。
- 用户确认采用“项目标准指标族接口 + TA-Lib 计算内核”的落地方式，以兼顾准确性与工程一致性。
- 用户明确提出双层结构风险：若状态层独立重算主指标且参数不一致，会造成语义错位；因此需固化“同源派生”硬约束。

## Goal / Problem Statement
- 建立可执行的指标接入需求边界：新增快速可落地指标族时，统一遵循“指标值层 + 状态层”双层结构。
- 固化“同源派生（Source-bound Derivation）”实现规范，避免值层与状态层参数漂移。
- 给出第一批落地范围与验收标准，为后续任务 ID（Spec/Validation/实现）提供明确输入。

## Scope In
- 新增指标族接入规范：接口、参数、命名、注册、输出约束。
- TA-Lib 作为计算内核的接入原则与边界（包含不可用场景说明）。
- 双层结构规范：
  - 值层只负责连续值计算。
  - 状态层只负责同源派生的离散状态计算。
- 预编译校验需求（source 实例存在、同周期、禁止状态层重算主值）。
- 第一批优先指标（快速可落地）落地顺序建议：`KAMA/TRIX/MFI` 优先，`MAMA/HT` 次优先，`FRAMA` 单列实现说明。

## Scope Out
- 本研讨不直接实施代码改动（不在本研讨中创建 task/spec/validation 资产）。
- 本研讨不覆盖订单簿/逐笔类微观结构指标（OBI/QI/OFI/VPIN）的工程接入。
- 本研讨不定义最终交易参数（阈值、分数、gate 细节）。
- 本研讨不包含 TrackB 替代验证矩阵或任何回测执行内容。

## Constraints
- 必须兼容当前 feature-engine 指标族接口与注册机制。
- 必须遵循现有列命名与参数校验规范（XTR-018 已建立约束）。
- 状态层禁止独立重算主指标（禁止“第二真源”）。
- FRAMA 不依赖 TA-Lib 核心函数，需自实现或单独实现路径，不得阻断其余指标接入。

## Implementation Design (同源派生双层结构)

### A. 双层结构落地定义
- 指标值层（Value Layer）：
  - 负责计算连续数值输出（例如 `macd line/signal/hist`、`kama`、`trix`）。
  - 允许声明主参数（周期、平滑系数等）。
- 状态层（State Layer）：
  - 只负责从值层输出派生状态（例如 `near_cross`、`expand`、`reject_*`）。
  - 不允许重复声明主指标参数；仅允许状态判定参数。

### B. 同源派生实现规则（强制）
- 状态层必须声明 `source_instance_id`（或等价统一字段）并绑定到值层实例。
- 状态层与 source 必须同周期（same timeframe）。
- 状态层禁止独立重算主值（例如 `macd_state` 禁止再配置 `fast/slow/signal`）。
- 一个状态实例仅绑定一个 source，禁止混源派生。

### C. 预编译校验要求
- `source_instance_id` 存在且唯一可解析。
- source family 与 state family 匹配（白名单映射）。
- `state.timeframe == source.timeframe`。
- state 参数中无禁用主参数（如 `fast/slow/signal`）。
- 输出命名包含 source 签名，保证可追溯与排错可定位。

### D. 迁移与兼容策略
- Phase 1（兼容期）：
  - 保留旧配置可运行；
  - 命中“state 独立主参数”时输出 warning。
- Phase 2（强制期）：
  - 预编译直接 fail-fast；
  - 必须改为 `source_instance_id` 同源派生。

### E. 实施顺序（建议）
1. 先对 `macd/macd_state` 做同源改造，作为模板。
2. 再新增 `kama/trix/mfi` 的值层并接入 registry（计算层可使用 TA-Lib）。
3. 最后补 `*_state` 家族并完成预编译约束接入（source 绑定与禁用参数校验）。

### F. FRAMA 参数认知与当前决策（已确认）
- `N` 表示用于估计分形维度 `D` 的窗口 K 线数量（bar count），不等于平滑映射常数。
- `alpha = exp(-4.6 * (D - 1))` 中的 `4.6` 是 `D -> alpha` 的缩放常数，约等于 `ln(100)`，用于将 `D=2` 时的最小 `alpha` 映射到约 `0.01`。
- 该常数不表示“默认窗口 N=100”；`N=200` 也不意味着要改为 `ln(200)`。
- 若未来要调整该常数，应基于目标 `alpha_min`（或目标最慢等效周期）做设计，不按 `N` 直接联动。
- 当前决策：先不修改该常数，默认保持 `4.6`。

## Requirement Summary
- REQ-001: 新增指标族必须采用“值层 + 状态层”双层结构设计。
- REQ-002: 状态层必须通过 `source_instance_id`（或等价字段）绑定值层实例，且与 source 同周期。
- REQ-003: 状态层禁止重复声明并计算值层核心参数（如 `fast/slow/signal` 这类主指标参数）。
- REQ-004: 快速可落地指标默认使用 TA-Lib 作为计算内核；若指标不在 TA-Lib 核心函数内（如 FRAMA），需在 spec 中声明替代实现。
- REQ-005: 预编译阶段需新增/强化校验规则：source 存在性、family 匹配、同周期、禁用参数、命名可追溯。

## Acceptance Criteria
- ACC-001 (REQ-001): 知识库中存在明确双层结构定义，并标注为默认开发规范。
- ACC-002 (REQ-002): 在后续 spec 中，状态层配置模板必须包含且仅包含 `source_instance_id`（或等价字段）与状态判定参数。
- ACC-003 (REQ-003): 在后续 spec 中，状态层参数 schema 明确禁止主指标参数重复声明与重算。
- ACC-004 (REQ-004): 第一批指标接入 spec 明确标注 TA-Lib 依赖清单与 FRAMA 的非 TA-Lib 处理方案。
- ACC-005 (REQ-005): 预编译校验项包含 source 存在/同周期/family 匹配/禁用参数/命名追溯五项。

## Reproduction Steps (BUG required)
- precondition: _N/A_
- steps: _N/A_
- expected: _N/A_
- actual: _N/A_

## Risks
- TA-Lib 版本与平台兼容风险（安装/运行差异）可能影响实现节奏。
- 状态层迁移过程中，旧有 family（如 macd_state）可能存在历史参数兼容负担。
- 新指标引入后若缺少 warmup/NaN 对齐验证，可能导致回测偏差。

## Open Questions
- Q-001 [Resolved]: FRAMA 采用“纯项目内实现（不依赖 TA-Lib）”作为默认路线；如后续评估有必要再讨论第三方封装。

## Discussion Log
- `2026-04-05`: workshop created.
- `2026-04-05`: 用户要求启动需求研讨流程，并将前序讨论沉淀到研讨文档。
- `2026-04-05`: 确认快速可落地指标范围与 TA-Lib 接入方向。
- `2026-04-05`: 确认“值层 + 状态层”双层结构，并要求状态层采用同源派生，避免参数错配。
- `2026-04-05`: 已在知识库固化架构规范；本 workshop 作为后续 task/spec 的需求入口。
- `2026-04-05`: 范围收敛：仅做“新指标开发 + 同源派生双层结构重构”，移除 TrackB 验证相关目标。
- `2026-04-05`: FRAMA 讨论结论：`N` 与 `4.6` 含义独立；`4.6` 暂不调整，先按默认实现。
- `2026-04-06`: 关闭 Open Question：FRAMA 默认采用项目内实现；研讨状态提升为 approved。

## Quality Gate Checklist
- [x] Structure complete
- [x] No semantic ambiguity
- [x] No conflicts (scope/constraints/acceptance)
- [x] No unclear descriptions
- [x] Open questions resolved

## Promotion Decision
- decision: `approved` # pending | approved | deferred | rejected
- linked_task_id: `XTR-SP-017`
- approved_by: `user`
- approved_at: `2026-04-06`
- note: `需求范围收敛为：新指标开发 + 同源派生双层结构重构。`
