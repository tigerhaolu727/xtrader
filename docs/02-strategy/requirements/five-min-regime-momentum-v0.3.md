# FiveMinRegimeMomentumStrategy 需求说明 v0.3

> 命名说明：`FiveMinRegimeMomentumStrategy` 为历史命名沿用，不代表策略引擎采用固定五维结构；v0.3 以 `RegimeSpec.groups[].rules[]` 的可配置分组与规则为准。

## 0. 规范级别约定
- `FROZEN`：实现必须遵守（MUST），偏离视为不符合本版本需求。
- `GUIDELINE`：实现建议遵守（SHOULD），允许在有充分理由时偏离。
- `BACKLOG`：后续讨论（MAY），不纳入 v0.3 实现阻断条件。
- 本文未特别标注的执行/校验条款，默认按 `FROZEN` 处理。

## 1. 背景
- 当前项目已经具备 feature 计算、策略协议、事件驱动回测运行时等基础能力。
- 需要一个标准化的 5 分钟策略配置（`StrategyProfile`），打通“最小研究闭环”，并提供清晰诊断信息。
- 本文档定义 `v0.3` 需求，和系统架构中的 `Regime-Aware Scoring` 保持一致。

## 2. 目标
- 新增策略配置 `FiveMinRegimeMomentumStrategy`（`StrategyProfile`），同时支持 long 与 short。
- 与现有 runtime/backtest 契约完全兼容。
- 通过 regime 判定 + 分组动态权重 + 规则得分，产出最终 `score_total`，并由 `SignalSpec/RiskSpec` 输出动作与风险参数。

## 3. 范围
- 范围内：
  - 固化执行引擎链路与 profile 驱动流程。
  - Regime 状态判定。
  - 动态权重生成与总分合成。
  - 动作映射、风险输出、诊断输出、测试、回测 smoke run。
  - 移除写死逻辑策略类（无过渡态）。
- 范围外：
  - OMS/EMS 实盘执行接入。
  - 组合分配器与跨策略资金路由。
  - 自动化超参数优化框架。
  - 全新多周期融合内核重构（v0.3 仅新增对齐语义，不引入第二套执行内核）。

## 4. 输入与依赖

### 4.1 输入名称
- `features`

### 4.2 必需基础列
- `timestamp`
- `symbol`
- `open`
- `high`
- `low`
- `close`
- `volume`

### 4.3 特征列（v0.3 baseline）
- 必需：`ema_12`, `ema_48`, `macd_12_26_9_hist`, `dmi_14_14_plus_di`, `dmi_14_14_minus_di`, `dmi_14_14_adx`, `atr_14`, `atr_pct_rank_252`, `volume_variation_20`
- 可选扩展：`rsi_14`（用于后续 regime 扩展或附加规则，不作为 v0.3 baseline 必需项）

### 4.4 时间与数据约束
- `timestamp` 必须为 UTC、单调递增、无重复。
- 所有中间计算必须禁止前视（no forward-looking）。

## 5. Baseline 规则得分定义（统一量纲：[-1, 1]）

- 本节是 `FiveMinRegimeMomentumStrategy` 的默认规则集示例，不构成引擎层“固定五维”约束。
- 其他策略可在 `RegimeSpec.groups[].rules[]` 中配置不同规则函数与输入引用。

### 5.1 趋势得分（Trend Score）
- `trend_gap = (ema12 - ema48) / (1.5 * atr14)`
- `trend_score = tanh(trend_gap)`

### 5.2 动量得分（Momentum Score）
- `mom_raw = macd_hist / rolling_std(macd_hist, 96)`
- `momentum_score = tanh(mom_raw)`

### 5.3 方向强度得分（Direction Strength Score）
- `dm_spread = (plus_di - minus_di) / 100`
- `adx_strength = clip((adx - 18) / 12, 0, 1)`
- `direction_score = dm_spread * adx_strength`

### 5.4 成交量确认得分（Volume Confirmation Score）
- `trend_proxy = tanh((ema12 - ema48) / (1.5 * atr14))`
- `momentum_proxy = tanh(macd_hist / rolling_std(macd_hist, 96))`
- `dir_sign = sign(0.6 * trend_proxy + 0.4 * momentum_proxy)`
- `vol_amp = tanh(volume_variation_20 / 0.8)`
- `volume_score = vol_amp * dir_sign`

### 5.5 回踩结构得分（Pullback Structure Score）
- `dev = (close - ema12) / atr14`
- `trend_proxy = sign(ema12 - ema48)`
- `pb_long = clip((-dev) / 1.2, 0, 1)`
- `pb_short = clip((dev) / 1.2, 0, 1)`
- `pullback_score = pb_long * (trend_proxy > 0) - pb_short * (trend_proxy < 0)`

### 5.6 `score_fn` 机制约束（v0.3 冻结）
- v0.3 仅保留 `score_fn` 机制，不引入 `compute + normalize + quality` 配置块。
- 每条 `RuleSpec` 通过 `score_fn + input_refs + params` 定义评分逻辑：
  - `score_fn` 指定评分算子类型；
  - `input_refs` 指定参与计算的特征输入；
  - `params` 指定算子参数。
- 归一化口径由 `score_fn` 实现内部负责，输出统一约束到 `[-1, 1]`。
- 质量处理在 v0.3 通过 `RuleSpec.nan_policy` 表达（最小闭环冻结）：
  - `nan_policy` 仅允许 `neutral_zero`；
  - 当规则输入缺失/NaN/warmup 不足时，`rule_score = 0.0`；
  - 该规则仍参与组内聚合（不做组内重归一化）。
- v0.3 仅允许内置 `score_fn`，不启用 `custom_udf`。
- 扩展原则：
  - 新增指标优先通过 `input_refs` 接入既有 `score_fn`；
  - 仅当出现“新的评分函数族”时才新增 `score_fn`。

### 5.7 `score_fn` 参数契约（v0.3 冻结）
- 通用约束：
  - `input_refs` 必须与对应 `score_fn` 的签名在“数量与顺序”上完全一致；
  - `params` 仅允许该 `score_fn` 白名单字段（未知字段 precompile 失败）；
  - `score_fn` 不允许依赖其他规则输出（只读取 `input_refs` 对应特征）。
  - 角色绑定规则冻结：`score_fn.input_roles[i] <-> RuleSpec.input_refs[i]`（按位置一一绑定，不做名称推断）。
  - precompile 必须输出每条规则的 `resolved_input_binding`（`role -> FeatureRef`）以便诊断与回放一致性。
- 内置签名与参数：
  - `trend_score`：
    - `input_refs`: `[ema_fast, ema_slow, atr_main]`
    - `params`: `atr_scale`（`>0`，默认 `1.5`）
  - `momentum_score`：
    - `input_refs`: `[macd_hist]`
    - `params`: `std_window`（整数，`>=10`，默认 `96`）
  - `direction_score`：
    - `input_refs`: `[plus_di, minus_di, adx]`
    - `params`: `adx_floor`（`[0,100]`，默认 `18`），`adx_span`（`>0`，默认 `12`）
  - `volume_score`：
    - `input_refs`: `[volume_variation, ema_fast, ema_slow, atr_main, macd_hist]`
    - `params`: `trend_mix`（`[0,1]`，默认 `0.6`），`vol_scale`（`>0`，默认 `0.8`），`atr_scale`（`>0`，默认 `1.5`）
  - `pullback_score`：
    - `input_refs`: `[close, ema_fast, ema_slow, atr_main]`
    - `params`: `dev_scale`（`>0`，默认 `1.2`）

### 5.8 内置 `score_fn` 默认参数速查表（实现映射）
- `trend_score`
  - `atr_scale=1.5`
- `momentum_score`
  - `std_window=96`
- `direction_score`
  - `adx_floor=18`
  - `adx_span=12`
- `volume_score`
  - `trend_mix=0.6`
  - `vol_scale=0.8`
  - `atr_scale=1.5`
