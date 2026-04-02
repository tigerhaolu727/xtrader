# xtrader 全系统技术架构设计（v1）

## 1. 设计目标
| 目标ID | 设计目标 | 成功标准 |
|---|---|---|
| G1 | 研究可复现 | 同一数据与参数可稳定复现回测结果 |
| G2 | 决策可解释 | 每笔交易可追溯信号、风控与执行原因 |
| G3 | 实盘可运行 | 具备稳定下单、回报处理、状态恢复能力 |
| G4 | 风险可控制 | 组合级与策略级风控可前置拦截 |
| G5 | 系统可观测 | 运行指标、告警、审计日志完整 |

## 2. 主模块总览
| 主模块ID | 主模块 | 设计目标 | 当前状态 | 规划范围 |
|---|---|---|---|---|
| M1 | Data Foundation（数据底座） | 历史/实时数据标准化与资产化 | 已有主干 | 采集、清洗、重采样、对账、存储 |
| M2 | Strategy Intelligence（策略智能） | 信号生成与多周期融合 | 已有基础（XTR-019 已冻结 v1 运行契约） | 特征、评分、信号、策略协议 |
| M3 | Portfolio & Risk（组合与风控） | 资金分配与风险约束 | 部分缺失 | 组合层、约束层、风险预算 |
| M4 | Backtest & Research（回测研究） | 策略验证与实验迭代 | 已落地（含 Runtime Core v1 回测闭环） | 事件驱动回测、参数评估、泄漏防护 |
| M5 | Execution Runtime（执行运行时） | 实盘下单与事件驱动执行 | Backtest 编排已落地，Live 关键能力缺失 | OMS/EMS、事件总线、任务编排 |
| M6 | State & Ledger（状态与账本） | 可恢复、可审计的交易状态 | 关键缺失 | 订单/成交/持仓/权益账本与快照 |
| M7 | Reporting & UI（报告与分析） | 离线分析与可视化联动 | 已落地（Viewer 契约 v1 已接入） | run 产物、离线 UI、分析交互 |
| M8 | Governance & Ops（治理与运维） | 流程规范与发布运维 | 已有基础 | spec/validation、backlog、监控告警 |

## 3. 模块分解

### M1 Data Foundation（数据底座）
| 子模块 | 功能设计 | 当前实现 | 规划范围 |
|---|---|---|---|
| M1.1 Exchange Adapter | 对接交易所行情/账户接口 | 已有 Bitget 适配 | 扩展 WS、统一限流与重试 |
| M1.2 Ingestion Pipeline | 历史K线下载与补齐 | 已实现 sync/repair | 增加实时增量管道 |
| M1.3 Preprocess & QA | 数据清洗与有效性校验 | 部分实现 | 补齐异常值检测/插值/统一校验 |
| M1.4 Resample Engine | 多周期聚合 | 已实现 | 增加质量报告与口径版本化 |
| M1.5 Reconcile Engine | 本地与交易所对账 | 已实现 | 自动化巡检与告警联动 |
| M1.6 Storage | Parquet 分区与索引 | 已实现 | 扩展缓存层与冷热分层 |

### M2 Strategy Intelligence（策略智能）
| 子模块 | 功能设计 | 当前实现 | 规划范围 |
|---|---|---|---|
| M2.1 Strategy Protocol | 策略输入输出契约 | 已实现 | 增加多周期元信息字段 |
| M2.2 Feature Layer | 指标/特征计算 | 基础具备 | 完成五维评分特征化 |
| M2.3 Regime-Aware Scoring | 市场状态+评分+权重一体化 | 设计阶段 | 统一静态/动态权重、状态切换、防抖与归一化 |
| M2.4 Signal Engine | 分值映射动作 | 已有阈值策略 | 扩展信号强度分级、确认机制与冲突处理 |
| M2.5 Multi-TF Fusion | 多周期融合逻辑 | 未系统化 | 高周期方向与低周期择时规则化 |

