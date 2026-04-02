# Validation Plan (XTR-SP-001)

## Planned Validation
- [x] `schema_validation_positive`：使用 `configs/strategy-profiles/five_min_regime_momentum/v0.3.json` 做正例校验，确认通过。
- [x] `schema_validation_negative_missing_required`：删除必填字段，确认校验失败且能定位路径。
- [x] `schema_validation_negative_enum_type_range`：构造枚举非法/类型错误/数值越界，确认校验失败。
- [x] `precompile_fail_fast_on_schema_error`：schema 失败时 precompile 直接失败，不进入后续步骤。
- [x] `unit_tests_for_schema_loader`：新增/更新单测并通过。
- [x] 数据准备：复用仓库内现有 `v0.3.json`，并在测试中构造最小坏样例。

## Execution Log
- 2026-04-02（CST）
  - 执行：`python scripts/task_guard.py new XTR-SP-001 --title "StrategyProfile Schema 冻结与校验接入"`
  - 结果：成功创建 `docs/03-delivery/specs/XTR-SP-001.md` 与 `docs/03-delivery/validation/XTR-SP-001.md`。
  - 执行：`python scripts/task_guard.py check XTR-SP-001`
  - 结果：通过（当前为文档阶段，尚未进入代码实现与测试执行）。
  - 执行：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_profile_schema_gate.py`
  - 结果：通过（`6 passed`），覆盖正例、缺字段、枚举/边界错误、precompile fail-fast 与 schema 资产加载。
  - 执行：`PYTHONPATH=src python -m py_compile src/xtrader/strategy_profiles/errors.py src/xtrader/strategy_profiles/models.py src/xtrader/strategy_profiles/loader.py src/xtrader/strategy_profiles/precompile.py src/xtrader/strategy_profiles/schema_registry.py src/xtrader/strategy_profiles/__init__.py`
  - 结果：通过（无语法错误）。
  - 执行：`python scripts/task_guard.py check XTR-SP-001`
  - 结果：通过（`✓ Spec & Validation check passed.`）。

## Evidence
- 规格文档：`docs/03-delivery/specs/XTR-SP-001.md`
- 验证文档：`docs/03-delivery/validation/XTR-SP-001.md`
- 关联需求：`docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
- 代码资产：
  - `src/xtrader/strategy_profiles/models.py`
  - `src/xtrader/strategy_profiles/loader.py`
  - `src/xtrader/strategy_profiles/precompile.py`
  - `src/xtrader/strategy_profiles/schemas/*.schema.json`
- 测试资产：
  - `tests/unit/strategy_profiles/test_profile_schema_gate.py`
