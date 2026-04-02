# 文档信息架构优化方案（v1）

## 1. 背景
当前 `docs/` 同时承载了：
- 项目长期规范（架构、运行管理）
- 任务交付资产（spec/validation）
- 策略需求讨论底稿
- Agent 协作流程与会话记录

这些内容生命周期和受众不同，放在同一层级会造成检索成本上升和语义混淆。

## 2. 目标
1. 按“受众 + 生命周期”分层。
2. 保持 `spec/validation` 任务链路不受影响。
3. 迁移后收口为单一路径维护，避免双写漂移。

## 3. 推荐信息架构（目标态）
```text
docs/
  README.md
  01-project/
    overview.md
    system-architecture.md
    runtime-management.md
  02-strategy/
    discussions/
    requirements/
    playbooks/
  03-delivery/
    roadmap/
    specs/
    validation/
    backlog/
    templates/
  04-operations/
    runbooks/
    troubleshooting/
    perf/
  05-agent/
    processes/
    session-notes/
  06-history/
    archives/
```

## 4. 完成态目录清单（唯一维护入口）
| 当前路径 | 说明 |
|---|---|
| `docs/01-project/system-architecture.md` | 项目级长期文档（系统架构） |
| `docs/01-project/runtime-management.md` | 项目级长期文档（运行管理） |
| `docs/02-strategy/playbooks/strategy-profile-playbook.md` | 策略开发操作手册 |
| `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md` | 策略需求基线 |
| `docs/02-strategy/discussions/strategy-discussion-memory.md` | 策略讨论记忆 |
| `docs/02-strategy/discussions/trading-strategy-bg.md` | 策略背景资料 |
| `docs/03-delivery/roadmap/implementation-tasks-v0.3.md` | 交付路线图 |
| `docs/03-delivery/roadmap/implementation-ready-checklist.md` | 实现前检查清单 |
| `docs/03-delivery/specs/*` | 任务规格库 |
| `docs/03-delivery/validation/*` | 任务验证库 |
| `docs/03-delivery/templates/*` | Spec/Validation 模板 |
| `docs/03-delivery/backlog/*` | 交付待办池 |
| `docs/05-agent/processes/*` | 协作流程规范 |
| `docs/05-agent/session-notes/session-notes.md` | 会话日志索引 |

## 5. 分阶段落地（低风险）
### Phase A（立即可做，低风险）
状态：已完成（2026-04-02）
1. 增加 `docs/README.md` 导航（已完成）。
2. 冻结命名规则与目录职责。
3. 新文档按目标目录新建（已完成）。

### Phase B（迁移稳定文档）
状态：已完成（2026-04-02，含扩展项）
1. 迁移 `system_architecture`、`strategy_runtime_management`、`strategy_profile_playbook`。
2. 迁移 `FiveMinRegimeMomentumStrategy_requirements_v0.3` 到 `docs/02-strategy/requirements/`。
3. 统一 `implementation_tasks_v0.3` 主维护入口到 `docs/03-delivery/roadmap/`。
4. 完成主入口切换并冻结新目录职责。

### Phase C（迁移任务库）
状态：已完成（2026-04-02，含工具切换）
1. 整体迁移 `specs/validation` 到 `03-delivery/`。
2. 批量修复 cross-link 和工具脚本路径引用。
3. 清理旧路径兼容层，保留单一路径维护。

### Phase D（协作与待办收口）
状态：已完成（2026-04-02）
1. `session-notes` 迁移到 `docs/05-agent/session-notes/`。
2. `backlog` 迁移到 `docs/03-delivery/backlog/`。
3. 流程文档迁移到 `docs/05-agent/processes/`。
4. 删除旧兼容目录与 stub，保持结构单一清晰。
5. 建立 `docs/04-operations/` 目录骨架（`runbooks/`、`troubleshooting/`、`perf/`）。
6. 建立 `docs/02-strategy/discussions/` 主文档并接管策略讨论记忆。

## 6. 治理规则（建议冻结）
1. 一文一目的：需求、流程、验证、会话记录分离。
2. 任务号只出现于 `specs/validation`，项目长期文档不绑定任务号。
3. 任何迁移必须同时更新：
   - `docs/README.md`
   - 文内链接
   - 相关脚本/流程中的硬编码路径
4. 会话日志归属 `05-agent`，按月分卷维护。

## 7. 验收标准
1. 新同学可通过 `docs/README.md` 在 5 分钟内定位：
   - 项目总览
   - 策略上手手册
   - 当前任务 spec/validation
2. `spec/validation` 配对关系保持 1:1，无缺失。
3. 不存在“迁移后旧链接全部失效”的断链事故。
