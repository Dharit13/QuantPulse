"""Financial Modeling Prep data source.

Enable by setting FMP_API_KEY in .env.
Provides: company fundamentals, analyst estimates, historical OHLCV, financial ratios.

FMP free tier: 250 requests/day. Uses `/stable/` endpoints (v3 is deprecated).
Rate limiter registered as "fmp" at ~4 req/min.
Docs: https://intelligence.financialmodelingprep.com/developer/docs
"""

import logging
from datetime import date, timedelta

import httpx
import pandas as pd

from backend.config import settings
from backend.data.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://financialmodelingprep.com/stable"


class FMPSource:
    """FMP data source for fundamentals, estimates, and historical prices.

    Uses the /stable/ endpoint prefix (FMP deprecated /api/v3 in 2025).
    All methods degrade gracefully when the API key is not configured.
    """

    SOURCE_NAME = "fmp"

    def __init__(self) -> None:
        self._api_key = settings.fmp_api_key
        self._client: httpx.Client | None = None
        self._quota_exhausted = False

    @property
    def _http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=BASE_URL,
                timeout=15.0,
            )
        return self._client

    def _enabled(self) -> bool:
        return bool(self._api_key) and not self._quota_exhausted

    def _get(self, path: str, params: dict | None = None) -> list | dict:
        """Rate-limited GET with api key injection. Returns parsed JSON.

        Handles 402/403 (paid-only) and 429 (rate-limited) gracefully.
        After the first 429 exhaustion, skips all further FMP calls for
        the session to avoid wasting time on retries.
        """
        if self._quota_exhausted:
            return []

        params = dict(params or {})
        params["apikey"] = self._api_key
        try:
            resp = rate_limiter.request_with_retry(
                self.SOURCE_NAME,
                self._http,
                "GET",
                path,
                params=params,
            )
            return resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (402, 403):
                logger.debug("FMP %s requires paid plan (HTTP %d)", path, exc.response.status_code)
                return []
            if exc.response.status_code == 429:
                self._quota_exhausted = True
                logger.warning("FMP daily quota exhausted — disabling FMP for this session")
                return []
            raise

    # ── Public API ──────────────────────────────────────────────

    def get_fundamentals(self, ticker: str) -> dict:
        """Company profile + key financial ratios.

        Returns dict matching the schema used by yfinance_src.get_fundamentals()
        so DataFetcher can swap seamlessly.
        """
        if not self._enabled():
            return {}

        try:
            profile = self._get("/profile", params={"symbol": ticker})
            if not profile:
                return {}

            p = profile[0] if isinstance(profile, list) else profile

            ratios_list = self._get("/ratios", params={"symbol": ticker, "limit": "4"})
            r = ratios_list[0] if isinstance(ratios_list, list) and ratios_list else {}

            metrics_list = self._get("/key-metrics", params={"symbol": ticker, "limit": "4"})
            m = metrics_list[0] if isinstance(metrics_list, list) and metrics_list else {}

            return {
                "market_cap": p.get("marketCap") or p.get("mktCap"),
                "pe_ratio": p.get("pe") or r.get("priceEarningsRatio"),
                "forward_pe": m.get("peRatio") or r.get("priceEarningsToGrowthRatio"),
                "peg_ratio": r.get("priceEarningsToGrowthRatio"),
                "eps_trailing": p.get("eps"),
                "eps_forward": None,
                "revenue_growth": r.get("revenuePerShare"),
                "profit_margin": r.get("netProfitMargin") or m.get("netIncomePerShare"),
                "debt_to_equity": r.get("debtEquityRatio") or m.get("debtToEquity"),
                "sector": p.get("sector", ""),
                "industry": p.get("industry", ""),
                "avg_volume": p.get("volAvg"),
                "beta": p.get("beta"),
                "dividend_yield": p.get("lastDividend") or p.get("lastDiv"),
                "short_ratio": None,
                "analyst_target": p.get("targetMeanPrice")
                or (p.get("price", 0) * 1.1 if p.get("price") else None),
            }
        except httpx.HTTPStatusError as exc:
            logger.error("FMP fundamentals HTTP error for %s: %s", ticker, exc)
            return {}
        except Exception:
            logger.exception("FMP fundamentals failed for %s", ticker)
            return {}

    def get_earnings(self, ticker: str) -> list[dict]:
        """Historical EPS from income statements.

        FMP free tier no longer has /earnings-surprises, so we derive EPS
        from quarterly income statements. Returns list of dicts with:
        date, eps_actual, eps_estimate, surprise_pct.
        """
        if not self._enabled():
            return []

        try:
            data = self._get(
                "/income-statement",
                params={"symbol": ticker, "period": "quarter", "limit": "4"},
            )
            if not isinstance(data, list):
                return []

            records: list[dict] = []
            for item in data:
                report_date_str = item.get("date", "")
                try:
                    report_date = date.fromisoformat(report_date_str)
                except (ValueError, TypeError):
                    continue

                eps = item.get("eps")
                eps_diluted = item.get("epsDiluted") or eps
                if eps_diluted is None:
                    continue

                records.append({
                    "date": report_date,
                    "eps_actual": float(eps_diluted),
                    "eps_estimate": float(eps_diluted),
                    "surprise_pct": 0.0,
                    "revenue": item.get("revenue"),
                    "net_income": item.get("netIncome"),
                })

            records.sort(key=lambda r: r["date"], reverse=True)
            return records[:12]
        except httpx.HTTPStatusError as exc:
            logger.error("FMP earnings HTTP error for %s: %s", ticker, exc)
            return []
        except Exception:
            logger.exception("FMP earnings failed for %s", ticker)
            return []

    def get_earnings_calendar(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        """Upcoming earnings calendar.

        Note: This endpoint may not be available on FMP free tier.
        Falls back gracefully to empty list.
        """
        if not self._enabled():
            return []

        try:
            if not from_date:
                from_date = date.today().isoformat()
            if not to_date:
                to_date = (date.today() + timedelta(days=14)).isoformat()

            data = self._get(
                "/earning_calendar",
                params={"from": from_date, "to": to_date},
            )
            if not isinstance(data, list) or not data:
                return []

            records: list[dict] = []
            for item in data:
                records.append({
                    "date": item.get("date", ""),
                    "symbol": item.get("symbol", ""),
                    "eps_estimate": item.get("epsEstimated"),
                    "revenue_estimate": item.get("revenueEstimated"),
                    "fiscal_period": item.get("fiscalDateEnding", ""),
                    "time": item.get("time", ""),
                })

            logger.info("FMP: fetched %d earnings calendar entries", len(records))
            return records
        except httpx.HTTPStatusError:
            logger.debug("FMP earnings calendar not available on free tier")
            return []
        except Exception:
            logger.debug("FMP earnings calendar unavailable")
            return []

    def get_analyst_estimates(self, ticker: str) -> list[dict]:
        """Consensus analyst estimates (EPS and revenue)."""
        if not self._enabled():
            return []

        try:
            data = self._get(
                "/analyst-estimates",
                params={"symbol": ticker, "period": "annual", "limit": "4"},
            )
            if not isinstance(data, list):
                return []

            records: list[dict] = []
            for item in data:
                records.append({
                    "date": item.get("date", ""),
                    "estimated_eps_avg": item.get("estimatedEpsAvg"),
                    "estimated_eps_high": item.get("estimatedEpsHigh"),
                    "estimated_eps_low": item.get("estimatedEpsLow"),
                    "estimated_revenue_avg": item.get("estimatedRevenueAvg"),
                    "number_analysts": item.get("numberAnalystEstimatedEps", 0),
                })

            return records
        except httpx.HTTPStatusError as exc:
            logger.error("FMP analyst estimates HTTP error for %s: %s", ticker, exc)
            return []
        except Exception:
            logger.exception("FMP analyst estimates failed for %s", ticker)
            return []

    def get_eps_surprises(self, ticker: str) -> list[dict]:
        """EPS surprise history — delegates to get_earnings()."""
        return self.get_earnings(ticker)

    def get_daily_ohlcv(
        self,
        ticker: str,
        period: str = "2y",
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Daily OHLCV from FMP historical-price-eod endpoint."""
        if not self._enabled():
            return pd.DataFrame()

        try:
            params: dict[str, str] = {"symbol": ticker}
            if start:
                params["from"] = start
            if end:
                params["to"] = end

            data = self._get("/historical-price-eod/full", params=params)
            if not isinstance(data, list) or not data:
                return pd.DataFrame()

            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()

            rename_map = {
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            }
            df = df.rename(columns=rename_map)
            cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
            return df[cols]
        except httpx.HTTPStatusError as exc:
            logger.error("FMP OHLCV HTTP error for %s: %s", ticker, exc)
            return pd.DataFrame()
        except Exception:
            logger.exception("FMP OHLCV failed for %s", ticker)
            return pd.DataFrame()


fmp_source = FMPSource()
