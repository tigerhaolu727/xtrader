"""Trend indicator families."""

from xtrader.strategies.feature_engine.indicators.trend.dmi import DMIIndicator
from xtrader.strategies.feature_engine.indicators.trend.ema import EMAIndicator
from xtrader.strategies.feature_engine.indicators.trend.frama import FRAMAIndicator
from xtrader.strategies.feature_engine.indicators.trend.ht_trendline import HTTrendlineIndicator
from xtrader.strategies.feature_engine.indicators.trend.kama import KAMAIndicator
from xtrader.strategies.feature_engine.indicators.trend.ma import MAIndicator
from xtrader.strategies.feature_engine.indicators.trend.macd import MACDIndicator
from xtrader.strategies.feature_engine.indicators.trend.macd_state import MACDStateIndicator
from xtrader.strategies.feature_engine.indicators.trend.mama import MAMAIndicator
from xtrader.strategies.feature_engine.indicators.trend.support_proximity import SupportProximityIndicator
from xtrader.strategies.feature_engine.indicators.trend.trix import TRIXIndicator

__all__ = [
    "DMIIndicator",
    "EMAIndicator",
    "FRAMAIndicator",
    "HTTrendlineIndicator",
    "KAMAIndicator",
    "MAIndicator",
    "MACDIndicator",
    "MACDStateIndicator",
    "MAMAIndicator",
    "SupportProximityIndicator",
    "TRIXIndicator",
]
