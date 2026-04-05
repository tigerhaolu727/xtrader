"""Indicator registry and defaults for feature-engine pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from xtrader.strategies.feature_engine.errors import xtr018_error
from xtrader.strategies.feature_engine.indicators.base import BaseIndicator
from xtrader.strategies.feature_engine.indicators.oscillator.kd import KDIndicator
from xtrader.strategies.feature_engine.indicators.oscillator.rsi import RSIIndicator
from xtrader.strategies.feature_engine.indicators.oscillator.wr import WRIndicator
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
from xtrader.strategies.feature_engine.indicators.volatility.atr import ATRIndicator
from xtrader.strategies.feature_engine.indicators.volatility.atr_pct_rank import ATRPctRankIndicator
from xtrader.strategies.feature_engine.indicators.volatility.bollinger import BollingerIndicator
from xtrader.strategies.feature_engine.indicators.volatility.stddev import StdDevIndicator
from xtrader.strategies.feature_engine.indicators.volume.mfi import MFIIndicator
from xtrader.strategies.feature_engine.indicators.volume.volume_ma import VolumeMAIndicator
from xtrader.strategies.feature_engine.indicators.volume.volume_variation import VolumeVariationIndicator


@dataclass(slots=True)
class IndicatorRegistry:
    """Registry mapping indicator family names to implementations."""

    _families: dict[str, BaseIndicator] = field(default_factory=dict)

    def register(self, indicator: BaseIndicator) -> None:
        family = str(indicator.name).strip().lower()
        if not family:
            raise xtr018_error("PLAN_UNKNOWN_FAMILY", "empty family name")
        if family in self._families:
            raise xtr018_error("PLAN_UNKNOWN_FAMILY", f"duplicate registry family: {family}")
        self._families[family] = indicator

    def get(self, family: str) -> BaseIndicator:
        key = str(family).strip().lower()
        if key not in self._families:
            raise xtr018_error("PLAN_UNKNOWN_FAMILY", key)
        return self._families[key]

    def families(self) -> tuple[str, ...]:
        return tuple(sorted(self._families.keys()))


def build_default_indicator_registry() -> IndicatorRegistry:
    registry = IndicatorRegistry()
    for indicator in (
        MAIndicator(),
        EMAIndicator(),
        FRAMAIndicator(),
        HTTrendlineIndicator(),
        KAMAIndicator(),
        MACDIndicator(),
        MACDStateIndicator(),
        MAMAIndicator(),
        SupportProximityIndicator(),
        TRIXIndicator(),
        DMIIndicator(),
        RSIIndicator(),
        KDIndicator(),
        WRIndicator(),
        ATRIndicator(),
        ATRPctRankIndicator(),
        BollingerIndicator(),
        StdDevIndicator(),
        MFIIndicator(),
        VolumeMAIndicator(),
        VolumeVariationIndicator(),
    ):
        registry.register(indicator)
    return registry


__all__ = [
    "IndicatorRegistry",
    "build_default_indicator_registry",
]
