"""Backtesting components for strategy validation."""

from .event_driven import (
    EventDrivenBacktestConfig,
    EventDrivenBacktestResult,
    EventDrivenBacktestSummary,
    build_strategy_report_root,
    run_event_driven_backtest,
    write_event_driven_outputs,
    write_strategy_event_driven_outputs,
)
from .leakage_guard import find_execution_lag_violations, find_unclosed_bar_violations
from .offline_viewer import initialize_offline_report_viewer

__all__: list[str] = [
    "EventDrivenBacktestConfig",
    "EventDrivenBacktestResult",
    "EventDrivenBacktestSummary",
    "build_strategy_report_root",
    "find_execution_lag_violations",
    "find_unclosed_bar_violations",
    "initialize_offline_report_viewer",
    "run_event_driven_backtest",
    "write_event_driven_outputs",
    "write_strategy_event_driven_outputs",
]
