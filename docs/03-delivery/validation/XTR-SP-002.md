# Validation Plan (XTR-SP-002)

## Planned Validation
- [x] `semantic_precompile_positive`：`v0.3.json` 语义编译通过并产出依赖字段。
- [x] `semantic_score_fn_arity_negative`：构造 `input_refs` 个数错误，触发 `SCORE_FN_INPUT_ARITY_MISMATCH`。
- [x] `semantic_classifier_ref_set_negative`：构造 `inputs/conditions` 不一致，触发 `UNUSED_CLASSIFIER_INPUT` 或 `UNDECLARED_CLASSIFIER_REF`。
- [x] `semantic_signal_priority_negative`：构造重复 `priority_rank`，触发 `SIGNAL_PRIORITY_RANK_DUPLICATE`。
- [x] `semantic_reason_code_map_negative`：缺失启用规则映射，触发 `MISSING_REASON_CODE_MAPPING`。
- [x] `semantic_score_coverage_negative`：移除 HOLD 且区间未覆盖 `[-1,1]`，触发 `SIGNAL_SCORE_RANGE_COVERAGE_GAP`。
- [x] `unit_tests_for_semantic_precompile`：新增/更新单测并通过。

## Execution Log
- 运行命令与结果（时间、状态、日志要点）
- 2026-04-02（CST）
  - 执行：`python scripts/task_guard.py new XTR-SP-002 --title "StrategyProfile 语义校验与预编译阻断"`
  - 结果：成功创建 `docs/03-delivery/specs/XTR-SP-002.md` 与 `docs/03-delivery/validation/XTR-SP-002.md`。
  - 执行：`python scripts/task_guard.py check XTR-SP-002`
  - 结果：通过（进入编码前流程守门通过）。
  - 执行：`PYTHONPATH=src pytest -q tests/unit/strategy_profiles/test_profile_schema_gate.py tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
  - 结果：通过（`12 passed`），覆盖 `XTR-SP-001` 回归与 `XTR-SP-002` 语义校验正负例。
  - 执行：`PYTHONPATH=src python -m py_compile src/xtrader/strategy_profiles/errors.py src/xtrader/strategy_profiles/models.py src/xtrader/strategy_profiles/loader.py src/xtrader/strategy_profiles/precompile.py src/xtrader/strategy_profiles/schema_registry.py src/xtrader/strategy_profiles/score_fn_registry.py src/xtrader/strategy_profiles/__init__.py`
  - 结果：通过（无语法错误）。
  - 执行：`PYTHONPATH=src pytest -q tests/unit/runtime/test_runtime_v1.py`
  - 结果：通过（`23 passed`），runtime 既有回归未受影响。
  - 执行：`python scripts/task_guard.py check XTR-SP-002`
  - 结果：通过（`✓ Spec & Validation check passed.`）。

## Evidence
- 链接或附件（如截图、日志路径、CI 链接）
- 规格文档：`docs/03-delivery/specs/XTR-SP-002.md`
- 验证文档：`docs/03-delivery/validation/XTR-SP-002.md`
- 代码资产：
  - `src/xtrader/strategy_profiles/precompile.py`
  - `src/xtrader/strategy_profiles/score_fn_registry.py`
- 测试资产：
  - `tests/unit/strategy_profiles/test_profile_semantic_precompile.py`
