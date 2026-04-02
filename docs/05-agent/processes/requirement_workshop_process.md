# 需求研讨流程（对话式）

## 0. 定位
- 本流程用于需求/任务/BUG 的文字描述收敛，形成标准化研讨文档。
- 流程名称固定为：`需求研讨流程`。
- 该流程是 `任务开发流程` 的前置门禁：研讨未通过，不得进入任务开发流程。

## 1. 存储位置与命名
- 目录：`docs/03-delivery/workshops/`
- 条目：`docs/03-delivery/workshops/items/XTR-WS-XXX.md`
- 类型：`requirement | task | bug`
- 状态：`draft -> discussing -> review -> approved`

## 2. 启动口令（推荐）
- `启动需求研讨流程：<标题>`
- `启动任务研讨流程：<标题>`
- `启动BUG研讨流程：<标题>`

## 3. 对话式执行步骤
1. 创建研讨骨架
   - 执行（自动编号）：`python scripts/workshop_guard.py new --auto-id --title "..." --type <requirement|task|bug>`
   - 或分两步：`python scripts/workshop_guard.py next-id` -> `python scripts/workshop_guard.py new <WORKSHOP_ID> --title "..." --type <...>`
   - 同步更新：`docs/03-delivery/workshops/index.md`

2. 进入讨论态（discussing）
   - Agent 以对话方式逐条澄清：目标、范围、约束、验收、风险、开放问题。
   - 每轮讨论后，Agent 回写研讨并输出“未决问题清单”。

3. 形成评审态（review）
   - 当未决问题显著收敛后，进入 `review`。
   - 执行基础校验：`python scripts/workshop_guard.py check <WORKSHOP_ID>`。

4. 完成态守门（ready gate）
   - 执行最终守门：`python scripts/workshop_guard.py check <WORKSHOP_ID> --ready`
   - 必须全部通过：
     - 结构完整
     - 无语义不明
     - 无冲突
     - 无描述不清
     - 开放问题已解决

5. 通过并提升（approved）
   - `status=approved` 且 `decision=approved`。
   - 仅此状态才可进入 `任务开发流程`。

## 4. 质量门禁定义
### 4.1 结构门禁（必过）
- 必填章节齐全：背景、目标、范围、约束、需求摘要、验收标准、风险、开放问题等。

### 4.2 语义门禁（必过）
- 不允许模糊词未量化（如“尽快/明显/适当”等）。
- 不允许范围冲突（`Scope In` 与 `Scope Out` 重叠）。
- 需求与验收须可追溯（`REQ-XXX` 必须在 `ACC` 中映射）。

### 4.3 BUG 补充门禁（type=bug 必过）
- `precondition/steps/expected/actual` 四项必须具体、可复现，不可为占位值。

## 5. 与任务开发流程的关系
- 下游流程：`docs/05-agent/processes/task_development_process.md`
- 进入条件：
  1. `workshop_guard --ready` 通过；
  2. 研讨状态为 `approved`；
  3. 无未决问题。

## 6. 默认行为
- 当你明确提到“启动需求研讨流程”时，助手默认先讨论、后回写、再守门。
- 守门不通过时，助手必须继续澄清，不得跳转到任务开发流程。
