import logging

import pandas as pd

from backend.data.cache import data_cache
from backend.data.sources.yfinance_src import yfinance_source

logger = logging.getLogger(__name__)

CROSS_ASSET_TICKERS = {
    # Treasury yields
    "10y_yield": "^TNX",
    "5y_yield": "^FVX",
    "13w_yield": "^IRX",
    # Volatility
    "vix": "^VIX",
    # Commodities
    "oil": "CL=F",
    "gold": "GC=F",
    "copper": "HG=F",
    # Dollar
    "dxy": "DX-Y.NYB",
    # Credit
    "hy_bond": "HYG",
    "ig_bond": "LQD",
    # Equity indices
    "spy": "SPY",
    "qqq": "QQQ",
    "iwm": "IWM",
}

SECTOR_ETFS = {
    "technology": "XLK",
    "financials": "XLF",
    "energy": "XLE",
    "healthcare": "XLV",
    "consumer_discretionary": "XLY",
    "consumer_staples": "XLP",
    "industrials": "XLI",
    "materials": "XLB",
    "utilities": "XLU",
    "real_estate": "XLRE",
    "communication": "XLC",
}


class CrossAssetData:
    """Fetches and computes cross-asset indicators used by regime detection and cross-asset strategy."""

    def fetch_all(self, period: str = "1y") -> dict[str, pd.DataFrame]:
        cache_key = f"cross_asset_all:{period}"
        cached = data_cache.get(cache_key)
        if cached is not None and isinstance(cached, dict):
            return cached

        all_tickers = list(CROSS_ASSET_TICKERS.values())
        data = yfinance_source.get_multiple_ohlcv(all_tickers, period=period)

        result = {}
        for name, ticker in CROSS_ASSET_TICKERS.items():
            if ticker in data and not data[ticker].empty:
                result[name] = data[ticker]
            else:
                logger.warning("Missing cross-asset data for %s (%s)", name, ticker)

        return result

    def get_vix(self, period: str = "1y") -> pd.DataFrame:
        return yfinance_source.get_daily_ohlcv("^VIX", period=period)

    def get_spy(self, period: str = "2y") -> pd.DataFrame:
        return yfinance_source.get_daily_ohlcv("SPY", period=period)

    def get_yield_curve_data(self, period: str = "1y") -> dict[str, pd.DataFrame]:
        tickers = ["^TNX", "^FVX", "^IRX"]
        data = yfinance_source.get_multiple_ohlcv(tickers, period=period)
        return {
            "10y": data.get("^TNX", pd.DataFrame()),
            "5y": data.get("^FVX", pd.DataFrame()),
            "2y": data.get("^IRX", pd.DataFrame()),
        }

    def compute_yield_curve_slope(self, period: str = "1y") -> pd.Series:
        """10Y - 2Y yield spread."""
        yields = self.get_yield_curve_data(period)
        if yields["10y"].empty or yields["2y"].empty:
            return pd.Series(dtype=float)
        ten_y = yields["10y"]["Close"].reindex(yields["2y"].index, method="ffill")
        two_y = yields["2y"]["Close"]
        return (ten_y - two_y).dropna()

    def compute_credit_spread(self, period: str = "1y") -> pd.Series:
        """HYG/LQD ratio as credit spread proxy (lower = wider spreads = risk-off)."""
        data = yfinance_source.get_multiple_ohlcv(["HYG", "LQD"], period=period)
        if "HYG" not in data or "LQD" not in data:
            return pd.Series(dtype=float)
        hyg = data["HYG"]["Close"]
        lqd = data["LQD"]["Close"]
        common = hyg.index.intersection(lqd.index)
        return (hyg.loc[common] / lqd.loc[common]).dropna()

    def get_sector_etf_data(self, period: str = "1y") -> dict[str, pd.DataFrame]:
        tickers = list(SECTOR_ETFS.values())
        data = yfinance_source.get_multiple_ohlcv(tickers, period=period)
        return {name: data.get(ticker, pd.DataFrame()) for name, ticker in SECTOR_ETFS.items()}


cross_asset_data = CrossAssetData()
