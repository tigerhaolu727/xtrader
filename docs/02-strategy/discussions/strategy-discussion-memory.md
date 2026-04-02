# Strategy Discussion Memory

> 用于沉淀跨任务、长期有效的策略讨论上下文，避免重复讨论与语义漂移。

## 1. 讨论目的
- 记录策略设计讨论中的稳定共识、未决问题和决策演进。
- 区分“讨论记忆”和“任务交付文档”：
  - 任务落地细节进入 `docs/03-delivery/specs|validation`；
  - 跨任务的长期结论进入本文件。

## 2. 来源材料
- 需求与设计基线：
  - `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
  - `docs/03-delivery/roadmap/implementation-tasks-v0.3.md`
- 架构与运行文档：
  - `docs/01-project/system-architecture.md`
  - `docs/01-project/runtime-management.md`
- 会话记录：
  - `docs/05-agent/session-notes/session-notes.md`（索引）
  - `docs/05-agent/session-notes/<YYYY-MM>.md`（月度分卷）

## 3. 当前共识
- 主执行链路保持配置驱动：`FeaturePipeline -> RegimeScoringEngine -> SignalEngine -> RiskEngine -> Action Output`。
- 任务交付文档统一使用 `docs/03-delivery/specs` + `docs/03-delivery/validation`。
- 会话日志归属 `docs/05-agent/session-notes/`，并采用月度分卷维护。
- backlog 归属 `docs/03-delivery/backlog/`，用于“讨论后、待交付”的积压项管理。

## 4. 策略结构拆解（讨论视角）
- 策略层：
  - 关注 StrategyProfile 的行为定义、参数契约与版本边界。
- 引擎层：
  - 关注评分、信号、风控的职责边界与数据契约。
- 运行层：
  - 关注回测执行时序、产物契约、可复现与可观测性。
- 文档层：
  - 关注信息架构、路径统一、协作流程与证据闭环。

## 5. 关键不一致点（持续维护）
- 目录口径是否已统一（新旧路径是否仍存在双写）。
- 需求文档与实现任务文档是否出现语义冲突。
- 讨论结论是否已回写到正式 spec/validation 或长期文档。

## 6. 待决问题清单（持续维护）
- 哪些讨论项应升级为 backlog 卡片。
- 哪些 backlog 项具备条件升级为 `XTR-*` / `XTR-SP-*` 任务。
- 哪些历史兼容路径可以进一步下线（由 stub 过渡到移除）。

## 7. 决策日志（简版）
- 2026-03-31：建立独立策略讨论记忆文件，用于沉淀长期讨论上下文。
- 2026-04-02：文档信息架构收口，完成 `03-delivery` 与 `05-agent` 主入口统一。

## 8. 讨论模板
```markdown
### [日期/时段]
- 主题：
- 背景：
- 当前结论：
- 仍有分歧：
- 待决问题：
- 下一步动作：
```