#### M2 补充约束（评分型策略与直判策略并存）
1. 策略接口保持统一：均实现 `BaseActionStrategy.generate_actions(...)`，输出同一动作 schema。
2. 支持两类策略模式：
   - 评分型策略：在策略内部调用 `Regime-Aware Scoring` 生成 `score/signal` 后映射动作。
   - 直判型策略：可直接基于指标规则生成动作，不强制依赖评分系统。
3. 评分系统对外应保持单一入口，内部可拆分“状态判定/维度打分/权重分配/信号映射”子组件。

### M3 Portfolio & Risk（组合与风控）
| 子模块 | 功能设计 | 当前实现 | 规划范围 |
|---|---|---|---|
| M3.1 Position State | 持仓状态机 | 已实现 | 支持多策略共享仓位视图 |
| M3.2 Trade Risk | 单笔止损止盈与时停 | 已实现 | 增加波动率自适应阈值 |
| M3.3 Portfolio Allocator | 资金分配与仓位预算 | 缺失 | 策略配额、杠杆预算、相关性约束 |
| M3.4 Global Guard | 全局熔断与日损控制 | 部分实现 | 组合级风控门禁前置 |

### M4 Backtest & Research（回测研究）
| 子模块 | 功能设计 | 当前实现 | 规划范围 |
|---|---|---|---|
| M4.1 Event-driven Core | 动作驱动撮合与成本模型 | 已实现 | 细化成交模型（滑点/流动性） |
| M4.2 Leakage Guard | 前瞻偏差检测 | 已实现 | 与策略研发流程强绑定 |
| M4.3 Experiment Runner | 参数实验与批量回测 | 部分脚本化 | 统一实验配置与结果索引 |
| M4.4 Evaluation Metrics | 收益风险指标 | 已实现基础 | 加入策略特有诊断指标 |

### M5 Execution Runtime（执行运行时）
| 子模块 | 功能设计 | 当前实现 | 规划范围 |
|---|---|---|---|
| M5.1 OMS | 订单生命周期管理 | 缺失 | 下单、撤单、改单、幂等 |
| M5.2 EMS Gateway | 交易所执行通道 | 缺失 | REST+WS 执行与回报一致性 |
| M5.3 Event Bus | 实时事件总线 | 缺失 | 行情/订单/账户统一事件流 |
| M5.4 Runtime Orchestrator | 任务编排（回测/实盘共享抽象） | 已实现 Backtest-first RuntimeCore（非实盘） | 策略进程管理、重启恢复、Live Adapter |

### M6 State & Ledger（状态与账本）
| 子模块 | 功能设计 | 当前实现 | 规划范围 |
|---|---|---|---|
| M6.1 Order Ledger | 订单账本 | 缺失 | 状态追踪与审计 |
| M6.2 Trade Ledger | 成交账本 | 回测侧已有 | 实盘统一口径落盘 |
| M6.3 Position Ledger | 持仓快照 | 部分 | 跨重启恢复与对账 |
| M6.4 Equity Ledger | 权益与PnL | 回测侧已有 | 实盘分钟级权益曲线 |
| M6.5 Snapshot Store | 状态快照 | 缺失 | 崩溃恢复与回放 |

### M7 Reporting & UI（报告与分析）
| 子模块 | 功能设计 | 当前实现 | 规划范围 |
|---|---|---|---|
| M7.1 Run Artifact Schema | 标准产物契约 | 已实现 | 增强 `score/regime/weight/signal` 诊断字段与解释链路 |
| M7.2 Offline Viewer | 本地离线分析页面 | 已实现 | 继续优化交互与性能 |
| M7.3 Analysis Surfaces | K线/Equity/Timeline/Ledger 联动 | 已实现 | 增强策略语义可视化 |

