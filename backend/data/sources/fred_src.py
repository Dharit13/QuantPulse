"""FRED (Federal Reserve Economic Data) source.

Enable by setting FRED_API_KEY in .env (free at https://fred.stlouisfed.org/docs/api/api_key.html).
Provides: treasury yields, yield curve spreads, credit spreads, inflation (CPI),
          unemployment, Fed Funds rate, dollar index — all macro inputs for regime
          detection and cross-asset signals.

Rate limit: 120 requests/min. Rate limiter registered as "fred" at 2 req/s.
"""

import logging
from datetime import date, timedelta

import httpx
import pandas as pd

from backend.config import settings
from backend.data.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://api.stlouisfed.org/fred"

# Key FRED series IDs mapped to human-readable names
SERIES_IDS: dict[str, str] = {
    # Treasury yields
    "10y_yield": "DGS10",
    "5y_yield": "DGS5",
    "2y_yield": "DGS2",
    "3mo_yield": "DGS3MO",
    "1y_yield": "DGS1",
    # Yield curve spread (pre-computed by FRED)
    "10y_2y_spread": "T10Y2Y",
    "10y_3mo_spread": "T10Y3M",
    # Rates
    "fed_funds": "FEDFUNDS",
    # Credit
    "hy_oas": "BAMLH0A0HYM2",  # ICE BofA High Yield OAS
    "ig_oas": "BAMLC0A4CBBB",  # ICE BofA BBB OAS
    # Inflation
    "cpi": "CPIAUCSL",  # CPI All Items
    "core_cpi": "CPILFESL",  # CPI Less Food & Energy
    "pce": "PCEPI",  # PCE Price Index
    # Labor
    "unemployment": "UNRATE",
    "initial_claims": "ICSA",  # Weekly initial jobless claims
    # Dollar
    "dxy": "DTWEXBGS",  # Trade-weighted USD index
    # Broad activity
    "industrial_prod": "INDPRO",  # Industrial Production Index
}


