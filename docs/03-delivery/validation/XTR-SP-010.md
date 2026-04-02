# Validation Plan (XTR-SP-010)

## Planned Validation
- [x] `task_guard_check_pre_doc_update`：文档定稿后先过守门，再修改其他文档。
- [x] `profile_playbook_completeness_review`：操作手册包含新增 profile、校验、回测、产物读取四段闭环。
- [x] `error_code_handbook_review`：错误码说明覆盖 profile/precompile/runtime 高频场景并给出排障动作。
- [x] `commands_reproducibility_check`：文档示例命令可在本地执行（至少 precompile + smoke backtest）。
- [x] `architecture_alignment_check`：`system_architecture` 与新手册在主链路入口、产物路径约定上保持一致。

## Execution Log
- 2026-04-02：`python scripts/task_guard.py check XTR-SP-010`
  - 结果：通过（文档守门，允许进入文档实现阶段）。
- 2026-04-02：完成文档与模板收口实现
  - 新增：
    - `docs/02-strategy/playbooks/strategy-profile-playbook.md`
    - `configs/strategy-profiles/templates/profile_v0.3.minimal.json`
  - 更新：
    - `docs/01-project/system-architecture.md`
    - `docs/01-project/runtime-management.md`
    - `docs/03-delivery/specs/XTR-SP-010.md`
    - `docs/03-delivery/validation/XTR-SP-010.md`
- 2026-04-02：执行手册示例 precompile 命令（主 profile + 模板 profile）
  - 命令：`PYTHONPATH=src python - <<'PY' ... StrategyProfilePrecompileEngine().compile(...) ... PY`
  - 结果：
    - `configs/strategy-profiles/five_min_regime_momentum/v0.3.json -> SUCCESS`
    - `configs/strategy-profiles/templates/profile_v0.3.minimal.json -> SUCCESS`
- 2026-04-02：执行手册示例 smoke 回测命令
  - 命令：`PYTHONPATH=src python scripts/run_profile_action_backtest_smoke.py --profile configs/strategy-profiles/five_min_regime_momentum/v0.3.json --start 2026-01-01T00:00:00Z --end 2026-01-07T00:00:00Z --run-id 20260402T041500Z_xtr_sp_010_smoke`
  - 结果：`status=SUCCESS`，并生成标准产物目录：
    - `reports/backtests/strategy/profile_action/20260402T041500Z_xtr_sp_010_smoke`
  - 关键指标：
    - `trade_count=28`
    - `win_rate=0.10714285714285714`
    - `max_drawdown=-0.0009435748838168001`
    - `net_return=-0.0009435748838168001`
  - 备注：存在 `cpu_info.cc` 的 `sysctlbyname` warning，不影响任务验收。

## Evidence
- 文档与模板产物：
  - `docs/02-strategy/playbooks/strategy-profile-playbook.md`
  - `configs/strategy-profiles/templates/profile_v0.3.minimal.json`
- 架构与运行管理对齐：
  - `docs/01-project/system-architecture.md`（新增 `Profile 主链路约定（XTR-SP）`）
  - `docs/01-project/runtime-management.md`（新增与 XTR-SP 操作衔接）
- 命令复现证据：
  - precompile 成功（主 profile + 模板 profile）
  - smoke 回测成功并输出 `summary/diagnostics/trades/equity/signal_execution/run_manifest`
