# StrategyProfile 开发与回测操作手册（v0.3）

## 1. 目的
- 提供“新增/修改 profile -> 预编译校验 -> 回测 smoke -> 读取产物”的标准闭环。
- 降低新同学首次接手时的学习成本，避免在 `reports` 与 `runs` 路径语义上混淆。

## 2. 路径约定（先记住）
- 策略研究回测（ProfileAction + event-driven）产物：`reports/backtests/strategy/...`
- Runtime 编排与性能检查产物：`runs/...`
- 一句话：研究看 `reports`，运维/编排看 `runs`。

## 3. 最小上手步骤
### Step 1. 复制 profile 模板
- 模板文件：
  - `configs/strategy-profiles/templates/profile_v0.3.minimal.json`
- 建议新策略目录：
  - `configs/strategy-profiles/<your_strategy_id>/v0.3.json`

### Step 2. 先做预编译（不跑回测）
```bash
PYTHONPATH=src python - <<'PY'
from xtrader.strategy_profiles import StrategyProfilePrecompileEngine

profile = "configs/strategy-profiles/five_min_regime_momentum/v0.3.json"
result = StrategyProfilePrecompileEngine().compile(profile)
print("status:", result.status)
print("error_code:", result.error_code)
print("error_path:", result.error_path)
print("required_feature_refs:", len(result.required_feature_refs))
PY
```

### Step 3. 跑 BTCUSDT 5m smoke 回测
```bash
PYTHONPATH=src python scripts/run_profile_action_backtest_smoke.py \
  --profile configs/strategy-profiles/five_min_regime_momentum/v0.3.json \
  --start 2026-01-01T00:00:00Z \
  --end 2026-01-15T00:00:00Z \
  --run-id 20260402T040000Z_profile_smoke_demo
```

### Step 4. 检查关键产物
- 目标目录：`reports/backtests/strategy/profile_action/<run_id>/`
- 最小检查文件：
  - `summary.json`
  - `diagnostics.json`
  - `ledgers/trades.parquet`
  - `curves/equity_curve.parquet`
  - `timelines/signal_execution.parquet`
  - `run_manifest.json`

## 4. 调参入口（v0.3 常用）
- 状态判定：
  - `regime_spec.classifier.rules[].conditions`
- 分值计算：
  - `regime_spec.groups[].rules[].params`
  - `regime_spec.state_group_weights`
- 信号触发：
  - `signal_spec.entry_rules/exit_rules/hold_rules`
  - `signal_spec.cooldown_bars`
- 风险参数：
  - `risk_spec.size_model.params.fraction`
  - `risk_spec.stop_model`
  - `risk_spec.take_profit_model`

## 5. 常见错误码与排查
| 代码 | 来源阶段 | 含义 | 第一排查动作 |
|---|---|---|---|
| `PC-CFG-003` | profile_schema / runtime config | 配置类型、字段值、JSON 结构不合法 | 先看报错 `path`，对照 schema 字段类型修正 |
| `UNUSED_CLASSIFIER_INPUT` | profile_precompile | classifier `inputs` 声明但未被启用规则使用 | 检查 `classifier.rules[].conditions[].ref` 是否覆盖全部 inputs |
| `UNDECLARED_CLASSIFIER_REF` | profile_precompile | classifier 使用了未声明的 ref | 把 ref 加入 `classifier.inputs` 或修正规则引用 |
| `SCORE_FN_INPUT_ARITY_MISMATCH` | profile_precompile | `score_fn` 输入数量不匹配 | 对照 `score_fn` 预期输入角色补齐/删减 `input_refs` |
| `MISSING_REASON_CODE_MAPPING` | profile_precompile / signal runtime | 启用信号规则没有 reason 映射 | 在 `signal_spec.reason_code_map` 补齐 rule id |
| `SIGNAL_SCORE_RANGE_COVERAGE_GAP` | profile_precompile | 无 HOLD 兜底时区间未覆盖 `[-1,1]` | 补 HOLD 规则或补齐缺失区间 |
| `XTRSP007::PROFILE_PRECOMPILE_FAILED::*` | strategy init | `ProfileActionStrategy` 构造期预编译失败 | 优先读取内嵌的 `error_code/error_path/error_message` |
| `XTRSP005::MISSING_INPUT_COLUMN` | signal runtime | scoring 数据缺关键列 | 回查上游 `RegimeScoringEngine` 输出字段 |
| `XTRSP006::MISSING_MARKET_COLUMN` | risk runtime | 市场数据缺 `close/atr` 等字段 | 确认 `FeaturePipeline` 与 `market_df` 列契约 |
| `PC-TRI-001` / `PC-TRI-002` | runtime precompile/config | trial selector 非法或 scenario 冲突 | 检查 `trial_config` 与 `trial_selector` 一致性 |

## 6. 排查顺序建议（5 分钟版）
1. 先看 `error_code` 与 `error_path`（不要先改算法）。
2. 若是 precompile 错误，先让 `StrategyProfilePrecompileEngine().compile(...)` 单独通过。
3. 再跑 `run_profile_action_backtest_smoke.py`，确认链路与产物完整。
4. 最后再做参数调优，不要把“可运行性问题”和“效果问题”混在一起。

## 7. 相关文档
- profile 需求主文档：`docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
- 实施任务拆分：`docs/03-delivery/roadmap/implementation-tasks-v0.3.md`
- 系统架构总览：`docs/01-project/system-architecture.md`
- runtime 契约：`docs/03-delivery/specs/XTR-019.md`