- `pullback_score`
  - `dev_scale=1.2`
- 说明：
  - 上述默认值用于 `params` 缺省时的 precompile/resolved 填充；
  - 默认值变更属于策略行为变更，需提升 profile 版本（如 `v0.3 -> v0.3.1`）。

### 5.9 `score_fn_registry` JSON 草案（实现参考）
```json
{
  "version": "v0.3",
  "allow_custom_udf": false,
  "score_fns": {
    "trend_score": {
      "input_roles": ["ema_fast", "ema_slow", "atr_main"],
      "params_schema": {
        "atr_scale": {
          "type": "number",
          "exclusiveMinimum": 0.0,
          "default": 1.5
        }
      },
      "output_range": [-1.0, 1.0]
    },
    "momentum_score": {
      "input_roles": ["macd_hist"],
      "params_schema": {
        "std_window": {
          "type": "integer",
          "minimum": 10,
          "default": 96
        }
      },
      "output_range": [-1.0, 1.0]
    },
    "direction_score": {
      "input_roles": ["plus_di", "minus_di", "adx"],
      "params_schema": {
        "adx_floor": {
          "type": "number",
          "minimum": 0.0,
          "maximum": 100.0,
          "default": 18.0
        },
        "adx_span": {
          "type": "number",
          "exclusiveMinimum": 0.0,
          "default": 12.0
        }
      },
      "output_range": [-1.0, 1.0]
    },
    "volume_score": {
      "input_roles": ["volume_variation", "ema_fast", "ema_slow", "atr_main", "macd_hist"],
      "params_schema": {
        "trend_mix": {
          "type": "number",
          "minimum": 0.0,
          "maximum": 1.0,
          "default": 0.6
        },
        "vol_scale": {
          "type": "number",
          "exclusiveMinimum": 0.0,
          "default": 0.8
        },
        "atr_scale": {
          "type": "number",
          "exclusiveMinimum": 0.0,
          "default": 1.5
        }
      },
      "output_range": [-1.0, 1.0]
    },
    "pullback_score": {
      "input_roles": ["close", "ema_fast", "ema_slow", "atr_main"],
      "params_schema": {
        "dev_scale": {
          "type": "number",
          "exclusiveMinimum": 0.0,
          "default": 1.2
        }
      },
      "output_range": [-1.0, 1.0]
    }
  },
  "global_constraints": {
    "input_refs_must_match_signature_order": true,
    "unknown_params_forbidden": true,
    "rule_to_rule_dependency_forbidden": true,
    "nan_policy_allowed": ["neutral_zero"]
  }
}
```

## 6. Regime-Aware Scoring（v0.3 核心逻辑）

### 6.1 核心原则
- Regime 不输出独立 `gate` 信号。
- Regime 只负责输出分组动态权重。
- “gate 效果”通过权重为 0 达成，而不是单独的 `regime_gate` 分支。

### 6.2 Regime 状态集合（配置化）
- `RegimeSpec.states[]` 定义该策略可用状态集合（自定义，不写死在引擎）。
- 建议默认集合（可按策略裁剪/扩展）：
  - `TREND_CLEAN`
  - `TREND_TURBULENT`
  - `RANGE_COMPRESSION`
  - `RANGE_NOISY`
  - `TRANSITION`
  - `NO_TRADE_EXTREME`
- `RegimeSpec.classifier` 负责将每根 bar 归类到某个状态。
- v0.3 `classifier` 执行语义冻结：
  - `rules` 按 `priority` 升序执行，采用 first-match（首个命中即停止）；
  - 单条 `classifier_rule` 内 `conditions[]` 使用 AND 语义（全部条件为真才命中）；
  - `op=between` 解释为闭区间：`min <= x <= max`；
  - 条件值缺失/NaN/超 staleness 时，该条件判定为 `false`；
  - 若全部规则均未命中，使用 `default_state`。
  - `classifier.inputs` 与“启用规则（`enabled=true`）的 `conditions[].ref`”必须集合完全一致：
    - `inputs` 有但规则未使用 -> `UNUSED_CLASSIFIER_INPUT`（precompile 失败）；
    - 规则使用但未在 `inputs` 声明 -> `UNDECLARED_CLASSIFIER_REF`（precompile 失败）。

### 6.3 动态权重公式
- 权重采用“上一级唯一指定”：
  - 组内权重：由 `RegimeSpec.groups[].rule_weights` 明确指定（用于 `Rule -> Group` 聚合）。
  - 组间权重：由 `RegimeSpec.state_group_weights[state]` 明确指定（用于 `Group -> Total` 聚合）。
  - 兼容映射：旧版 `multiplier_matrix_by_group` 在 v0.3 对应 `state_group_weights`。
  - 执行路径不使用 `rule_base_weight/group_base_weight/default/fallback` 隐式权重。
- v0.3 最小闭环冻结：
  - 不启用 `q_g`（group 质量因子），固定视为 `q_g = 1.0`；
  - 因此组间权重计算简化为 `w_group_raw_g = state_group_weight_g`。
- 归一化规则：
  - 若 `sum(w_group_raw) > eps`，则 `w_g = w_group_raw_g / sum(w_group_raw)`
  - 若 `sum(w_group_raw) <= eps`，则所有 `w_g = 0`

### 6.4 严格权重校验（强制）
- `RegimeSpec.groups[]` 中每个 `GroupSpec` 必须完整声明 `rule_weights`（覆盖该 group 启用规则）；
- `state_group_weights` 必须完整覆盖 `RegimeSpec.states[]` 中全部状态；
- 每个状态下的 group 权重必须完整覆盖所有启用分组；
- 任一缺失即 precompile 失败（fail-fast）。

### 6.5 No-Trade 语义
- No-trade 使用“零权重结果”表达：
  - 对于强阻断状态（如配置存在 `NO_TRADE_EXTREME`），在 `state_group_weights` 中将所有 group 权重设为 0。
  - 得到 `w = [0,0,...,0]`，自然有 `score_total = 0`。
- 不使用独立 gate 分支。

### 6.6 可选平滑
- 可选（可配置）：
  - `w_t = (1 - a) * w_{t-1} + a * w_target`
  - `a` 建议在 `[0.1, 0.3]`
- 若关闭平滑，直接使用 `w_target`。

### 6.7 多周期对齐语义（单周期为特例）
- `RegimeSpec.decision_timeframe` 定义策略最终决策与动作输出的锚定周期。
- `RegimeSpec.alignment_policy` 定义非锚定周期特征如何对齐到 `decision_timeframe`。
- v0.3 约定：
  - `alignment_policy.mode = ffill_last_closed`：仅使用“已收盘”高周期值，并在低周期上前向填充到下一个高周期收盘前。
  - `alignment_policy.max_staleness_bars_by_tf`：按来源周期设置旧值保鲜上限（单位为 `decision_timeframe` bars）。
- 单周期策略是多周期特例：若只引用 `decision_timeframe` 特征，`max_staleness_bars_by_tf` 可为空对象。

## 7. 总分合成
- Step 1（Rule -> Group）：
  - 组内聚合：`group_score_g = Σ_r (rule_weight_{g,r} * rule_score_r)`
  - `rule_weight_{g,r}` 来自 `RegimeSpec.groups[g].rule_weights`。
- Step 2（Group -> Total）：
  - 组间聚合：`score_total = Σ_g (w_g * group_score_g)`
  - `w_g` 来自 `RegimeSpec.state_group_weights`（经归一化处理后）。

## 8. SignalSpec 动作映射（Long + Short）
- 最终动作由 `SignalSpec` 决定，不使用固定阈值三段式硬编码。
- `SignalSpec` 规则统一使用 `score_range` + `state_allow/state_deny`。
- 同 bar 多规则命中时，按 `rule.priority_rank` 产出唯一动作：`ENTER_LONG/ENTER_SHORT/EXIT/HOLD`。

## 9. RiskSpec 风险输出
- 保持当前 action schema：
  - `timestamp, symbol, action, size, stop_loss, take_profit, reason`
