# 项目总览（Overview）

## 1. 项目定位
- `xtrader` 是以事件驱动回测与策略配置化为核心的交易研究工程。
- 当前主线目标：通过 `StrategyProfile` 实现“尽量少改代码、主要改配置”的策略研发闭环。

## 2. 核心文档入口
- 系统架构：`docs/01-project/system-architecture.md`
- 运行与配置管理：`docs/01-project/runtime-management.md`
- 策略配置上手手册：`docs/02-strategy/playbooks/strategy-profile-playbook.md`
- 当前策略需求基线：`docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
- 任务交付区：`docs/03-delivery/`

## 3. 交付与协作约定
- 任务文档统一入口：
  - Spec：`docs/03-delivery/specs/<TASK_ID>.md`
  - Validation：`docs/03-delivery/validation/<TASK_ID>.md`
- backlog 统一入口：`docs/03-delivery/backlog/`
- 会话日志入口：`docs/05-agent/session-notes/session-notes.md`（按月追加到 `docs/05-agent/session-notes/<YYYY-MM>.md`）
- 任务推进遵循：`docs/05-agent/processes/task_development_process.md`
- 文档守门工具：`python scripts/task_guard.py check <TASK_ID>`

## 4. 产物路径约定
- 策略研究与回测产物：`reports/backtests/strategy/...`
- runtime 编排与性能产物：`runs/...`
