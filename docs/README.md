# Docs 导航（当前）

## 当前结构
- `docs/01-project/`：项目级长期文档（总览、系统架构、运行管理）。
- `docs/02-strategy/`：策略需求基线、讨论文档与策略开发手册。
- `docs/03-delivery/`：任务交付资产（roadmap/specs/validation/backlog）。
- `docs/04-operations/`：运维文档区（runbooks/troubleshooting/perf）。
- `docs/05-agent/`：协作流程与会话日志。
- `docs/06-history/`：历史归档区（非主维护入口）。
- `docs/03-delivery/templates/`：Spec/Validation 模板。

## 推荐阅读顺序（新同学）
1. `docs/01-project/overview.md`
2. `docs/01-project/system-architecture.md`
3. `docs/01-project/runtime-management.md`
4. `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
5. `docs/02-strategy/playbooks/strategy-profile-playbook.md`
6. `docs/03-delivery/roadmap/implementation-tasks-v0.3.md`
7. 对应任务文档：`docs/03-delivery/specs/<TASK>.md` + `docs/03-delivery/validation/<TASK>.md`
8. 协作与待办：`docs/05-agent/session-notes/session-notes.md` + `docs/03-delivery/backlog/`

## 规范说明
- 任务流程工具 `task_guard.py` 仅写入/校验：
  - `docs/03-delivery/specs`
  - `docs/03-delivery/validation`
- 会话日志按月维护在 `docs/05-agent/session-notes/<YYYY-MM>.md`。
- 迁移与治理基线见：`docs/docs_information_architecture_optimization_plan.md`。