- `reason` 字段口径（v0.3 冻结）：
  - 引擎内部统一使用 `reason_code` 概念；
  - 对外 action 输出字段保持 `reason`（兼容现有 schema）；
  - 输出时采用 `reason = reason_code`（值必须来自标准枚举，禁止自由文本）。
- 风险参数由 `RiskSpec` 生成（如 `size_model/stop_model/take_profit_model/time_stop/portfolio_guards`）。
- 输出单位口径冻结（v0.3）：
  - `stop_loss/take_profit` 输出为绝对价格位（price level）。
  - 若内部 mode 使用比例或 ATR 倍数，必须在 `RiskEngine` 内换算为绝对价格后再输出。
- size 语义：
  - `ENTER_LONG/ENTER_SHORT`：`size > 0`
  - `EXIT/HOLD`：`size = 0`

## 10. 默认参数（v0.3 Baseline）
- Signal baseline（`score_range`）：
  - `ENTER_LONG`: `min=0.55, max=null`（`null` 表示无界）
  - `ENTER_SHORT`: `min=null, max=-0.55`（`null` 表示无界）
  - `EXIT`: `[-0.15, 0.15]`
  - `HOLD`: 兜底规则（未命中其他动作时）。
- Risk baseline（示例口径）：
  - `size_model.mode = fixed_fraction`, `fraction = 0.02`
  - `stop_model.mode = fixed_pct`, `pct = 0.008`
  - `take_profit_model.mode = fixed_pct`, `pct = 0.016`
  - `time_stop.bars = 36`
  - `portfolio_guards.daily_loss_limit = 0.025`

## 11. 诊断与可解释性

### 11.1 行级诊断字段
- `score_total`
- `state`
- `group_scores`（`{group_id: score}`）
- `rule_scores`（`{rule_id: score}`）
- `group_weights`（`{group_id: weight}`）
- `group_qualities`（v0.3 固定输出 `1.0`，为未来质量因子扩展预留）
- `matched_rule_id`（最终命中的 `SignalSpec` 规则）
- `reason_code`

### 11.2 运行级诊断字段
- `input_rows`, `output_rows`
- `long_count`, `short_count`, `exit_count`, `hold_count`
- `state_distribution`
- `zero_weight_rows`

## 12. 建议的 reason_code（初始集合）
- `LONG_ENTRY_SIGNAL`
- `SHORT_ENTRY_SIGNAL`
- `EXIT_WEAK_SIGNAL`
- `HOLD_BETWEEN_BANDS`
- `REGIME_STATE_TREND_CLEAN`
- `REGIME_STATE_TREND_TURBULENT`
- `REGIME_STATE_RANGE_COMPRESSION`
- `REGIME_STATE_RANGE_NOISY`
- `REGIME_STATE_TRANSITION`
- `REGIME_STATE_NO_TRADE_EXTREME`
- `WEIGHT_ALL_ZERO`
- `WARMUP_INSUFFICIENT`
- `FEATURE_NAN`

## 13. 代码落位（计划）
- 引擎模块：
  - `src/xtrader/strategies/signal_engine/regime_scoring.py`
  - `src/xtrader/strategies/signal_engine/regime.py`
  - `src/xtrader/strategies/signal_engine/scoring.py`（`score_fn` registry 与内置评分算子实现）
  - `src/xtrader/strategies/signal_engine/signal.py`
  - `src/xtrader/strategies/signal_engine/risk.py`
  - `src/xtrader/strategies/signal_engine/reason_codes.py`
- profile 配置：
  - `configs/strategy-profiles/five_min_regime_momentum/v0.3.json`
- 测试：
  - `tests/unit/strategies/test_profile_driven_pipeline.py`

## 14. 验收标准
- Action 输出通过现有 schema 校验。
- 单测覆盖 `ENTER_LONG/ENTER_SHORT/EXIT/HOLD`，并覆盖 warmup/缺失值分支、区间冲突分支。
- 回测 smoke run 可产出完整 artifacts（`signals/trades/equity/summary`）。
- 前视偏差检查通过（不得泄漏未来信息）。
- 成本敏感性方向合理（成本上升不应异常提升表现）。
- 仓库中不再存在“写死信号逻辑”的业务策略类（以 profile + 引擎为唯一执行路径）。

## 15. 里程碑
- M1：引擎模块（Rule/Group/Regime/Signal/Risk）骨架完成。
- M2：规则得分 + 动态权重 + `score_range` 信号 + 风险输出 + 单测完成。
- M3：删除写死策略类并完成调用路径切换（无兼容分支）。
- M4：Runtime 回测 smoke run 与诊断验证完成，冻结 v0.3 基准结果。

## 16. 后续讨论项（BACKLOG）
- 状态判定阈值与滞后（hysteresis）参数细化。
- 各 regime 状态下 `state_group_weights` 数值细化。
- `q_g` 质量因子定义细节（延后至 v0.4；v0.3 固定 `q_g=1.0`）。
- v0.3 默认是否启用权重平滑。
- `nan_policy` 扩展（`skip/fail` 及组内重归一化策略）延后至 v0.4。
- `score_fn` 扩展机制（受控 `custom_udf` 注册与沙箱执行）延后至 v0.4。

## 17. StrategyProfile 生命周期与编译执行流程

### 17.1 StrategyProfile 定义与组成
- 一条可运行策略由 `StrategyProfile` 描述，最小组成：
  - `RegimeSpec`
  - `SignalSpec`（原 `ActionMappingSpec` 命名）
  - `RiskSpec`（原 `RiskIntentSpec` 命名）
- 其中：
  - `RegimeSpec` 负责完整评分体系：状态判定 + 分组定义 + 规则定义 + 动态权重产出；
  - `RegimeSpec` 内部包含：
    - `states[]`
    - `classifier`
    - `groups[]: GroupSpec`
    - `GroupSpec.rules[]: RuleSpec`
  - `RuleSpec` 通过 `score_fn` 负责单条评分规则计算（归一化由 `score_fn` 内置实现）；
  - `GroupSpec` 负责组内聚合与显式规则权重；
  - `SignalSpec` 负责 `score_total/state -> action` 映射；
  - `RiskSpec` 负责 `action/context -> size/stop_loss/take_profit/...` 输出口径。
- 最小可运行配置：
  - 1 个 `decision_timeframe` + 1 组 `alignment_policy` + 1 个状态 + 1 条 classifier 规则 + 1 个 `GroupSpec` + 1 条 `RuleSpec` + 1 组 `state_group_weights` 即可运行；
  - 多 group / 多 rule 通过配置横向扩展，不改执行代码。

### 17.2 存储与版本管理（GUIDELINE）
- 配置源（可评审、可版本化）：
  - `configs/strategy-profiles/<strategy_id>/<version>.json`
- 策略注册表（状态管理）：
  - `configs/strategy-profiles/registry.json`
- run 级快照（可复现）：
  - `strategy_profile.raw.json`
  - `strategy_profile.resolved.json`
  - `strategy_profile_hash`（写入 `run_manifest`）
- 状态流转（GUIDELINE）：
  - `DRAFT -> CANDIDATE -> APPROVED -> DEPRECATED`

