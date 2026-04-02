# 写死策略下线与入口收敛 (XTR-SP-008)

> 历史说明（2026-04-02）：本任务最初目标为“主入口收敛 + legacy 保留”。后续在 `XTR-SP-011` 中已确认并执行“Threshold 全量下线（含 legacy 路径删除）”，本文件保留作为阶段性历史记录。

## Intent
- `XTR-SP-007` 已完成 profile 引擎最小闭环，但主入口仍同时暴露 `ThresholdIntradayStrategy`，存在“写死策略与配置引擎并存”的歧义。
- 若不收敛入口，后续开发仍可能误走旧路径，削弱“主链路仅 profile 驱动”的目标。
- 本任务目标是将主链路收敛为 `ProfileActionStrategy`，并将 `ThresholdIntradayStrategy` 降级为 legacy 兼容路径。

## Requirement
### 功能目标
- 从主入口移除 `ThresholdIntradayStrategy`：
  - `xtrader.strategies`
  - `xtrader.strategies.builtin`
  - `xtrader.strategies.builtin_strategies`
- 主入口仅保留 `ProfileActionStrategy` 作为推荐执行路径。
- 保留 legacy 兼容能力：
  - `xtrader.strategies.intraday.ThresholdIntradayStrategy` 继续可用；
  - 原 `threshold_intraday.py` 实现文件保留。
- 清理测试中的主链路强耦合引用：
  - 主链路测试不再通过 `xtrader.strategies` 直接引用 Threshold；
  - legacy 用例改为显式从 legacy 路径导入。

### 非目标 / 范围外
- 不在本任务删除 `ThresholdIntradayStrategy` 实现代码（仅降级为 legacy）。
- 不在本任务切换历史回测产物命名。
- 不在本任务改动 `ProfileActionStrategy` 计算逻辑。

### 输入输出 / 接口
- 主入口行为变化：
  - `from xtrader.strategies import ProfileActionStrategy` 可用；
  - `from xtrader.strategies import ThresholdIntradayStrategy` 不再作为主链路导出。
- legacy 行为保持：
  - `from xtrader.strategies.intraday import ThresholdIntradayStrategy` 可用。

## Design
### 核心思路与架构
- 入口收敛采用“导出层改造 + 测试分层”：
  - 导出层：在 `__init__/builtin` 中仅导出 Profile；
  - 兼容层：`intraday.py` 保留 Threshold re-export；
  - 测试层：区分主链路测试与 legacy 兼容测试。

### 数据/接口/模型
- 需调整文件：
  - `src/xtrader/strategies/__init__.py`
  - `src/xtrader/strategies/builtin.py`
  - `src/xtrader/strategies/builtin_strategies/__init__.py`
  - `tests/unit/strategies/test_builtin.py`
  - `tests/unit/strategies/test_intraday.py`
  - `tests/unit/backtests/test_event_driven.py`（import 路径调整）

### 风险与权衡
- 风险 1：删除导出可能导致现有引用报错。
  - 处理：保留 legacy 导入路径并在测试中显式验证。
- 风险 2：主链路回归被误判为功能退化。
  - 处理：保留 event-driven 旧策略测试，但改为 legacy 导入，明确其“兼容验证”定位。

## Acceptance
- `xtrader.strategies`、`xtrader.strategies.builtin`、`xtrader.strategies.builtin_strategies` 不再导出 Threshold。
- `xtrader.strategies.intraday.ThresholdIntradayStrategy` 仍可导入并通过既有行为测试。
- 相关单测通过，且 `ProfileActionStrategy` 主链路测试不受影响。
- 无新增循环依赖或导入错误。

## Notes
- 依赖：
  - `docs/03-delivery/specs/XTR-SP-007.md`
  - `docs/03-delivery/roadmap/implementation-tasks-v0.3.md`
  - `docs/02-strategy/requirements/five-min-regime-momentum-v0.3.md`
- 里程碑对齐：
  - 本任务完成后，M4 进入 `XTR-SP-009`（E2E 回测与基线产物）。
