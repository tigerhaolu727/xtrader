# workshops（需求/任务/BUG 文字研讨）

本目录用于沉淀“需求/任务/BUG 的原始文字描述”，作为后续任务开发流程的输入。

## 目录结构
- `items/`：每条研讨文档（`XTR-WS-XXX.md`）。
- `templates/workshop-template.md`：研讨模板。
- `index.md`：研讨索引与状态追踪。

## 流程入口
- 流程名：`需求研讨流程`
- 流程文档：`docs/05-agent/processes/requirement_workshop_process.md`
- 自动编号：`python scripts/workshop_guard.py next-id`
- 创建研讨（自动编号）：`python scripts/workshop_guard.py new --auto-id --title "..." --type <requirement|task|bug>`
- 校验脚本：`python scripts/workshop_guard.py check <WORKSHOP_ID>`

## 状态说明
- `draft`：已创建草稿。
- `discussing`：对话澄清中。
- `review`：待守门校验。
- `approved`：可进入任务开发流程。
- `deferred/rejected`：暂缓/拒绝。
