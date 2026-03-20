"""FINRA ATS (Alternative Trading System) dark pool volume data.

Free public data from https://otctransparency.finra.org
Provides: weekly dark pool volume by ticker (delayed 2-4 weeks).

Use case for swing trading:
  - Stocks with persistently high/rising dark pool % of total volume
    suggest institutional accumulation not visible on lit exchanges.
  - Week-over-week dark pool volume increase is a leading indicator.
  - Z-score of dark pool % identifies anomalous institutional interest.

No API key needed — FINRA publishes downloadable data files.
"""

import logging
from datetime import date, datetime, timedelta

import httpx
import numpy as np
import pandas as pd

from backend.data.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# FINRA OTC transparency API
FINRA_API_URL = "https://api.finra.org/data/group/otcMarket/name/weeklySummary"

# Fallback: direct FINRA data page
FINRA_DATA_URL = "https://otctransparency.finra.org/otctransparency/AtsData"


class FINRASource:
    """FINRA ATS dark pool volume data source.

    Provides delayed (2-4 week) dark pool volume data for detecting
    institutional accumulation patterns over swing-trading timeframes.
    """

    SOURCE_NAME = "finra"

    def __init__(self) -> None:
        self._client: httpx.Client | None = None
        self._cache: dict[str, tuple[datetime, pd.DataFrame]] = {}
        self._cache_ttl_hours: float = 24.0

    @property
    def _http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=30.0,
                headers={
                    "User-Agent": "QuantPulse/2.0",
                    "Accept": "application/json",
                },
            )
        return self._client

    def _get_cached(self, key: str) -> pd.DataFrame | None:
        if key in self._cache:
            cached_at, df = self._cache[key]
            if (datetime.now() - cached_at).total_seconds() < self._cache_ttl_hours * 3600:
                return df
        return None

    def _set_cached(self, key: str, df: pd.DataFrame) -> None:
        self._cache[key] = (datetime.now(), df)

    # ── Core data fetch ─────────────────────────────────────────

    def get_weekly_ats_volume(
        self,
        ticker: str,
        weeks_back: int = 12,
    ) -> pd.DataFrame:
        """Fetch weekly ATS (dark pool) volume for a ticker.

        Returns DataFrame with columns: week_start, ats_volume, total_volume,
        ats_pct (dark pool as % of total), trades_count.

        Data is delayed 2-4 weeks per FINRA policy.
        """
        cache_key = f"ats_weekly:{ticker}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            data = self._fetch_ats_data(ticker, weeks_back)
            if data.empty:
                return pd.DataFrame()

            self._set_cached(cache_key, data)
            return data
        except Exception:
            logger.exception("FINRA ATS fetch failed for %s", ticker)
            return pd.DataFrame()

    def _fetch_ats_data(self, ticker: str, weeks_back: int) -> pd.DataFrame:
        """Fetch ATS data from FINRA's API."""
        try:
            end_date = date.today()
            start_date = end_date - timedelta(weeks=weeks_back)

            resp = rate_limiter.request_with_retry(
                self.SOURCE_NAME,
                self._http,
                "POST",
                FINRA_API_URL,
                json={
                    "fields": [
                        "weekStartDate",
                        "totalWeeklyShareQuantity",
                        "totalWeeklyTradeCount",
                        "lastUpdateDate",
                    ],
                    "dateRangeFilters": [
                        {
                            "fieldName": "weekStartDate",
                            "startDate": start_date.isoformat(),
                            "endDate": end_date.isoformat(),
                        }
                    ],
                    "domainFilters": [
                        {
                            "fieldName": "issueSymbolIdentifier",
                            "values": [ticker.upper()],
                        }
                    ],
                    "limit": 100,
                    "sortFields": ["-weekStartDate"],
                },
            )
            data = resp.json()

            if not data:
                return pd.DataFrame()

            records: list[dict] = []
            for item in data:
                week_start = item.get("weekStartDate", "")
                ats_volume = item.get("totalWeeklyShareQuantity", 0)
                trade_count = item.get("totalWeeklyTradeCount", 0)

                records.append(
                    {
                        "week_start": week_start,
                        "ats_volume": int(ats_volume),
                        "trades_count": int(trade_count),
                    }
                )

            if not records:
                return pd.DataFrame()

            df = pd.DataFrame(records)
            df["week_start"] = pd.to_datetime(df["week_start"])
            df = df.sort_values("week_start").reset_index(drop=True)
            return df
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 404):
                logger.debug("FINRA ATS data not available for %s (HTTP %d)", ticker, exc.response.status_code)
            else:
                logger.warning("FINRA ATS HTTP error for %s: %s", ticker, exc)
            return pd.DataFrame()
        except Exception:
            logger.debug("FINRA ATS API request failed for %s, returning empty", ticker)
            return pd.DataFrame()

    # ── Dark Pool Analysis ──────────────────────────────────────

    def compute_dark_pool_metrics(
        self,
        ticker: str,
        weeks_back: int = 12,
    ) -> dict:
        """Compute dark pool activity metrics for swing trading signals.

        Returns dict with:
          - avg_weekly_volume: average ATS volume over the lookback
          - recent_volume: most recent week's ATS volume
          - volume_trend: week-over-week change (positive = increasing)
          - volume_zscore: z-score of recent volume vs history
          - weeks_increasing: consecutive weeks of rising dark pool volume
          - signal_score: 0-100 composite score for institutional accumulation
        """
        df = self.get_weekly_ats_volume(ticker, weeks_back=weeks_back)

        if df.empty or len(df) < 3:
            return {
                "avg_weekly_volume": 0,
                "recent_volume": 0,
                "volume_trend": 0.0,
                "volume_zscore": 0.0,
                "weeks_increasing": 0,
                "signal_score": 0.0,
            }

        volumes = df["ats_volume"].values

        avg_vol = float(np.mean(volumes))
        recent_vol = float(volumes[-1])
        std_vol = float(np.std(volumes)) if len(volumes) > 1 else 1.0

        # Z-score of most recent week
        zscore = (recent_vol - avg_vol) / max(std_vol, 1.0)

        # Week-over-week trend (% change)
        if len(volumes) >= 2 and volumes[-2] > 0:
            wow_change = (volumes[-1] - volumes[-2]) / volumes[-2]
        else:
            wow_change = 0.0

        # Consecutive weeks increasing
        weeks_inc = 0
        for i in range(len(volumes) - 1, 0, -1):
            if volumes[i] > volumes[i - 1]:
                weeks_inc += 1
            else:
                break

        # Composite scoring for institutional accumulation
        score = 0.0
        if zscore > 1.0:
            score += min(30.0, zscore * 15.0)
        if wow_change > 0.1:
            score += min(25.0, wow_change * 50.0)
        if weeks_inc >= 3:
            score += min(25.0, weeks_inc * 7.0)
        if recent_vol > avg_vol * 1.5:
            score += 20.0

        return {
            "avg_weekly_volume": int(avg_vol),
            "recent_volume": int(recent_vol),
            "volume_trend": round(wow_change, 4),
            "volume_zscore": round(zscore, 2),
            "weeks_increasing": weeks_inc,
            "signal_score": min(100.0, round(score, 2)),
        }

    def scan_for_accumulation(
        self,
        tickers: list[str],
        min_score: float = 40.0,
        weeks_back: int = 12,
    ) -> list[dict]:
        """Scan a list of tickers for dark pool accumulation signals.

        Returns tickers sorted by signal_score descending.
        """
        results: list[dict] = []

        for ticker in tickers:
            try:
                metrics = self.compute_dark_pool_metrics(ticker, weeks_back=weeks_back)
                if metrics["signal_score"] >= min_score:
                    metrics["ticker"] = ticker
                    results.append(metrics)
            except Exception:
                logger.debug("Dark pool scan failed for %s", ticker)

        results.sort(key=lambda r: r["signal_score"], reverse=True)
        logger.info("FINRA: %d tickers with dark pool accumulation signal (>%.0f score)", len(results), min_score)
        return results


finra_source = FINRASource()