### 17.3 编译期（Precompile）流程
- Step 1：加载 `StrategyProfile`，执行 schema 与字段校验。
- Step 2：校验 `RegimeSpec/SignalSpec/RiskSpec` 基础结构与枚举字段。
- Step 3：解析 `RegimeSpec.groups[].rules[].input_refs` 与 `RegimeSpec.classifier.inputs/conditions[].ref`，汇总 `required_feature_refs`（`conditions[].ref` 仅统计 `enabled=true` 的 classifier 规则）。
- Step 4：根据 `required_feature_refs` 反解/校验 `indicator_plan_by_tf`。
- Step 5：校验 `decision_timeframe` 与 `alignment_policy` 可执行性（timeframe 合法、mode 合法、staleness 配置覆盖非锚定周期）。
- Step 6：生成 `required_indicator_plan_by_tf`（去重、排序、参数锁定）。
- Step 7：生成 `feature_catalog`（`FeatureRef -> physical_col` 映射）。
- Step 8：校验 `RegimeSpec` 内依赖完整性（规则依赖 + classifier 依赖：缺失引用、非法 `output_key`、循环依赖、classifier 输入声明一致性）。
- Step 8.1：按 `score_fn` 注册签名校验每条 `RuleSpec.input_refs` 的参数个数与顺序绑定规则。
- Step 9：执行权重完整性校验（强制）：
  - 校验 `RegimeSpec.groups[]` 每个 group 的 `rule_weights` 是否完整覆盖启用规则；
  - 校验 `state_group_weights` 是否完整覆盖 `RegimeSpec.states[]`；
  - 校验每个状态下的 group 权重是否完整覆盖启用分组；
  - 缺失即 fail-fast。
- Step 10：校验 `SignalSpec/RiskSpec` 可执行性：
  - `SignalSpec`：`score_range` 合法、`rule.priority_rank` 合法且冲突可解、`reason_code_map` 覆盖完整；
  - `RiskSpec`：`mode` 在白名单内、`params` 满足对应 mode 参数约束。
- Step 11：输出：
  - `precompile_report.json`
  - `feature_catalog.json`
  - `strategy_profile.resolved.json`
  - （内含 `resolved_input_bindings`: `rule_id -> {role: feature_ref}`）
  - `required_indicator_plan_by_tf`
  - `signal_spec.resolved.json`
  - `risk_spec.resolved.json`

### 17.4 运行期（Runtime）执行链路
- Step 1：按 `required_indicator_plan_by_tf` 调用 `FeaturePipeline` 计算最小特征集。
- Step 2：按 `decision_timeframe` 建立决策时间轴，并按 `alignment_policy` 对齐非锚定周期特征（含 staleness 判定）。
- Step 3：调用 `RegimeScoringEngine`（内部固定链路）：
  - `RuleEngine -> GroupAggregator -> RegimeEngine -> ScoreSynthesizer`
  - `RuleEngine` 按 `score_fn` registry 分发到对应评分算子。
  - 输出 `score_total/state/group_scores/rule_scores`。
- Step 4：`SignalEngine` 按 `SignalSpec`（`score_range + state`）映射到 `ENTER_LONG/ENTER_SHORT/EXIT/HOLD`。
- Step 5：`RiskEngine` 按 `RiskSpec` 计算 `size/stop_loss/take_profit/time_stop_bars`。
- Step 6：输出标准 action 表与 diagnostics，并交由现有回测执行层处理。

### 17.5 Runtime 如何知道需要哪些指标
- 核心原则：由配置反向推导，不靠手工猜测。
- 具体机制：
  - 从 `RegimeSpec.groups[].rules[].input_refs` 收集规则依赖；
  - 从 `RegimeSpec.classifier.inputs` 与“启用规则”的 `classifier.rules[].conditions[].ref` 收集状态判定依赖；
  - precompile 阶段强校验二者集合一致（不一致直接失败，不进入 runtime）；
  - 以 `decision_timeframe` 为主轴，识别所有非锚定周期依赖；
  - 通过 `FeatureRef` 解析出 `timeframe + instance_id + output_key`；
  - 反查 `indicator_plan_by_tf` 中对应的 `family + params`；
  - 汇总后得到最小 `required_indicator_plan_by_tf`；
  - 运行时仅计算该最小集合，避免多余特征计算。

### 17.6 Regime 与策略的边界
- `RegimeScoringEngine` 是通用程序模块（引擎级能力，对外统一入口）。
- `RegimeSpec` 是策略配置的一部分（策略级语义，内含 `groups/rules`）。
- 即：引擎复用、配置隔离；不同策略可共享同一 `RegimeScoringEngine`，但各自拥有独立 `RegimeSpec`。

### 17.7 失败与回退语义
- 若 `required_feature_refs` 无法被 `indicator_plan_by_tf` 解析，precompile 失败并阻断运行。
- 若运行时某些规则输入缺失/NaN/warmup 不足，按 `RuleSpec.nan_policy=neutral_zero` 处理为 `rule_score=0.0`，并写入 `reason_code`（`FEATURE_NAN` 或 `WARMUP_INSUFFICIENT`）。
- 若 `classifier` 条件依赖缺失/NaN/超 staleness，相关条件视为 `false`；若无规则命中则回退 `default_state`。
- 若 `sum(w_group_raw) <= eps`，组间动态权重全零，`score_total=0`，动作映射自然退化为 `EXIT/HOLD`。

## 18. SignalSpec 标准化（分数到信号）

### 18.1 设计目标
- 在 `score_total` 之上再抽象一层 `SignalSpec`，支持不同策略复用同一打分引擎、切换不同信号逻辑。
- `SignalSpec` 仅依赖可观测输入（如 `score_total/state/diagnostics`），不直接依赖底层指标细节。

### 18.2 最小配置结构（FROZEN）
- `SignalSpec`：
  - `entry_rules`：入场规则集合（支持 long/short）。
  - `exit_rules`：离场规则集合。
  - `hold_rules`：持有规则集合（可选，默认兜底）。
  - `rule.score_range`：分数区间条件（统一形式，替代 `score_op/score_threshold/expr`）。
    - `min/max` 仅允许 `number | null`；`null` 表示该侧无界。
  - `rule.state_allow / rule.state_deny`：状态白名单/黑名单（可选）。
  - `rule.priority_rank`：规则优先级（整数，越小优先级越高）。
  - `cooldown_bars`：动作冷却期（可选）。
  - `cooldown_scope`：冷却作用域（v0.3 默认 `symbol_action`）。
  - `reason_code_map`：规则命中到标准 reason code 的映射。

### 18.3 执行语义（FROZEN）
- 信号层输入：`score_total`、`state`、`group_scores`、`rule_scores`、持仓上下文。
- 信号层输出：`ENTER_LONG/ENTER_SHORT/EXIT/HOLD` 与 `reason_code`（action 对外字段为 `reason`，取值等于 `reason_code`）。
- 单条规则命中条件：
  - `enabled=true`；
  - `score_total` 落入 `score_range`；
  - 通过 `state_allow/state_deny` 过滤（若同时配置，`state_deny` 优先）。
- 命中决策顺序：
  - 按 `rule.priority_rank` 升序执行；
  - 采用 first-match 语义，确保同 bar 单动作。
- `cooldown_bars` 语义（v0.3）：
  - `cooldown_scope=symbol_action`：同一 `symbol+action` 在冷却期内不重复触发。

### 18.4 编译期校验（FROZEN）
- 校验 `entry_rules/exit_rules/hold_rules` 的字段完整性与类型合法性。
- 校验 `score_range` 区间合法性（边界、开闭区间、空区间、越界）。
- 校验 `rule.priority_rank` 合法性（正整数；在 `entry_rules/exit_rules/hold_rules` 全局范围内必须唯一）。
- 校验规则冲突（允许区间重叠，但必须可由唯一 `priority_rank` 提供确定性 first-match）。
- 校验区间覆盖完整性：若不存在 `HOLD` 兜底规则，则规则区间必须完整覆盖 `[-1, 1]`（否则 precompile 失败）。
- 校验动作枚举合法性（仅允许标准 action 枚举）。
- 校验 `reason_code_map` 必须覆盖所有启用规则 `id`（`entry_rules/exit_rules/hold_rules` 全覆盖）。
- 产物写入 `signal_spec.resolved.json`，并纳入 `strategy_profile_hash`。

### 18.5 区间策略（v0.3 约束）
- 推荐区间基线：相邻规则采用半开区间拼接（如 `[a,b)` 与 `[b,c)`）以避免边界重复命中。
- 若确需闭区间重叠，必须依赖“全局唯一”的 `priority_rank` 提供确定性 first-match。
- 若不存在 `HOLD` 兜底规则且区间覆盖存在空洞，precompile 直接失败（错误）。

