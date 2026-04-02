"""Strategy profile schema gate modules."""

from xtrader.strategy_profiles.errors import StrategyProfileContractError
from xtrader.strategy_profiles.loader import LoadedStrategyProfile, StrategyProfileLoader
from xtrader.strategy_profiles.precompile import StrategyProfilePrecompileEngine, StrategyProfilePrecompileResult
from xtrader.strategy_profiles.risk_engine import RiskEngine, RiskEngineResult
from xtrader.strategy_profiles.regime_scoring import RegimeScoringEngine, RegimeScoringResult, run_score_fn_series
from xtrader.strategy_profiles.schema_registry import load_schema_file, schema_root_dir
from xtrader.strategy_profiles.signal_engine import SignalEngine, SignalEngineResult

__all__ = [
    "LoadedStrategyProfile",
    "RiskEngine",
    "RiskEngineResult",
    "RegimeScoringEngine",
    "RegimeScoringResult",
    "SignalEngine",
    "SignalEngineResult",
    "StrategyProfileContractError",
    "StrategyProfileLoader",
    "StrategyProfilePrecompileEngine",
    "StrategyProfilePrecompileResult",
    "load_schema_file",
    "run_score_fn_series",
    "schema_root_dir",
]
