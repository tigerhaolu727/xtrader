# 任务开发流程（标准）

## 0. 适用范围
- 本流程用于 `XTR-SP-XXX` 等任务型开发。
- 流程名称固定为：`任务开发流程`。
- 前置门禁：必须先完成 `需求研讨流程` 并达到 `approved` 状态。
- 需求研讨流程见：
  - `docs/05-agent/processes/requirement_workshop_process.md`（流程名：`需求研讨流程`）。
- 文档治理子流程见：
  - `docs/05-agent/processes/spec_validation_process.md`（流程名：`spec/validation 流程`）。

## 1. 标准步骤（1-10）
1. 研讨前置确认  
确认已满足以下条件：
- `docs/03-delivery/workshops/items/<WORKSHOP_ID>.md` 已存在；
- 执行 `python scripts/workshop_guard.py check <WORKSHOP_ID> --ready` 通过；
- 研讨状态为 `approved`。

2. 创建任务  
执行：`python scripts/task_guard.py new <TASK_ID> --title "..."`。

3. 只写文档，不写代码  
先完成：
- `docs/03-delivery/specs/<TASK_ID>.md`
- `docs/03-delivery/validation/<TASK_ID>.md`

4. 文档评审与确认  
梳理语义不明、冲突点、待确认项，等待确认后再进入编码。

5. 文档守门  
执行：`python scripts/task_guard.py check <TASK_ID>`。  
未通过禁止编码。

6. 开发实现  
严格按当前任务范围实现，不跨任务扩写。

7. 执行验证  
运行本任务对应测试、编译检查、必要回归测试。

8. 回填验证证据  
更新 `docs/03-delivery/validation/<TASK_ID>.md`：
- `Planned Validation` 勾选
- `Execution Log` 命令与结果
- `Evidence` 关联文件

9. 交付前再次守门  
再次执行：`python scripts/task_guard.py check <TASK_ID>`。

10. 会话收尾  
追加 `docs/05-agent/session-notes/<YYYY-MM>.md`，记录完成项、问题与下一步（入口索引：`docs/05-agent/session-notes/session-notes.md`）。

## 2. 未来调用方式（约定）
- 研讨流程调用口令（推荐）：
  - `启动需求研讨流程：<标题>`
  - `启动任务研讨流程：<标题>`
  - `启动BUG研讨流程：<标题>`
- 调用口令（推荐）：
  - `按任务开发流程执行 XTR-SP-003`
  - `用任务开发流程推进 XTR-SP-004`
  - `按任务开发流程从文档阶段开始做 XTR-SP-005`
- 子流程调用口令（推荐）：
  - `先按 spec/validation 流程处理 XTR-SP-006`
  - `先做 XTR-SP-007 的 spec/validation，不进入编码`
- 若只想走流程前半段（不编码）：
  - `按任务开发流程先做 spec/validation，任务是 XTR-SP-006`

## 3. 默认行为
- 当你明确提到“按任务开发流程”时，助手默认按 1->10 顺序执行。
- 若缺少 `approved` 研讨，助手会先引导进入 `需求研讨流程`，不直接创建任务。
- 若你要求“先不开发代码”，助手会停在第 5 步并等待确认。