## 19. RiskSpec 标准化（信号到风险参数）

### 19.1 设计目标
- 风险参数从策略代码中抽离为 `RiskSpec` 配置，实现“同信号，不同风险模板”快速复用。
- 统一输出口径，保持与现有 action schema 兼容。

### 19.2 最小配置结构（FROZEN）
- `RiskSpec`：
  - `size_model`：仓位模型（固定比例、波动率缩放、风险预算等）。
  - `stop_model`：止损模型（固定百分比、ATR 倍数、结构位等）。
  - `take_profit_model`：止盈模型（固定 R、ATR 倍数、分段止盈等）。
  - `time_stop`：最大持仓 bar 数。
  - `portfolio_guards`：如 `daily_loss_limit`、最大并发仓位等约束。
  - `rounding_policy`：价格与数量舍入规则（与执行层契约保持一致）。
- v0.3 mode 白名单：
  - `size_model.mode`: `fixed_fraction`
  - `stop_model.mode`: `fixed_pct` / `atr_multiple`
  - `take_profit_model.mode`: `fixed_pct` / `rr_multiple`

### 19.3 执行语义（FROZEN）
- 风险层输入：`action`、`score_total`、市场数据（如 `close/atr`）、账户上下文。
- 风险层输出：`size/stop_loss/take_profit/time_stop_bars`。
- 输出口径冻结：`stop_loss/take_profit` 必须为绝对价格位（内部若使用 `%/ATR` 需先换算）。
- `ENTER_*` 必须输出 `size > 0`；`EXIT/HOLD` 必须输出 `size = 0`。

### 19.4 编译期校验（FROZEN）
- 校验各风险模型参数范围与必填字段。
- 校验输出类型与单位口径一致性（价格位/比例不得混用）。
- 校验 guard 规则可执行性（依赖字段存在、条件可求值）。
- 产物写入 `risk_spec.resolved.json`，并纳入 `strategy_profile_hash`。

## 20. 统一引擎执行总线（GUIDELINE，主链路除外）
- 固化执行链路：
  - `FeaturePipeline -> RegimeScoringEngine -> SignalEngine -> RiskEngine -> Action Output`
- 其中 `RegimeScoringEngine` 内部固定为：
  - `RuleEngine -> GroupAggregator -> RegimeEngine -> ScoreSynthesizer`
- 策略差异主要由 `StrategyProfile` 配置表达，代码层仅保留：
  - 通用执行引擎；
  - 指标计算算子库；
  - 可复用规则算子库；
  - precompile 与诊断基础设施。

## 21. JSON Schema 草案（RegimeSpec / SignalSpec / RiskSpec）

### 21.1 RegimeSpec Schema（FROZEN）
```json
{
  "$id": "xtrader.schemas.regime_spec.v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "decision_timeframe",
    "alignment_policy",
    "states",
    "classifier",
    "groups",
    "state_group_weights"
  ],
  "properties": {
    "decision_timeframe": {
      "$ref": "#/$defs/timeframe"
    },
    "alignment_policy": {
      "$ref": "#/$defs/alignment_policy"
    },
    "states": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {
        "$ref": "#/$defs/state_name"
      }
    },
    "classifier": {
      "$ref": "#/$defs/classifier"
    },
    "groups": {
      "type": "array",
      "minItems": 1,
      "items": {
        "$ref": "#/$defs/group"
      }
    },
    "state_group_weights": {
      "type": "object",
      "minProperties": 1,
      "additionalProperties": {
        "$ref": "#/$defs/group_weight_map"
      }
    }
  },
  "$defs": {
    "timeframe": {
      "type": "string",
      "pattern": "^[0-9]+[smhdw]$"
    },
    "state_name": {
      "type": "string",
      "pattern": "^[A-Z][A-Z0-9_]*$"
    },
    "alignment_policy": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "mode"
      ],
      "properties": {
        "mode": {
          "type": "string",
          "enum": [
            "ffill_last_closed"
          ]
        },
        "max_staleness_bars_by_tf": {
          "type": "object",
          "default": {},
          "patternProperties": {
            "^[0-9]+[smhdw]$": {
              "type": "integer",
              "minimum": 1
            }
          },
          "additionalProperties": false
        }
      }
    },
    "feature_ref": {
      "type": "string",
      "pattern": "^f:[^:]+:[^:]+:[^:]+$"
    },
    "classifier": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "inputs",
        "rules",
        "default_state"
      ],
      "properties": {
        "inputs": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": {
            "$ref": "#/$defs/feature_ref"
          }
        },
        "rules": {
          "type": "array",
          "minItems": 1,
          "items": {
            "$ref": "#/$defs/classifier_rule"
          }
        },
        "default_state": {
          "$ref": "#/$defs/state_name"
        }
      }
    },
    "classifier_rule": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "priority",
        "target_state",
        "conditions"
      ],
      "properties": {
        "priority": {
          "type": "integer",
          "minimum": 1
        },
        "target_state": {
          "$ref": "#/$defs/state_name"
        },
        "conditions": {
          "type": "array",
          "minItems": 1,
          "items": {
            "$ref": "#/$defs/predicate"
          }
        },
        "enabled": {
          "type": "boolean",
          "default": true
        }
      }
    },
    "predicate": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "ref",
        "op"
      ],
      "properties": {
        "ref": {
          "$ref": "#/$defs/feature_ref"
        },
        "op": {
          "type": "string",
          "enum": [
            ">",
            ">=",
            "<",
            "<=",
            "==",
            "!=",
            "between"
          ]
        },
        "value": {
          "type": "number"
        },
        "min": {
          "type": "number"
        },
        "max": {
          "type": "number"
        }
      },
      "allOf": [
        {
          "if": {
            "properties": {
              "op": {
                "const": "between"
              }
            }
          },
          "then": {
            "required": [
              "min",
              "max"
            ]
          },
          "else": {
            "required": [
              "value"
            ]
          }
        }
      ]
    },
    "rule": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "rule_id",
        "score_fn",
        "input_refs"
      ],
      "properties": {
        "rule_id": {
          "type": "string",
          "minLength": 1
        },
        "score_fn": {
          "type": "string",
          "enum": [
            "trend_score",
            "momentum_score",
            "direction_score",
            "volume_score",
            "pullback_score"
          ]
        },
        "input_refs": {
          "type": "array",
          "minItems": 1,
          "items": {
            "$ref": "#/$defs/feature_ref"
          }
        },
        "params": {
          "type": "object",
          "default": {}
        },
        "nan_policy": {
          "type": "string",
          "enum": [
            "neutral_zero"
          ],
          "default": "neutral_zero"
        },
        "enabled": {
          "type": "boolean",
          "default": true
        }
      }
    },
    "group": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "group_id",
        "rules",
        "rule_weights"
      ],
      "properties": {
        "group_id": {
          "type": "string",
          "minLength": 1
        },
        "rules": {
          "type": "array",
          "minItems": 1,
          "items": {
            "$ref": "#/$defs/rule"
          }
        },
        "rule_weights": {
          "type": "object",
          "minProperties": 1,
          "additionalProperties": {
            "type": "number",
            "minimum": 0.0
          }
        },
        "enabled": {
          "type": "boolean",
          "default": true
        }
      }
    },
    "group_weight_map": {
      "type": "object",
      "minProperties": 1,
      "additionalProperties": {
        "type": "number",
        "minimum": 0.0
      }
    }
  }
}
```