### M8 Governance & Ops（治理与运维）
| 子模块 | 功能设计 | 当前实现 | 规划范围 |
|---|---|---|---|
| M8.1 Spec/Validation Flow | 研发流程守门 | 已实现 | 持续制度化 |
| M8.2 Backlog Memory | 延后任务记忆库 | 已实现 | 与任务升级流程联动 |
| M8.3 Strategy Memory | 长周期讨论沉淀 | 已实现 | 作为架构/策略共识底稿 |
| M8.4 Observability | 监控告警与审计 | 缺失 | 指标、报警、追踪、日志规范 |

## 4. 目标目录规划
| 目录 | 角色定位 |
|---|---|
| `src/xtrader/common` | 统一模型与基础类型 |
| `src/xtrader/exchanges` | 交易所适配 |
| `src/xtrader/data` | 数据采集、预处理、对账、资产化 |
| `src/xtrader/strategies` | 策略协议、特征、评分、信号生成、多周期融合 |
| `src/xtrader/portfolio` | 组合分配与约束（新增） |
| `src/xtrader/risk` | 统一风控引擎（新增，回测+实盘共用） |
| `src/xtrader/execution` | OMS/EMS/执行通道（扩展） |
| `src/xtrader/ledger` | 订单/成交/持仓/权益账本（新增） |
| `src/xtrader/runtime` | Runtime Core 编排（backtest-first）与 Live 适配扩展点 |
| `src/xtrader/backtests` | 事件驱动回测执行与结构化产物输出 |
| `src/xtrader/observability` | 监控、告警、审计（新增） |
| `docs` | 架构、策略、流程、backlog 与验证文档 |

## 5. 主业务链路
1. 市场数据进入 Data Foundation，形成标准化数据资产。
2. Strategy Intelligence 生成动作信号。
3. Portfolio & Risk 执行资金分配与风险准入。
4. Execution Runtime 执行订单并处理回报。
5. State & Ledger 持久化订单、成交、持仓与权益状态。
6. Reporting & UI 输出分析结果。
7. Governance & Ops 提供流程、监控与审计保障。

## 6. 分阶段实施建议
| 阶段 | 重点模块 | 阶段目标 |
|---|---|---|
| Phase 0（已完成） | XTR-019 M1~M5 | 完成 Runtime Core v1（Backtest-first）契约、编排、产物与可追溯闭环 |
| Phase 1 | M5 + M6 最小 Live 闭环 | 打通单策略单标的实盘执行、订单/成交/持仓恢复 |
| Phase 2 | M3 组合风控 | 增加资金分配、相关性约束与组合级风险预算 |
| Phase 3 | M8.4 可观测 | 完成监控告警、运行审计与追踪体系 |
| Phase 4 | M2.3 + M2.5 + M7 增强 | 完成 Regime-aware 评分闭环与多周期解释可视化 |

## 7. 关键接口边界约束
1. 策略层不直接写文件，只输出结构化动作。
2. 策略层输出风险意图（`stop_loss/take_profit` 参数），不负责真实成交价与成交成本计算。
3. 执行层不直接做策略判定，只处理订单执行与回报。
4. 风控层负责持仓后逐 bar 风险检查（止损/止盈/时停/日损），并可触发强制退出。
5. 回测与实盘尽量复用风控与账本口径，降低双轨偏差。
6. 评分系统与市场状态判定建议作为统一模块能力，对策略提供单一调用入口。
7. 文档治理遵循 Spec/Validation 流程，延后项进入 backlog。

