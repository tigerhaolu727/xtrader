# 文档与运维收口 (XTR-SP-010)

## Intent
- `XTR-SP-001 ~ XTR-SP-009` 已完成 profile 引擎闭环与 E2E 验证，但“新增策略如何落地、常见错误如何排查、回测产物路径如何约定”仍分散在多处文档与会话记录中。
- 若缺少统一操作手册与错误码索引，新同学虽然能读懂设计，但难以独立完成“新增 profile -> 验证 -> 回测”全过程。
- 本任务目标是完成文档与运维层收口，形成可直接执行的一套标准说明。

## Requirement
### 功能目标
- 补充 profile 引擎主链路的“开发到回测”操作手册，覆盖：
  - profile 新增/复制模板
  - precompile 校验
  - 回测 smoke 命令
  - 产物路径与结果读取
- 补充错误码与排查手册（最小可用集），覆盖：
  - profile/precompile 失败
  - runtime 配置失败
  - 输入数据缺失或格式错误
  - diagnostics 降级（`NOT_AVAILABLE`）语义
- 更新架构文档，明确以下冻结约定：
  - 主链路策略入口为 `ProfileActionStrategy`；
  - 策略研究回测产物落 `reports/backtests/strategy/...`；
  - Runtime 编排与性能检查产物落 `runs/...`。

### 非目标 / 范围外
- 不在本任务新增策略引擎能力或修改运行逻辑。
- 不在本任务重构现有 runtime/backtest 文件结构。
- 不在本任务新增 CI workflow，仅补充文档和使用说明。

### 输入输出 / 接口
- 输入：
  - 现有实现与文档（`XTR-SP-001 ~ XTR-SP-009`、`XTR-019`）。
  - 已可运行脚本（含 profile smoke/backtest 脚本）。
- 输出：
  - 可直接给新同学使用的 profile 开发与回测指南文档。
  - 错误码速查与排障步骤文档。
  - 架构文档的路径与主链路约定更新。

## Design
### 核心思路与架构
- 采用“单入口手册 + 架构索引对齐 + 验证证据回填”方式收口：
  1. 产出统一操作手册（新增策略、校验、回测、调参、读产物）；
  2. 在系统架构文档中补齐主链路与目录约定，避免与旧路径混淆；
  3. 在 validation 中记录“文档命令可执行”的最小证据链。

### 数据/接口/模型
- 推荐新增文档包含：
  - `Profile` 模板路径与命名约定；
  - 常用命令模板；
  - 输出目录对照（`reports` vs `runs`）；
  - 常见错误码表（code/stage/含义/处理）。
- 文档中的命令示例必须可在当前仓库执行并成功（至少 smoke 粒度）。

### 风险与权衡
- 风险 1：文档与代码后续漂移。
  - 处理：手册引用具体脚本与路径，避免复制粘贴实现细节。
- 风险 2：错误码覆盖过度追求“全量”导致维护负担。
  - 处理：本任务先冻结“高频最小集”，后续按问题增量扩展。
- 风险 3：新旧路径并存导致认知冲突。
  - 处理：明确声明“研究回测看 `reports`，runtime 运维看 `runs`”。

## Acceptance
- 存在一份面向新同学的 profile 开发/回测指南，且步骤从配置到回测可闭环执行。
- 架构文档中已明确主链路入口与产物路径约定（`reports` vs `runs`）。
- 存在错误码与排查说明，覆盖 profile/precompile/runtime 常见失败场景。
- 文档示例命令可在本地仓库最小复现（至少 precompile + smoke backtest）。
- `python scripts/task_guard.py check XTR-SP-010` 通过。

## Notes
- 依赖：
  - `docs/03-delivery/specs/XTR-SP-009.md`
  - `docs/03-delivery/specs/XTR-019.md`
  - `docs/03-delivery/roadmap/implementation-tasks-v0.3.md`
- 里程碑对齐：
  - 本任务完成后，`XTR-SP-001 ~ XTR-SP-010` 全部收口。