### 21.2 SignalSpec Schema（FROZEN）
```json
{
  "$id": "xtrader.schemas.signal_spec.v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "entry_rules",
    "exit_rules",
    "reason_code_map"
  ],
  "properties": {
    "entry_rules": {
      "type": "array",
      "minItems": 1,
      "items": {
        "$ref": "#/$defs/rule"
      }
    },
    "exit_rules": {
      "type": "array",
      "minItems": 1,
      "items": {
        "$ref": "#/$defs/rule"
      }
    },
    "hold_rules": {
      "type": "array",
      "default": [],
      "items": {
        "$ref": "#/$defs/rule"
      }
    },
    "cooldown_bars": {
      "type": "integer",
      "minimum": 0,
      "default": 0
    },
    "cooldown_scope": {
      "type": "string",
      "enum": [
        "symbol_action"
      ],
      "default": "symbol_action"
    },
    "reason_code_map": {
      "type": "object",
      "minProperties": 1,
      "additionalProperties": {
        "type": "string",
        "minLength": 1
      }
    }
  },
  "$defs": {
    "state": {
      "type": "string",
      "pattern": "^[A-Z][A-Z0-9_]*$"
    },
    "score_range": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "min",
        "max",
        "min_inclusive",
        "max_inclusive"
      ],
      "properties": {
        "min": {
          "type": [
            "number",
            "null"
          ],
          "minimum": -1.0,
          "maximum": 1.0
        },
        "max": {
          "type": [
            "number",
            "null"
          ],
          "minimum": -1.0,
          "maximum": 1.0
        },
        "min_inclusive": {
          "type": "boolean",
          "default": true
        },
        "max_inclusive": {
          "type": "boolean",
          "default": false
        }
      }
    },
    "rule": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "id",
        "action",
        "priority_rank",
        "score_range"
      ],
      "properties": {
        "id": {
          "type": "string",
          "minLength": 1
        },
        "action": {
          "type": "string",
          "enum": [
            "ENTER_LONG",
            "ENTER_SHORT",
            "EXIT",
            "HOLD"
          ]
        },
        "priority_rank": {
          "type": "integer",
          "minimum": 1
        },
        "score_range": {
          "$ref": "#/$defs/score_range"
        },
        "state_allow": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/state"
          },
          "uniqueItems": true
        },
        "state_deny": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/state"
          },
          "uniqueItems": true
        },
        "enabled": {
          "type": "boolean",
          "default": true
        }
      }
    }
  }
}
```

### 21.3 RiskSpec Schema（FROZEN）
```json
{
  "$id": "xtrader.schemas.risk_spec.v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "size_model",
    "stop_model",
    "take_profit_model",
    "time_stop",
    "portfolio_guards"
  ],
  "properties": {
    "size_model": {
      "$ref": "#/$defs/size_model_block"
    },
    "stop_model": {
      "$ref": "#/$defs/stop_model_block"
    },
    "take_profit_model": {
      "$ref": "#/$defs/take_profit_model_block"
    },
    "time_stop": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "bars"
      ],
      "properties": {
        "bars": {
          "type": "integer",
          "minimum": 1
        }
      }
    },
    "portfolio_guards": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "daily_loss_limit"
      ],
      "properties": {
        "daily_loss_limit": {
          "type": "number",
          "minimum": 0.0,
          "maximum": 1.0
        },
        "max_concurrent_positions": {
          "type": "integer",
          "minimum": 1,
          "default": 1
        }
      }
    },
    "rounding_policy": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "price_dp": {
          "type": "integer",
          "minimum": 0,
          "default": 4
        },
        "size_dp": {
          "type": "integer",
          "minimum": 0,
          "default": 4
        }
      }
    }
  },
  "$defs": {
    "size_model_block": {
      "oneOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "mode",
            "params"
          ],
          "properties": {
            "mode": {
              "const": "fixed_fraction"
            },
            "params": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "fraction"
              ],
              "properties": {
                "fraction": {
                  "type": "number",
                  "exclusiveMinimum": 0.0,
                  "maximum": 1.0
                }
              }
            }
          }
        }
      ]
    },
    "stop_model_block": {
      "oneOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "mode",
            "params"
          ],
          "properties": {
            "mode": {
              "const": "fixed_pct"
            },
            "params": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "pct"
              ],
              "properties": {
                "pct": {
                  "type": "number",
                  "exclusiveMinimum": 0.0,
                  "maximum": 1.0
                }
              }
            }
          }
        },
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "mode",
            "params"
          ],
          "properties": {
            "mode": {
              "const": "atr_multiple"
            },
            "params": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "multiple"
              ],
              "properties": {
                "multiple": {
                  "type": "number",
                  "exclusiveMinimum": 0.0
                }
              }
            }
          }
        }
      ]
    },
    "take_profit_model_block": {
      "oneOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "mode",
            "params"
          ],
          "properties": {
            "mode": {
              "const": "fixed_pct"
            },
            "params": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "pct"
              ],
              "properties": {
                "pct": {
                  "type": "number",
                  "exclusiveMinimum": 0.0,
                  "maximum": 1.0
                }
              }
            }
          }
        },
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "mode",
            "params"
          ],
          "properties": {
            "mode": {
              "const": "rr_multiple"
            },
            "params": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "multiple"
              ],
              "properties": {
                "multiple": {
                  "type": "number",
                  "exclusiveMinimum": 0.0
                }
              }
            }
          }
        }
      ]
    }
  }
}
```

### 21.4 Precompile 校验要点（FROZEN，与 Schema 配套）
- `RegimeSpec.decision_timeframe` 必须是合法 timeframe，且存在于被引用特征周期集合中。
- `RegimeSpec.alignment_policy.mode` 必须命中枚举（v0.3 为 `ffill_last_closed`）。
- 若存在非 `decision_timeframe` 的引用特征，`max_staleness_bars_by_tf` 必须覆盖这些来源周期。
- `RegimeSpec.states[]` 必须唯一且非空。
- `RegimeSpec.classifier.default_state` 必须属于 `RegimeSpec.states[]`。
- `RegimeSpec.classifier.rules[].target_state` 必须属于 `RegimeSpec.states[]`，`priority` 不可重复。
- `RegimeSpec.classifier.inputs` 与 `conditions[].ref` 必须是合法 `FeatureRef`，并可解析到 `feature_catalog`。
- `RegimeSpec.classifier.inputs` 与“启用规则（`enabled=true`）的 `conditions[].ref`”必须集合完全一致（按去重集合比较）：
  - 若存在 `inputs - used_refs` 非空，报错 `UNUSED_CLASSIFIER_INPUT`；
  - 若存在 `used_refs - inputs` 非空，报错 `UNDECLARED_CLASSIFIER_REF`。
- `RegimeSpec.classifier.rules[]` 执行语义冻结为：`priority` 升序 first-match。
- `classifier_rule.conditions[]` 执行语义冻结为 AND（all conditions true）。
- `predicate.op=between` 的区间语义冻结为闭区间 `[min, max]`，且 `min <= max`（否则 precompile 失败）。
- `classifier` 条件值缺失/NaN/超 staleness 时，条件判定为 `false`。
- `state_group_weights` 的 key 集合必须与 `RegimeSpec.states[]` 完全一致（禁止缺失与多余状态）。
- 每个状态下的 group 权重必须完整覆盖所有启用 group，且权重值 `>= 0`。
- `RuleSpec` 不允许出现 `compute/normalize/quality` 字段（v0.3 冻结 `score_fn` 单一路径）。
- `RuleSpec.nan_policy` 在 v0.3 仅允许 `neutral_zero`（`skip/fail` 不启用）。
- 对 `neutral_zero` 的执行语义冻结：输入缺失/NaN/warmup 不足时 `rule_score=0.0`，且不触发组内重归一化。
- `RuleSpec.score_fn` 必须命中 v0.3 内置白名单（`trend_score/momentum_score/direction_score/volume_score/pullback_score`），不允许 `custom_udf`。
- `RuleSpec.input_refs` 必须满足对应 `score_fn` 的签名约束（数量与顺序完全匹配）。
- `RuleSpec.input_refs` 角色绑定按位置固定：`input_roles[i] <-> input_refs[i]`，禁止按名称自动推断。
- 若 `len(input_refs) != len(score_fn.input_roles)`，报错 `SCORE_FN_INPUT_ARITY_MISMATCH`。
- `RuleSpec.params` 必须满足对应 `score_fn` 的参数白名单与数值边界（未知字段或越界即 precompile 失败）。
- `SignalSpec` 规则执行顺序以 `rule.priority_rank` 为准（升序 first-match）。
- `SignalSpec.rule.priority_rank` 在 `entry_rules/exit_rules/hold_rules` 全局范围必须唯一，重复即 precompile 失败。
- `SignalSpec.reason_code_map` 必须覆盖所有启用规则 `id`。
- `SignalSpec.rule.score_range` 必须满足：
  - `min/max` 不可同时为 `null`；
  - 禁止出现 `+inf/-inf` 文本或等价字符串写法（无界仅允许用 `null`）；
  - `min < max`（或在闭区间语义下满足非空区间条件）；
  - 同一规则集内不产生不可消解冲突（若区间重叠，必须可由唯一 `priority_rank` 决议）。
