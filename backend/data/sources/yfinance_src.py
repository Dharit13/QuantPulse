import logging
import threading
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class _RateLimiter:
    """Simple token-bucket rate limiter: max `rate` calls per `per` seconds."""

    def __init__(self, rate: int = 5, per: float = 5.0):
        self._rate = rate
        self._per = per
        self._lock = threading.Lock()
        self._tokens = float(rate)
        self._last = time.monotonic()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._rate, self._tokens + elapsed * (self._rate / self._per))
            self._last = now
            if self._tokens < 1:
                sleep_time = (1 - self._tokens) * (self._per / self._rate)
                time.sleep(sleep_time)
                self._tokens = 0
            else:
                self._tokens -= 1


_yf_limiter = _RateLimiter(rate=5, per=5.0)


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
            _yf_limiter.acquire()
            t = yf.Ticker(ticker)
            if start and end:
                df = t.history(start=start, end=end, auto_adjust=True)
            else:
                df = t.history(period=period, auto_adjust=True)
            if df.empty:
                logger.warning("No data returned for %s", ticker)
            return df
        except Exception:
            logger.debug("Failed to fetch OHLCV for %s", ticker)
            return pd.DataFrame()

    def get_multiple_ohlcv(
        self,
        tickers: list[str],
        period: str = "2y",
    ) -> dict[str, pd.DataFrame]:
        results = {}
        logger.info("Batch-fetching %d tickers via yf.download...", len(tickers))
        try:
            _yf_limiter.acquire()
            batch = yf.download(
                tickers,
                period=period,
                group_by="ticker",
                threads=False,
                progress=False,
            )
            if batch.empty:
                return results
            if len(tickers) == 1:
                if not batch.empty:
                    results[tickers[0]] = batch
            else:
                for ticker in tickers:
                    try:
                        df = batch[ticker].dropna(how="all")
                        if not df.empty:
                            results[ticker] = df
                    except (KeyError, Exception):
                        pass
        except Exception:
            logger.warning("Batch download failed, falling back to individual fetches")
            for ticker in tickers:
                try:
                    df = self.get_daily_ohlcv(ticker, period=period)
                    if not df.empty:
                        results[ticker] = df
                except Exception:
                    pass
        logger.info("Fetch complete — %d/%d tickers", len(results), len(tickers))
        return results

    def get_current_price(self, ticker: str) -> float | None:
        try:
            _yf_limiter.acquire()
            t = yf.Ticker(ticker)
            info = t.fast_info
            return float(info.get("lastPrice", info.get("previousClose", 0)))
        except Exception:
            logger.debug("Failed to get current price for %s", ticker)
            return None

    def get_fundamentals(self, ticker: str) -> dict:
        try:
            _yf_limiter.acquire()
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
            logger.debug("Failed to get fundamentals for %s", ticker)
            return {}

    def get_cashflow(self, ticker: str) -> pd.DataFrame:
        """Annual cash flow statement. Rows include 'Free Cash Flow',
        'Operating Cash Flow', 'Capital Expenditure', etc."""
        try:
            _yf_limiter.acquire()
            t = yf.Ticker(ticker)
            cf = t.cashflow
            if cf is None or cf.empty:
                return pd.DataFrame()
            return cf
        except Exception:
            logger.debug("Failed to get cash flow for %s", ticker)
            return pd.DataFrame()

    def get_shares_outstanding(self, ticker: str) -> int | None:
        """Shares outstanding from yfinance info."""
        try:
            _yf_limiter.acquire()
            t = yf.Ticker(ticker)
            info = t.info
            return info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        except Exception:
            logger.debug("Failed to get shares outstanding for %s", ticker)
            return None

    def get_options_chain(self, ticker: str, expiry: str | None = None) -> dict:
        try:
            _yf_limiter.acquire()
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
            logger.debug("Failed to get options for %s", ticker)
            return {"expiries": [], "calls": pd.DataFrame(), "puts": pd.DataFrame()}

    def get_earnings_dates(self, ticker: str) -> pd.DataFrame:
        try:
            _yf_limiter.acquire()
            t = yf.Ticker(ticker)
            return t.earnings_dates
        except Exception:
            logger.debug("Failed to get earnings dates for %s", ticker)
            return pd.DataFrame()

    def get_earnings_history(self, ticker: str) -> list[dict]:
        """Return recent quarterly EPS actual vs estimate with surprise %.

        Each dict: {date, eps_actual, eps_estimate, surprise_pct, revenue_surprise_pct}
        Falls back gracefully if yfinance doesn't have the data.
        """
        try:
            _yf_limiter.acquire()
            t = yf.Ticker(ticker)
            df = t.earnings_dates
            if df is None or df.empty:
                return []

            records: list[dict] = []
            for idx, row in df.iterrows():
                actual = row.get("Reported EPS")
                estimate = row.get("EPS Estimate")
                if pd.isna(actual) or pd.isna(estimate):
                    continue

                surprise_pct = (actual - estimate) / abs(estimate) * 100 if estimate != 0 else 0.0
                report_date = pd.Timestamp(idx).date() if isinstance(idx, pd.Timestamp) else idx

                records.append(
                    {
                        "date": report_date,
                        "eps_actual": float(actual),
                        "eps_estimate": float(estimate),
                        "surprise_pct": round(float(surprise_pct), 2),
                    }
                )

            # Only return past earnings (not future estimates)
            today = datetime.now().date()
            records = [r for r in records if r["date"] <= today]
            records.sort(key=lambda r: r["date"], reverse=True)
            return records[:12]
        except Exception:
            logger.debug("Failed to get earnings history for %s", ticker)
            return []

    def get_analyst_revisions(self, ticker: str, limit: int = 20) -> list[dict]:
        """Individual analyst upgrade/downgrade events with price targets.

        Each dict: {date, firm, action, from_grade, to_grade, price_target}
        """
        try:
            _yf_limiter.acquire()
            t = yf.Ticker(ticker)
            ud = t.upgrades_downgrades
            if ud is None or ud.empty:
                return []

            records: list[dict] = []
            for idx, row in ud.head(limit).iterrows():
                rev_date = idx.date() if hasattr(idx, "date") else idx
                action_raw = str(row.get("Action", "")).lower()
                action_map = {
                    "up": "upgrade",
                    "down": "downgrade",
                    "main": "maintains",
                    "reit": "reiterates",
                    "init": "initiates",
                }
                action = action_map.get(action_raw, action_raw)
                records.append(
                    {
                        "date": rev_date,
                        "firm": row.get("Firm", ""),
                        "action": action,
                        "from_grade": row.get("FromGrade", ""),
                        "to_grade": row.get("ToGrade", ""),
                        "price_target": row.get("currentPriceTarget"),
                    }
                )
            return records
        except Exception:
            logger.debug("Failed to get analyst revisions for %s", ticker)
            return []

    def get_recommendation_trends(self, ticker: str) -> list[dict]:
        """Return analyst recommendation trends (upgrades, downgrades, etc).

        Each dict: {date, strong_buy, buy, hold, sell, strong_sell}
        """
        try:
            _yf_limiter.acquire()
            t = yf.Ticker(ticker)
            recs = t.recommendations
            if recs is None or recs.empty:
                return []

            records: list[dict] = []
            for idx, row in recs.iterrows():
                rec_date = idx.date() if hasattr(idx, "date") else idx
                records.append(
                    {
                        "date": rec_date,
                        "strong_buy": int(row.get("strongBuy", row.get("To Grade", 0)) or 0)
                        if "strongBuy" in row.index
                        else 0,
                        "buy": int(row.get("buy", 0) or 0) if "buy" in row.index else 0,
                        "hold": int(row.get("hold", 0) or 0) if "hold" in row.index else 0,
                        "sell": int(row.get("sell", 0) or 0) if "sell" in row.index else 0,
                        "strong_sell": int(row.get("strongSell", 0) or 0) if "strongSell" in row.index else 0,
                    }
                )

            records.sort(key=lambda r: r["date"], reverse=True)
            return records[:24]
        except Exception:
            logger.debug("Failed to get recommendation trends for %s", ticker)
            return []

    def get_earnings_day_return(self, ticker: str, earnings_date: str) -> float | None:
        """Get the single-day return on an earnings date (gap + intraday).

        Returns the close-to-close return as a percentage.
        """
        try:
            _yf_limiter.acquire()
            t = yf.Ticker(ticker)
            start = pd.Timestamp(earnings_date) - timedelta(days=5)
            end = pd.Timestamp(earnings_date) + timedelta(days=3)
            df = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
            if df.empty or len(df) < 2:
                return None

            target = pd.Timestamp(earnings_date)
            if target in df.index:
                idx = df.index.get_loc(target)
            else:
                idx = df.index.searchsorted(target)
                if idx >= len(df):
                    return None

            if idx < 1:
                return None

            prev_close = float(df["Close"].iloc[idx - 1])
            earn_close = float(df["Close"].iloc[idx])
            return round((earn_close - prev_close) / prev_close * 100, 2) if prev_close > 0 else None
        except Exception:
            logger.debug("Failed to get earnings day return for %s", ticker)
            return None


yfinance_source = YFinanceSource()
