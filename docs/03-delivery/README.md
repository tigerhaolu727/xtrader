# 03-delivery（任务交付区）

## 目录说明
- `workshops/`：需求/任务/BUG 的对话式研讨文档（任务开发前置输入）。
- `roadmap/`：需求拆分与里程碑路线图。
- `specs/`：任务规格文档（`XTR-*`、`XTR-SP-*`）。
- `validation/`：任务验证与证据文档（与 `specs` 配对）。
- `backlog/`：待迭代项与延后事项（交付侧积压池）。
- `templates/`：`task_guard.py` 使用的 Spec/Validation 模板。

## 当前状态（已切换）
- 本目录已成为任务交付的唯一流程入口。
- 研讨守门脚本：
  - `python scripts/workshop_guard.py next-id`
  - `python scripts/workshop_guard.py new --auto-id --title \"...\" --type <requirement|task|bug>`
  - `python scripts/workshop_guard.py check <WORKSHOP_ID> --ready`
- `task_guard.py` 当前写入/校验路径：
  - `docs/03-delivery/specs`
  - `docs/03-delivery/validation`
- 旧入口 `docs/specs` 与 `docs/validation` 已删除，避免双写与路径漂移。

## 迁移注意事项
1. 新增与修改任务文档时，只改 `03-delivery` 下对应文件。
2. 若发现旧路径引用，直接修正到 `03-delivery`，不再新增兼容 stub。