## 8. XTR-019 Runtime Core v1 落地现状（截至 2026-04-01）
### 8.1 已实现范围（M1~M5）
| 里程碑 | 已实现能力 | 核心实现文件 |
|---|---|---|
| M1 配置与契约底座 | `schema_version=xtr_runtime_v1`、必填/默认值、`risk_rules` 约束、`trial_config(single/scenarios)` 契约 | `src/xtrader/runtime/config.py` |
| M2 预编译与试验编排 | `feature_catalog` 生成、`FeatureRef`/`output_key` 校验、scenario 原子覆盖、`warn_policy` 与多 trial 调度门禁 | `src/xtrader/runtime/precompile.py`、`src/xtrader/runtime/config.py`、`src/xtrader/runtime/core.py` |
| M3 执行闭环与交易语义 | `signal_time=t`、`execution_time=t+1`、`next_bar_open` 成交、SL/TP 后续 bar 生效、`SKIPPED` 与 `skip_reason` 语义 | `src/xtrader/backtests/event_driven.py`、`src/xtrader/runtime/core.py` |
| M4 运行产物与 Viewer 契约 | `runs/{run_id}` 单目录、`artifacts/*`、`data_snapshot/*`、`run_manifest` v1、`viewer_contract` 的 `READY/INVALID_RUN/NOT_AVAILABLE` | `src/xtrader/runtime/core.py`、`src/xtrader/backtests/event_driven.py` |
| M5 可追溯与非功能 | `config_hash/catalog_hash/params_hash`、`code_version/data_version`、`performance_log`、专项性能脚本与 nightly workflow | `src/xtrader/runtime/hash_utils.py`、`src/xtrader/runtime/core.py`、`scripts/runtime_v1_perf_check.py`、`.github/workflows/runtime-v1-perf.yml` |

### 8.2 测试与验证映射
| 里程碑 | 自动化测试（关键覆盖） | 验证文档与非功能证据 |
|---|---|---|
| M1+M2 | `tests/unit/runtime/test_runtime_v1.py`：配置校验、scenario 冲突、precompile 错误码、`warn_policy` 优先级与阻断 | `docs/03-delivery/validation/XTR-019.md`（M2 收口） |
| M3 | `tests/unit/backtests/test_event_driven.py`：`SKIPPED/NO_NEXT_BAR`、`next_bar_open`、SL/TP 时序、四表一致性 | `docs/03-delivery/validation/XTR-019.md`（M3 收口） |
| M4 | `tests/unit/runtime/test_runtime_v1.py`：`run_manifest` v1 字段、`dataset_index/snapshot_meta`、`viewer_contract` 降级 | `docs/03-delivery/validation/XTR-019.md`（M4 收口） |
| M5 | `tests/unit/runtime/test_runtime_v1.py`：traceability hash 稳定性、`code_version` fail-fast、`performance_log` 字段；`scripts/runtime_v1_perf_check.py`：A/B 阈值与回归阈值 | `docs/03-delivery/validation/XTR-019.md`（M5 收口）与 `runs/perf/runtime_v1/*` |

### 8.3 当前缺口与下一阶段重点
1. 当前 Runtime Core 仍是 backtest-first 形态，未接入实盘 OMS/EMS、订单事件总线与跨重启恢复。
2. 组合层资金分配与组合级风险预算尚未纳入 Runtime Core 主链路。
3. 下一阶段优先级：
   - 先完成 M5.1/M5.2/M5.3（OMS/EMS/Event Bus）最小 Live 闭环；
   - 再补 M6 账本快照恢复；
   - 最后把组合层（M3.3/M3.4）前置到执行准入。

## 9. Profile 主链路约定（XTR-SP）
1. 主链路策略入口固定为 `ProfileActionStrategy`，执行顺序为：
   - `FeaturePipeline -> RegimeScoringEngine -> SignalEngine -> RiskEngine -> Action Output`
2. 路径语义冻结：
   - 策略研究回测与离线分析产物：`reports/backtests/strategy/<strategy_slug>/<run_id>/`
   - Runtime 编排、trial 与性能回归产物：`runs/<run_id>/` 或 `runs/perf/...`
3. 新增策略默认流程：
   - 先改/新增 `StrategyProfile` 配置；
   - 再通过 precompile 校验；
   - 最后运行 profile smoke 回测生成标准产物。
4. 操作手册索引：
   - `docs/02-strategy/playbooks/strategy-profile-playbook.md`
