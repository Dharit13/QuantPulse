import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class YFinanceSource:
    """Primary free data source wrapping yfinance."""

    def get_daily_ohlcv(
        self,
        ticker: str,
        period: str = "2y",
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        try:
            t = yf.Ticker(ticker)
            if start and end:
                df = t.history(start=start, end=end, auto_adjust=True)
            else:
                df = t.history(period=period, auto_adjust=True)
            if df.empty:
                logger.warning("No data returned for %s", ticker)
            return df
        except Exception:
            logger.exception("Failed to fetch OHLCV for %s", ticker)
            return pd.DataFrame()

    def get_multiple_ohlcv(
        self,
        tickers: list[str],
        period: str = "2y",
    ) -> dict[str, pd.DataFrame]:
        results = {}
        try:
            data = yf.download(tickers, period=period, group_by="ticker", auto_adjust=True, threads=True)
            if isinstance(data.columns, pd.MultiIndex):
                for ticker in tickers:
                    try:
                        results[ticker] = data[ticker].dropna(how="all")
                    except KeyError:
                        logger.warning("Ticker %s not found in batch download", ticker)
            else:
                # Single ticker case
                results[tickers[0]] = data.dropna(how="all")
        except Exception:
            logger.exception("Batch download failed, falling back to individual fetches")
            for ticker in tickers:
                results[ticker] = self.get_daily_ohlcv(ticker, period=period)
        return results

    def get_current_price(self, ticker: str) -> float | None:
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            return float(info.get("lastPrice", info.get("previousClose", 0)))
        except Exception:
            logger.exception("Failed to get current price for %s", ticker)
            return None

    def get_fundamentals(self, ticker: str) -> dict:
        try:
            t = yf.Ticker(ticker)
            info = t.info
            return {
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "eps_trailing": info.get("trailingEps"),
                "eps_forward": info.get("forwardEps"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margin": info.get("profitMargins"),
                "debt_to_equity": info.get("debtToEquity"),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "avg_volume": info.get("averageVolume"),
                "beta": info.get("beta"),
                "dividend_yield": info.get("dividendYield"),
                "short_ratio": info.get("shortRatio"),
                "analyst_target": info.get("targetMeanPrice"),
            }
        except Exception:
            logger.exception("Failed to get fundamentals for %s", ticker)
            return {}

    def get_options_chain(self, ticker: str, expiry: str | None = None) -> dict:
        try:
            t = yf.Ticker(ticker)
            dates = t.options
            if not dates:
                return {"expiries": [], "calls": pd.DataFrame(), "puts": pd.DataFrame()}

            target = expiry if expiry and expiry in dates else dates[0]
            chain = t.option_chain(target)
            return {
                "expiries": list(dates),
                "calls": chain.calls,
                "puts": chain.puts,
                "expiry_used": target,
            }
        except Exception:
            logger.exception("Failed to get options for %s", ticker)
            return {"expiries": [], "calls": pd.DataFrame(), "puts": pd.DataFrame()}

    def get_earnings_dates(self, ticker: str) -> pd.DataFrame:
        try:
            t = yf.Ticker(ticker)
            return t.earnings_dates
        except Exception:
            logger.exception("Failed to get earnings dates for %s", ticker)
            return pd.DataFrame()


yfinance_source = YFinanceSource()
