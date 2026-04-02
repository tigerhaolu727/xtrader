# Spec/Validation 流程（子流程）

## 0. 定位
- 本流程是 `任务开发流程` 的子流程，覆盖“先文档后编码”的治理步骤。
- 适用阶段：主流程的第 `3/4/5/8/9` 步。
- 上游前置流程：`需求研讨流程`（研讨通过后才进入本流程）。

## 1. 执行步骤
1. 建立文档骨架  
确保存在：
- `docs/03-delivery/specs/<TASK_ID>.md`
- `docs/03-delivery/validation/<TASK_ID>.md`

2. 填写 Spec（先于编码）  
至少补齐：
- `Intent`
- `Requirement`
- `Design`
- `Acceptance`

3. 填写 Validation 计划（先于编码）  
在 `Planned Validation` 中列出可执行校验项（测试名/命令/目的）。

4. 评审待确认项  
把语义不明、冲突点、待确认问题显式列出，等待确认。

5. 文档守门（编码前）  
执行：`python scripts/task_guard.py check <TASK_ID>`。  
未通过时禁止进入编码。

6. 回填执行证据（编码后）  
在 `Execution Log` 记录命令与结果；在 `Evidence` 关联关键文件。

7. 二次守门（交付前）  
再次执行：`python scripts/task_guard.py check <TASK_ID>`。

## 2. 快速口令
- `先按 spec/validation 流程处理 XTR-SP-003`
- `先做 XTR-SP-004 的 spec/validation，不进入编码`
- `按 spec/validation 子流程复核 XTR-SP-005`

## 3. 与主流程关系
- 主流程文档：`docs/05-agent/processes/task_development_process.md`
- 关系：主流程负责端到端，子流程负责文档治理与证据闭环。
