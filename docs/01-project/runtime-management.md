# 声明式策略配置与 FeatureRef 运行管理机制（v1）

## 1. 目标
- 为多周期、多指标、多参数策略提供统一运行管理机制。
- 解决参数变化导致评分规则/策略规则与特征列名不同步的问题。
- 支持参数寻优场景下的 trial 级预编译、校验与可追溯运行。

## 2. 适用范围
- 声明式策略配置（多周期、指标、评分、融合、风险）。
- `FeatureRef` 语义引用规范。
- `feature_catalog` 自动生成与运行期映射。
- 参数模板 -> 候选参数 -> trial 预编译 -> 回测执行流程。

## 3. 核心原则
1. 单一配置源：策略相关配置统一由声明式配置驱动。
2. 引用解耦：评分规则/策略规则仅依赖 `FeatureRef`，不直接依赖物理列名。
3. 预编译先行：trial 运行前必须通过配置编译与依赖校验。
4. trial 隔离：每个 trial 独立生成 catalog 与哈希，避免互相污染。
5. 可追溯：运行结果可回溯到配置、映射与校验证据。

## 4. 术语定义
- `FeatureRef`：稳定语义引用，格式 `{timeframe}.{instance_id}.{output_key}`。
- `physical_col`：特征实际列名，如 `ema_12`、`macd_12_26_9_hist`。
- `feature_catalog`：`FeatureRef -> physical_col` 的映射表（trial 级）。
- `trial`：一次参数组合运行单元。
- `precompile`：trial 执行前的解析、映射与依赖校验阶段。

## 5. 配置契约（最小集）
- `strategy_id`
- `execution_timeframe`
- `timeframes`
- `indicator_plan_by_tf`
- `scoring_rules`
- `fusion_rules`
- `risk_rules`

### 5.1 indicator_plan_by_tf 规则
- 每条记录必须包含：`instance_id`, `family`, `params`。
- 同一 timeframe 内 `instance_id` 唯一。
- 同一 timeframe 内禁止重复 `family + resolved_params` 组合。

### 5.2 规则引用规范
- 评分规则与策略规则只允许引用 `FeatureRef`。
- 禁止在规则中硬编码物理列名。

## 6. FeatureRef 规范
### 6.1 格式
- `{timeframe}.{instance_id}.{output_key}`

### 6.2 output_key
- 单输出指标固定为 `value`。
- 多输出指标按指标后缀字典：
  - `macd`: `line/signal/hist`
  - `bollinger`: `mid/up/low`
  - `kd`: `k/d/j`
  - `dmi`: `plus_di/minus_di/adx`

### 6.3 稳定性规则
- 参数调整时优先保持 `instance_id` 不变，保障引用稳定。
- 若删除或重命名 `instance_id`，必须同步更新规则引用，否则预编译失败。

## 7. feature_catalog 生成机制
### 7.1 生成时机
- 运行前自动生成（precompile 阶段）。
- 可落盘到 run/trial 目录用于审计。

### 7.2 生成输入
- `indicator_plan_by_tf`
- 指标族参数 schema 与输出后缀规则

### 7.3 生成输出字段（建议）
- `feature_ref`
- `physical_col`
- `timeframe`
- `family`
- `instance_id`
- `resolved_params`
- `params_hash`

## 8. 预编译（precompile）流程
1. 读取 trial 配置并解析默认参数。
2. 生成 `indicator_plan_resolved`。
3. 生成 `feature_catalog`。
4. 校验评分与策略规则中的全部 `FeatureRef`。
5. 生成编译摘要与哈希，校验通过后才进入回测。

### 8.1 必须校验项（fail-fast）
- 引用存在性：`FeatureRef` 必须可解析。
- 输出键合法性：`output_key` 必须在该 family 输出字典中。
- 周期合法性：引用 timeframe 必须在策略声明中存在。
- 参数合法性：符合对应 family 参数 schema。

### 8.2 失败行为
- 任一校验失败，当前 trial 直接中止，不进入执行阶段。
- 输出结构化错误：`rule_id`, `feature_ref`, `error_code`, `detail`。

## 9. 参数寻优集成（trial 模式）
### 9.1 生命周期
1. 参数模板生成候选参数。
2. 每个候选生成独立 trial 配置。
3. 每个 trial 独立 precompile。
4. precompile 通过后执行回测。
5. 按 trial 落盘产物与结果。

### 9.2 trial 必备产物
- `resolved_config.json`
- `feature_catalog.json`
- `precompile_report.json`
- `metrics.json`（或回测结果文件）
- `config_hash`
- `catalog_hash`
- `trial_id`

### 9.3 缓存一致性
- 特征缓存 key 必须包含：`params_hash + timeframe + data_range + code_version`。

## 10. 运行期访问机制
- 提供 `FeatureAccessor.get(feature_ref)`。
- accessor 通过 `feature_catalog` 完成 `FeatureRef -> physical_col` 映射。
- 评分与策略逻辑统一通过 accessor 读取特征，不直接索引列名。

## 11. 兼容性与边界
- 兼容评分型策略与直判型策略并存。
- 不要求所有策略都使用评分系统，但使用评分系统的策略必须遵守 `FeatureRef` 契约。
- `BaseActionStrategy` 输出 schema 维持不变。

## 12. 验收标准（v1）
1. 调整指标参数（保持 `instance_id`）后，规则无需改写仍可运行。
2. 调换 `indicator_plan` 顺序不影响规则解析与结果正确性。
3. 删除被引用指标时，precompile 能准确报错并阻断运行。
4. 多 trial 并行时，catalog 不串用、不污染。
5. 任一 trial 结果均可追溯到其 `resolved_config` 与 `feature_catalog`。

## 13. 后续扩展
- 引入规则版本化与迁移脚本（`rule_schema_version`）。
- 增加 FeatureRef 静态检查器（提交前 lint）。
- 将 precompile 结果接入 UI 诊断面板显示。

## 14. 与 XTR-SP 链路的操作衔接
- Profile 策略研发与回测操作手册：
  - `docs/02-strategy/playbooks/strategy-profile-playbook.md`
- 路径语义对齐：
  - `reports/backtests/strategy/...`：策略研究回测（ProfileAction + event-driven）
  - `runs/...`：Runtime 编排/trial/perf 运行产物
- 新增 profile 的推荐顺序：
  1. 基于模板创建配置：`configs/strategy-profiles/templates/profile_v0.3.minimal.json`
  2. 执行 precompile 校验，先消除配置错误码；
  3. 运行 BTCUSDT 5m smoke 回测，确认关键产物齐全；
  4. 再进入调参和效果评估。