- `SignalSpec` 区间覆盖规则：若不存在启用的 `HOLD` 兜底规则，则启用规则区间必须完整覆盖 `[-1, 1]`（否则 precompile 失败）。
- `SignalSpec.state_allow/state_deny`（若配置）必须是 `RegimeSpec.states[]` 的子集。
- `state_allow/state_deny` 同时出现时，`state_deny` 优先。
- `cooldown_scope` 必须命中枚举（v0.3 仅允许 `symbol_action`）。
- `RiskSpec.mode` 必须命中对应白名单枚举（按 `size_model/stop_model/take_profit_model` 分域管理）。
- `RiskSpec.params` 必须满足对应 mode 参数 schema（由 mode 注册表校验，不允许运行期猜测）。
- `RiskSpec` 必须保证输出契约：
  - `ENTER_* => size > 0`
  - `EXIT/HOLD => size = 0`
- 风险参数单位口径冻结为输出绝对价格位：`stop_loss/take_profit` 在 `RiskEngine` 内换算完成后输出。

## 22. 最小可运行配置示例（便于理解）

### 22.1 RegimeSpec 示例（最小闭环）
```json
{
  "decision_timeframe": "5m",
  "alignment_policy": {
    "mode": "ffill_last_closed",
    "max_staleness_bars_by_tf": {}
  },
  "states": [
    "TREND_CLEAN",
    "RANGE_NOISY",
    "NO_TRADE_EXTREME"
  ],
  "classifier": {
    "inputs": [
      "f:5m:dmi_14_14_adx:value",
      "f:5m:atr_pct_rank_252:value"
    ],
    "rules": [
      {
        "priority": 1,
        "target_state": "NO_TRADE_EXTREME",
        "conditions": [
          {
            "ref": "f:5m:atr_pct_rank_252:value",
            "op": ">",
            "value": 0.98
          }
        ],
        "enabled": true
      },
      {
        "priority": 2,
        "target_state": "TREND_CLEAN",
        "conditions": [
          {
            "ref": "f:5m:dmi_14_14_adx:value",
            "op": ">=",
            "value": 25
          },
          {
            "ref": "f:5m:atr_pct_rank_252:value",
            "op": "between",
            "min": 0.2,
            "max": 0.9
          }
        ],
        "enabled": true
      },
      {
        "priority": 3,
        "target_state": "RANGE_NOISY",
        "conditions": [
          {
            "ref": "f:5m:dmi_14_14_adx:value",
            "op": "<",
            "value": 18
          },
          {
            "ref": "f:5m:atr_pct_rank_252:value",
            "op": ">",
            "value": 0.9
          }
        ],
        "enabled": true
      }
    ],
    "default_state": "RANGE_NOISY"
  },
  "groups": [
    {
      "group_id": "trend_core",
      "rules": [
        {
          "rule_id": "trend_rule_v1",
          "score_fn": "trend_score",
          "input_refs": [
            "f:5m:ema_12:value",
            "f:5m:ema_48:value",
            "f:5m:atr_14:value"
          ],
          "params": {},
          "nan_policy": "neutral_zero",
          "enabled": true
        }
      ],
      "rule_weights": {
        "trend_rule_v1": 1.0
      },
      "enabled": true
    }
  ],
  "state_group_weights": {
    "TREND_CLEAN": {
      "trend_core": 1.0
    },
    "RANGE_NOISY": {
      "trend_core": 0.6
    },
    "NO_TRADE_EXTREME": {
      "trend_core": 0.0
    }
  }
}
```

### 22.2 SignalSpec 示例（最小闭环）
```json
{
  "entry_rules": [
    {
      "id": "long_breakout_v1",
      "action": "ENTER_LONG",
      "priority_rank": 2,
      "score_range": {
        "min": 0.55,
        "max": null,
        "min_inclusive": true,
        "max_inclusive": false
      },
      "state_deny": [
        "NO_TRADE_EXTREME"
      ],
      "enabled": true
    },
    {
      "id": "short_breakout_v1",
      "action": "ENTER_SHORT",
      "priority_rank": 3,
      "score_range": {
        "min": null,
        "max": -0.55,
        "min_inclusive": false,
        "max_inclusive": true
      },
      "state_deny": [
        "NO_TRADE_EXTREME"
      ],
      "enabled": true
    }
  ],
  "exit_rules": [
    {
      "id": "exit_weak_signal_v1",
      "action": "EXIT",
      "priority_rank": 1,
      "score_range": {
        "min": -0.15,
        "max": 0.15,
        "min_inclusive": true,
        "max_inclusive": true
      },
      "enabled": true
    }
  ],
  "hold_rules": [
    {
      "id": "hold_default_v1",
      "action": "HOLD",
      "priority_rank": 99,
      "score_range": {
        "min": -1.0,
        "max": 1.0,
        "min_inclusive": true,
        "max_inclusive": true
      },
      "enabled": true
    }
  ],
  "cooldown_bars": 1,
  "cooldown_scope": "symbol_action",
  "reason_code_map": {
    "long_breakout_v1": "LONG_ENTRY_SIGNAL",
    "short_breakout_v1": "SHORT_ENTRY_SIGNAL",
    "exit_weak_signal_v1": "EXIT_WEAK_SIGNAL",
    "hold_default_v1": "HOLD_BETWEEN_BANDS"
  }
}
```

### 22.3 RiskSpec 示例（最小闭环）
```json
{
  "size_model": {
    "mode": "fixed_fraction",
    "params": {
      "fraction": 0.02
    }
  },
  "stop_model": {
    "mode": "fixed_pct",
    "params": {
      "pct": 0.008
    }
  },
  "take_profit_model": {
    "mode": "fixed_pct",
    "params": {
      "pct": 0.016
    }
  },
  "time_stop": {
    "bars": 36
  },
  "portfolio_guards": {
    "daily_loss_limit": 0.025,
    "max_concurrent_positions": 1
  },
  "rounding_policy": {
    "price_dp": 4,
    "size_dp": 4
  }
}
```

### 22.4 三者如何配合运行
- `RegimeScoringEngine` 先产出 `score_total`（内部包含 `RuleEngine -> GroupAggregator -> RegimeEngine -> ScoreSynthesizer`）。
- `SignalEngine` 用 `SignalSpec` 规则得到唯一动作（由 `priority_rank` 解决冲突）。
- `RiskEngine` 用 `RiskSpec` 为该动作补全 `size/stop_loss/take_profit/time_stop_bars`。
- 统一输出 action schema，交给后续执行层/回测层。

## 23. 当前代码现状与引擎化落地路径（讨论结论）

### 23.1 当前代码中的真实生效位置（As-Is）
- `signal_rules/risk_rules` 当前主要用于配置层与 precompile 层校验，不等于“运行时已按配置执行策略”。
- `PrecompileEngine` 当前核心职责是：
  - 生成 `feature_catalog`（`FeatureRef -> physical_col`）；
  - 校验规则中 `feature_ref` 可解析、`output_key` 合法。
- Runtime 执行阶段仍通过 `strategy.generate_actions(context)` 调用策略类代码逻辑（`if/else`），并非由通用 `SignalEngine/RiskEngine` 解释配置后执行。

