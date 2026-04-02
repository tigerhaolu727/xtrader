"""Strategy composition and signal management for action-driven trading."""

from xtrader.strategies.base import (
    ActionStrategyResult,
    BaseActionStrategy,
    BaseStrategy,
    DEFAULT_ACTION_OUTPUT_SCHEMA,
    StrategyContext,
    StrategyResult,
    StrategySpec,
    TradeAction,
)
from xtrader.strategies.builtin_strategies import ProfileActionStrategy
from xtrader.strategies.feature_engine import FeaturePipeline
from xtrader.strategies.risk import RiskCheckResult, RiskConfig, RiskManager
from xtrader.strategies.state_machine import (
    PositionSnapshot,
    PositionState,
    PositionStateMachine,
    TransitionResult,
)

__all__ = [
    "ActionStrategyResult",
    "BaseActionStrategy",
    "BaseStrategy",
    "DEFAULT_ACTION_OUTPUT_SCHEMA",
    "FeaturePipeline",
    "PositionSnapshot",
    "PositionState",
    "PositionStateMachine",
    "ProfileActionStrategy",
    "RiskCheckResult",
    "RiskConfig",
    "RiskManager",
    "StrategyContext",
    "StrategyResult",
    "StrategySpec",
    "TradeAction",
    "TransitionResult",
]
