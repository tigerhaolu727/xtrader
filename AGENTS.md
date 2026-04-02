# AGENT USAGE RULES

本项目采用 “Spec 维护人 + 验证守门人” 双角色流程，即使是单人开发，也必须按以下约束执行：

1. **任何需求或问题都必须创建任务 ID**  
   - 运行 `python scripts/task_guard.py new <task-id> --title "任务描述"`  
   - 该命令会在 `docs/03-delivery/specs/<task-id>.md` 与 `docs/03-delivery/validation/<task-id>.md` 生成模板；未生成前不得改代码。

2. **先写 Spec 再编码**  
   - 在对应的 Spec 文件中，最少填写 “Intent / Requirement / Design / Acceptance” 四节。  
   - 修改代码前运行 `python scripts/task_guard.py check <task-id>`；未通过检查禁止继续。

3. **验证守门人必须记录验证证据**  
   - 在 `docs/03-delivery/validation/<task-id>.md` 中写明计划的验证项及实际执行命令/结果。  
   - `task_guard.py check` 会确保存在“Planned Validation”和“Execution Log”小节，缺失则视为不合规。

4. **提交与评审**  
   - Commit 信息或 PR 描述必须引用对应任务 ID。  
   - 若尚未补齐 Spec/验证文档，须先补齐再提交。

5. **Session Notes**  
   - 每次会话结束前，在 `docs/05-agent/session-notes/<YYYY-MM>.md` 追加记录，并链接到对应任务 ID（入口索引见 `docs/05-agent/session-notes/session-notes.md`）。

> 违反以上任一规则，Agent 必须中止工作，先补齐 Spec/验证后再继续。

## 目录速览

- `docs/03-delivery/specs/`：按任务 ID 存放规格文档。  
- `docs/03-delivery/validation/`：按任务 ID 存放验证计划与执行记录。  
- `docs/03-delivery/templates/`：Spec 与 Validation 模板。  
- `scripts/task_guard.py`：生成模板与进行流程校验。

请在每次任务开始时主动阅读对应 Spec/Validation，并在实现完成后更新验证记录。任何未经 `task_guard.py check` 放行的任务视为违规。

## 交互流程

1. **需求输入**：用户用自然语言描述需求或 Bug。  
2. **助手创建资产**：助手负责选择任务 ID，运行 `task_guard.py new`，并按描述填写初版 Spec 与 Validation。  
3. **用户确认**：用户审阅并确认 Spec/Validation；若需修改，由助手更新文档。  
4. **执行开发**：只有在用户确认并通过 `task_guard.py check` 后，助手才可动手编写或修改代码。  
5. **复核与记录**：实现结束后更新验证日志、session notes，并再次执行 `task_guard.py check` 作为交付前守门。

此流程适用于所有功能开发与缺陷修复，确保始终遵循“先 Spec、再验证、再编码”的约束。

## 会话定制约定

- 仅当用户消息开头明确包含“需求”、“BUG”等字样时，才进入上述 Spec/Validation 流程。其他普通提问或对话可直接答复，无需触发任务流程。该约定需在未来会话中继续沿用。
