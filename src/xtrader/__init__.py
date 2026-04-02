"""XTrader package scaffold for Bitget-focused quantitative research."""
from importlib import metadata

from . import common
from .exchanges import ExchangeClient

try:
    __version__ = metadata.version("xtrader")
except metadata.PackageNotFoundError:  # pragma: no cover - fallback for editable installs
    __version__ = "0.0.0"

__all__ = ["__version__", "ExchangeClient", "common"]