class FREDSource:
    """FRED data source for macro indicators used by regime detection and
    cross-asset signals.

    All methods degrade gracefully (return empty containers) when the API key
    is not configured or the request fails.
    """

    SOURCE_NAME = "fred"

    def __init__(self) -> None:
        self._api_key = settings.fred_api_key
        self._client: httpx.Client | None = None

    @property
    def _http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=BASE_URL,
                timeout=15.0,
            )
        return self._client

    def _enabled(self) -> bool:
        return bool(self._api_key)

    def _get(self, path: str, params: dict | None = None) -> dict:
        """Rate-limited GET with api_key injection. Returns parsed JSON."""
        params = dict(params or {})
        params["api_key"] = self._api_key
        params["file_type"] = "json"
        resp = rate_limiter.request_with_retry(
            self.SOURCE_NAME,
            self._http,
            "GET",
            path,
            params=params,
        )
        return resp.json()

    # ── Core data fetcher ───────────────────────────────────────

    def get_series(
        self,
        series_id: str,
        observation_start: str | None = None,
        observation_end: str | None = None,
        limit: int = 500,
    ) -> pd.Series:
        """Fetch a single FRED series as a pandas Series indexed by date.

        Args:
            series_id: FRED series identifier (e.g. "DGS10", "UNRATE").
            observation_start: ISO date string for start of range.
            observation_end: ISO date string for end of range.
            limit: Max number of observations (most recent).

        Returns:
            pd.Series with DatetimeIndex and float values. Empty Series on failure.
        """
        if not self._enabled():
            return pd.Series(dtype=float)

        try:
            params: dict[str, str] = {
                "series_id": series_id,
                "sort_order": "desc",
                "limit": str(limit),
            }
            if observation_start:
                params["observation_start"] = observation_start
            if observation_end:
                params["observation_end"] = observation_end

            data = self._get("/series/observations", params=params)
            observations = data.get("observations", [])

            if not observations:
                logger.warning("FRED: no observations for %s", series_id)
                return pd.Series(dtype=float)

            dates: list[str] = []
            values: list[float] = []
            for obs in observations:
                val = obs.get("value", ".")
                if val == "." or val is None:
                    continue
                try:
                    dates.append(obs["date"])
                    values.append(float(val))
                except (ValueError, TypeError, KeyError):
                    continue

            if not dates:
                return pd.Series(dtype=float)

            series = pd.Series(values, index=pd.to_datetime(dates), name=series_id)
            return series.sort_index()
        except httpx.HTTPStatusError as exc:
            logger.error("FRED HTTP error for %s: %s", series_id, exc)
            return pd.Series(dtype=float)
        except Exception:
            logger.exception("FRED fetch failed for %s", series_id)
            return pd.Series(dtype=float)

    def get_series_by_name(
        self,
        name: str,
        observation_start: str | None = None,
        limit: int = 500,
    ) -> pd.Series:
        """Fetch a FRED series using our human-readable name mapping.

        Args:
            name: Key from SERIES_IDS (e.g. "10y_yield", "unemployment").
        """
        series_id = SERIES_IDS.get(name)
        if not series_id:
            logger.warning("Unknown FRED series name: %s", name)
            return pd.Series(dtype=float)
        return self.get_series(series_id, observation_start=observation_start, limit=limit)

    # ── Higher-level macro indicators ──────────────────────────

    def get_yield_curve(self, lookback_days: int = 365) -> dict[str, pd.Series]:
        """Fetch treasury yields across the curve.

        Returns dict keyed by tenor name ("3mo", "1y", "2y", "5y", "10y")
        with pd.Series values.
        """
        if not self._enabled():
            return {}

        start = (date.today() - timedelta(days=lookback_days)).isoformat()
        tenor_map = {
            "3mo": "DGS3MO",
            "1y": "DGS1",
            "2y": "DGS2",
            "5y": "DGS5",
            "10y": "DGS10",
        }

        result: dict[str, pd.Series] = {}
        for tenor, series_id in tenor_map.items():
            series = self.get_series(series_id, observation_start=start)
            if not series.empty:
                result[tenor] = series

        return result

    def get_yield_curve_slope(self, lookback_days: int = 365) -> pd.Series:
        """10Y - 2Y yield spread as a time series.

        More precise than yfinance proxies because FRED publishes the actual
        constant-maturity rates.
        """
        if not self._enabled():
            return pd.Series(dtype=float)

        start = (date.today() - timedelta(days=lookback_days)).isoformat()
        spread = self.get_series("T10Y2Y", observation_start=start)
        if not spread.empty:
            return spread

        # Fall back to computing from individual series
        ten_y = self.get_series("DGS10", observation_start=start)
        two_y = self.get_series("DGS2", observation_start=start)
        if ten_y.empty or two_y.empty:
            return pd.Series(dtype=float)

        common_idx = ten_y.index.intersection(two_y.index)
        return (ten_y.loc[common_idx] - two_y.loc[common_idx]).dropna()

    def get_credit_spread(self, lookback_days: int = 365) -> pd.Series:
        """High-yield OAS (option-adjusted spread) as a time series.

        Higher OAS = wider credit spreads = risk-off. This is a more direct
        measure than the HYG/LQD ratio proxy used by cross_asset.py.
        """
        if not self._enabled():
            return pd.Series(dtype=float)

        start = (date.today() - timedelta(days=lookback_days)).isoformat()
        return self.get_series("BAMLH0A0HYM2", observation_start=start)

    def get_macro_snapshot(self) -> dict[str, float | None]:
        """Latest values for key macro indicators.

        Returns a flat dict for use in regime detection and dashboard display.
        """
        if not self._enabled():
            return {}

        snapshot: dict[str, float | None] = {}
        indicators = [
            "10y_yield",
            "2y_yield",
            "3mo_yield",
            "10y_2y_spread",
            "10y_3mo_spread",
            "fed_funds",
            "hy_oas",
            "unemployment",
            "dxy",
        ]

        for name in indicators:
            series = self.get_series_by_name(name, limit=5)
            snapshot[name] = float(series.iloc[-1]) if not series.empty else None

        return snapshot

    def get_inflation_data(self, lookback_months: int = 60) -> dict[str, pd.Series]:
        """CPI and Core CPI time series for inflation monitoring."""
        if not self._enabled():
            return {}

        start = (date.today() - timedelta(days=lookback_months * 31)).isoformat()
        result: dict[str, pd.Series] = {}

        for name in ("cpi", "core_cpi", "pce"):
            series = self.get_series_by_name(name, observation_start=start)
            if not series.empty:
                result[name] = series

        return result

    def compute_cpi_yoy(self, lookback_months: int = 60) -> pd.Series:
        """Year-over-year CPI change (%) — the headline inflation number."""
        if not self._enabled():
            return pd.Series(dtype=float)

        start = (date.today() - timedelta(days=lookback_months * 31)).isoformat()
        cpi = self.get_series("CPIAUCSL", observation_start=start)
        if cpi.empty or len(cpi) < 13:
            return pd.Series(dtype=float)

        return cpi.pct_change(periods=12).dropna() * 100


fred_source = FREDSource()