### 23.2 现状与目标态差异（Gap）
- 现状：`配置校验 + 代码执行`。
- 目标：`配置编译 + 配置执行`。
- 差异点：
  - 已具备：配置读取、结构校验、特征引用校验、回测编排。
  - 未具备：通用 `SignalEngine`/`RiskEngine` 对 `SignalSpec/RiskSpec` 的运行期解释执行。

### 23.3 目标执行形态（To-Be）
- 固化主链路：
  - `FeaturePipeline -> RegimeScoringEngine -> SignalEngine -> RiskEngine -> Action Output`
- 其中：
  - `RegimeScoringEngine` 是一个整体模块，内部固定为 `RuleEngine -> GroupAggregator -> RegimeEngine -> ScoreSynthesizer`；
  - `Rule/Group/Regime` 配置统一封装在 `RegimeSpec` 内部；
  - `SignalEngine` 仅依据 `SignalSpec` 与运行时输入（`score_total/state/...`）决策动作；
  - `RiskEngine` 仅依据 `RiskSpec` 与上下文生成 `size/stop_loss/take_profit/time_stop_bars`；
  - 策略差异主要通过 `StrategyProfile` 配置表达。

### 23.4 增量落地步骤（GUIDELINE）
- Step 1：将 `SignalSpec/RiskSpec` 的 v0.3 FROZEN Schema 落地为正式 `.schema.json`，接入 precompile 的 schema 校验流程。
- Step 2：在 precompile 增加产物：
  - `signal_spec.resolved.json`
  - `risk_spec.resolved.json`
  - （可选）规则区间标准化产物（如归一化边界表）。
- Step 3：新增运行时模块：
  - `RegimeScoringEngine`（对外一体化评分入口）
  - `SignalEngine`（规则命中、优先级冲突决议、reason_code 产出）
  - `RiskEngine`（仓位/止损/止盈/时限与 guards 计算）
- Step 4：在 RuntimeCore 中引入引擎调用路径，直接替代策略类内硬编码信号分支（无兼容分支）。
- Step 5：删除写死业务策略类与相关入口/测试，确保唯一执行路径是 profile + 引擎。

### 23.5 验收判定（本节对应）
- 当同一策略在“不改引擎代码”的前提下，仅通过修改 `SignalSpec/RiskSpec` 即可改变动作与风险输出，可判定配置执行链路打通。
- 当新增策略主要工作收敛为“新增指标算子 + 新配置文件”，且无需改 Runtime 主链路，可判定引擎化目标达成。

## 24. 写死策略类下线流程（无过渡态）

### 24.1 原则
- 不保留“旧策略类直判”兼容路径。
- Profile + 引擎是唯一执行路径。

### 24.2 下线范围（目标文件）
- 删除：
  - `src/xtrader/strategies/builtin_strategies/threshold_intraday.py`
  - `src/xtrader/strategies/intraday.py`
- 清理引用与导出：
  - `src/xtrader/strategies/builtin.py`
  - `src/xtrader/strategies/builtin_strategies/__init__.py`
  - `src/xtrader/strategies/__init__.py`
- 删除或重写旧测试：
  - `tests/unit/strategies/test_intraday.py`
  - `tests/unit/strategies/test_builtin.py`

### 24.3 执行步骤
- Step 1：完成 `StrategyProfile -> RegimeScoringEngine -> SignalEngine -> RiskEngine -> Action Output` 全链路可运行。
- Step 2：将 runtime/script 的策略入口切换为 profile 驱动入口。
- Step 3：删除写死策略类及其导出、脚本引用、旧测试。
- Step 4：补齐 profile 驱动单测与回测 smoke 验证。
- Step 5：执行全量静态检查与回归测试，确认无残留引用。

### 24.4 阻断条件（任一触发即不允许合入）
- 代码中仍存在对 `ThresholdIntradayStrategy` 的运行时引用。
- 仍存在“策略类内硬编码 if/else 信号判定”作为主执行路径。
- profile 驱动路径无法独立输出标准 action schema。

## 25. v0.3 冻结条款总览（1页）

### 25.1 执行主链路（FROZEN）
- 唯一执行路径：
  - `FeaturePipeline -> RegimeScoringEngine -> SignalEngine -> RiskEngine -> Action Output`
- `RegimeScoringEngine` 内部固定：
  - `RuleEngine -> GroupAggregator -> RegimeEngine -> ScoreSynthesizer`

### 25.2 Regime / Classifier（FROZEN）
- `Regime` 不输出独立 gate，no-trade 通过 `state_group_weights=0` 达成。
- `classifier` 语义固定：
  - `priority` 升序 first-match；
  - 单条规则 `conditions[]` 为 AND；
  - `between` 为闭区间 `[min, max]`；
  - 条件缺失/NaN/超 staleness 判 `false`；
  - 全未命中回退 `default_state`。
- `classifier.inputs` 与启用规则 `conditions[].ref` 必须集合完全一致：
  - `UNUSED_CLASSIFIER_INPUT`
  - `UNDECLARED_CLASSIFIER_REF`

### 25.3 评分机制（FROZEN）
- 仅保留 `score_fn + input_refs + params`，禁止 `compute/normalize/quality`。
- `nan_policy` 仅允许 `neutral_zero`：
  - 输入缺失/NaN/warmup 不足 -> `rule_score=0.0`；
  - 不触发组内重归一化。
- `score_fn` 仅允许内置白名单：
  - `trend_score/momentum_score/direction_score/volume_score/pullback_score`
  - `custom_udf` 在 v0.3 禁用。
- `input_refs` 必须满足 `score_fn` 签名（数量+顺序）；
  - 角色绑定固定为 `input_roles[i] <-> input_refs[i]`；
  - `len(input_refs)` 不匹配时报 `SCORE_FN_INPUT_ARITY_MISMATCH`。

### 25.4 信号层（FROZEN）
- 规则表达统一使用 `score_range`（`number|null`，`null` 表示无界，禁用 `+inf/-inf` 文本）。
- `priority_rank` 在 `entry/exit/hold` 全局唯一，升序 first-match。
- `reason_code_map` 必须覆盖所有启用规则 `id`。
- 若不存在启用的 `HOLD` 兜底规则，规则区间必须完整覆盖 `[-1, 1]`，否则 precompile 失败。

### 25.5 风险层（FROZEN）
- 输出契约：
  - `ENTER_* => size > 0`
  - `EXIT/HOLD => size = 0`
- `stop_loss/take_profit` 输出必须是绝对价格位。
- mode 白名单：
  - `size_model`: `fixed_fraction`
  - `stop_model`: `fixed_pct | atr_multiple`
  - `take_profit_model`: `fixed_pct | rr_multiple`

### 25.6 编译期阻断（FROZEN）
- 关键依赖不可解析、状态/权重覆盖不完整、枚举非法、参数越界、规则冲突不可解，均 precompile 失败。
- precompile 必须产出：
  - `strategy_profile.resolved.json`
  - `feature_catalog.json`
  - `signal_spec.resolved.json`
  - `risk_spec.resolved.json`
  - `required_indicator_plan_by_tf`
  - `resolved_input_bindings`（`rule_id -> {role: feature_ref}`）

### 25.7 版本边界（BACKLOG）
- 以下不纳入 v0.3 实现阻断：
  - `q_g` 动态质量因子（v0.3 固定 `q_g=1.0`）
  - `nan_policy` 的 `skip/fail`
  - 受控 `custom_udf` 扩展

## 26. Implementation Tasks（执行拆分）
- 本需求对应的实现任务拆分清单见：
  - `docs/03-delivery/roadmap/implementation-tasks-v0.3.md`
- 任务命名统一使用：`XTR-SP-XXX`。
- 默认按依赖顺序推进：`001 -> 002 -> ... -> 010`。
- “最小闭环完成”判定：`XTR-SP-001 ~ XTR-SP-007` 全部完成。
