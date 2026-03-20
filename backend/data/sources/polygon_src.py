"""Polygon.io data source.

Enable by setting ENABLE_POLYGON=true and POLYGON_API_KEY in .env.
Provides: daily/intraday OHLCV, options chain with greeks, snapshot data.

Polygon Starter ($29/mo): delayed data, full history.
Polygon Developer ($79/mo): real-time + intraday.

Rate limits: free tier = 5/min, paid = effectively unlimited.
Docs: https://polygon.io/docs
"""

import logging
from datetime import date, timedelta

import httpx
import pandas as pd

from backend.config import settings
from backend.data.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"

PERIOD_MAP = {
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}


class PolygonSource:
    """Polygon.io data source for OHLCV, intraday bars, and options.

    All methods degrade gracefully when the API key is not configured
    or the feature flag is disabled.
    """

    SOURCE_NAME = "polygon"

    def __init__(self) -> None:
        self._api_key = settings.polygon_api_key
        self._client: httpx.Client | None = None

    @property
    def _http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=BASE_URL,
                timeout=20.0,
            )
        return self._client

    def _enabled(self) -> bool:
        return bool(self._api_key) and settings.enable_polygon

    def _get(self, path: str, params: dict | None = None) -> dict:
        """Rate-limited GET with apiKey injection."""
        params = dict(params or {})
        params["apiKey"] = self._api_key
        resp = rate_limiter.request_with_retry(
            self.SOURCE_NAME,
            self._http,
            "GET",
            path,
            params=params,
        )
        return resp.json()

    # ── OHLCV ───────────────────────────────────────────────────

    def get_daily_ohlcv(
        self,
        ticker: str,
        period: str = "2y",
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Daily OHLCV bars from Polygon aggregate endpoint."""
        if not self._enabled():
            return pd.DataFrame()

        try:
            if not end:
                end = date.today().isoformat()
            if not start:
                days = PERIOD_MAP.get(period, 730)
                start = (date.today() - timedelta(days=days)).isoformat()

            data = self._get(
                f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                params={"adjusted": "true", "sort": "asc", "limit": "5000"},
            )

            results = data.get("results", [])
            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results)
            df["date"] = pd.to_datetime(df["t"], unit="ms")
            df = df.set_index("date")
            df = df.rename(
                columns={
                    "o": "Open",
                    "h": "High",
                    "l": "Low",
                    "c": "Close",
                    "v": "Volume",
                }
            )
            return df[["Open", "High", "Low", "Close", "Volume"]]
        except httpx.HTTPStatusError as exc:
            logger.error("Polygon OHLCV HTTP error for %s: %s", ticker, exc)
            return pd.DataFrame()
        except Exception:
            logger.exception("Polygon OHLCV failed for %s", ticker)
            return pd.DataFrame()

    def get_intraday_bars(
        self,
        ticker: str,
        interval: str = "1",
        timespan: str = "minute",
        days_back: int = 5,
    ) -> pd.DataFrame:
        """Intraday bars (1-min, 5-min, etc.) from Polygon.

        Requires Polygon Developer plan ($79/mo) for real-time data.
        """
        if not self._enabled() or not settings.enable_intraday:
            return pd.DataFrame()

        try:
            end = date.today().isoformat()
            start = (date.today() - timedelta(days=days_back)).isoformat()

            data = self._get(
                f"/v2/aggs/ticker/{ticker}/range/{interval}/{timespan}/{start}/{end}",
                params={"adjusted": "true", "sort": "asc", "limit": "50000"},
            )

            results = data.get("results", [])
            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results)
            df["datetime"] = pd.to_datetime(df["t"], unit="ms")
            df = df.set_index("datetime")
            df = df.rename(
                columns={
                    "o": "Open",
                    "h": "High",
                    "l": "Low",
                    "c": "Close",
                    "v": "Volume",
                    "vw": "VWAP",
                    "n": "Transactions",
                }
            )
            cols = [c for c in ["Open", "High", "Low", "Close", "Volume", "VWAP", "Transactions"] if c in df.columns]
            return df[cols]
        except httpx.HTTPStatusError as exc:
            logger.error("Polygon intraday HTTP error for %s: %s", ticker, exc)
            return pd.DataFrame()
        except Exception:
            logger.exception("Polygon intraday failed for %s", ticker)
            return pd.DataFrame()

    # ── Options ─────────────────────────────────────────────────

    def get_options_chain(self, ticker: str) -> dict:
        """Options chain snapshot with basic contract data.

        Returns dict with "calls" and "puts" lists, each containing
        strike, expiry, bid, ask, volume, open_interest.
        """
        if not self._enabled():
            return {}

        try:
            data = self._get(
                f"/v3/snapshot/options/{ticker}",
                params={"limit": "250"},
            )
            results = data.get("results", [])
            if not results:
                return {}

            calls: list[dict] = []
            puts: list[dict] = []

            for r in results:
                details = r.get("details", {})
                day = r.get("day", {})
                greeks = r.get("greeks", {})
                underlying = r.get("underlying_asset", {})

                record = {
                    "strike": details.get("strike_price", 0),
                    "expiry": details.get("expiration_date", ""),
                    "contract_type": details.get("contract_type", ""),
                    "bid": day.get("close", 0),
                    "ask": day.get("close", 0),
                    "volume": day.get("volume", 0),
                    "open_interest": r.get("open_interest", 0),
                    "implied_vol": greeks.get("iv", 0),
                    "delta": greeks.get("delta", 0),
                    "gamma": greeks.get("gamma", 0),
                    "theta": greeks.get("theta", 0),
                    "vega": greeks.get("vega", 0),
                    "underlying_price": underlying.get("price", 0),
                }

                if details.get("contract_type") == "call":
                    calls.append(record)
                else:
                    puts.append(record)

            return {"calls": calls, "puts": puts}
        except httpx.HTTPStatusError as exc:
            logger.error("Polygon options chain HTTP error for %s: %s", ticker, exc)
            return {}
        except Exception:
            logger.exception("Polygon options chain failed for %s", ticker)
            return {}

    def get_options_chain_greeks(self, ticker: str) -> dict[float, dict]:
        """Options chain aggregated by strike with greeks — used by GEX computation.

        Returns dict mapping strike → {call_oi, put_oi, call_gamma, put_gamma}.
        """
        if not self._enabled():
            return {}

        chain = self.get_options_chain(ticker)
        if not chain:
            return {}

        strikes: dict[float, dict] = {}

        for call in chain.get("calls", []):
            s = call["strike"]
            if s not in strikes:
                strikes[s] = {"call_oi": 0, "put_oi": 0, "call_gamma": 0.0, "put_gamma": 0.0}
            strikes[s]["call_oi"] += call.get("open_interest", 0)
            strikes[s]["call_gamma"] = call.get("gamma", 0.0)

        for put in chain.get("puts", []):
            s = put["strike"]
            if s not in strikes:
                strikes[s] = {"call_oi": 0, "put_oi": 0, "call_gamma": 0.0, "put_gamma": 0.0}
            strikes[s]["put_oi"] += put.get("open_interest", 0)
            strikes[s]["put_gamma"] = put.get("gamma", 0.0)

        return strikes

    # ── Analyst Ratings (Benzinga) ──────────────────────────────

    def get_analyst_ratings(
        self,
        ticker: str,
        limit: int = 20,
    ) -> list[dict]:
        """Historical analyst ratings from Benzinga via Polygon.

        Returns list of dicts: {date, firm, action, from_grade, to_grade,
        price_target, ticker}.
        """
        if not self._enabled():
            return []

        try:
            data = self._get(
                "/benzinga/v1/ratings",
                params={
                    "ticker": ticker,
                    "limit": str(limit),
                    "sort": "date.desc",
                },
            )
            results = data.get("results", [])
            ratings: list[dict] = []
            for r in results:
                ratings.append(
                    {
                        "date": r.get("date", ""),
                        "firm": r.get("analyst", {}).get("name_full", "") or r.get("analyst_name", ""),
                        "action": r.get("rating_action", ""),
                        "from_grade": r.get("prior", {}).get("rating", ""),
                        "to_grade": r.get("current", {}).get("rating", ""),
                        "price_target": r.get("target_price", {}).get("current")
                        if isinstance(r.get("target_price"), dict)
                        else r.get("target_price"),
                        "ticker": r.get("ticker", ticker),
                    }
                )
            return ratings
        except httpx.HTTPStatusError as exc:
            logger.error("Polygon analyst ratings HTTP error for %s: %s", ticker, exc)
            return []
        except Exception:
            logger.exception("Polygon analyst ratings failed for %s", ticker)
            return []

    # ── Consensus Target (Benzinga) ─────────────────────────────

    def get_consensus_target(self, ticker: str) -> dict | None:
        """Analyst consensus price target from Benzinga via Polygon.

        Returns {target_consensus: float, target_high: float, target_low: float,
        num_analysts: int} or None.
        """
        if not self._enabled():
            return None
        try:
            data = self._get(
                f"/benzinga/v1/consensus-ratings/{ticker}",
                params={},
            )
            results = data.get("results", [])
            if not results:
                return None
            r = results[0] if isinstance(results, list) else results
            target = r.get("target_consensus") or r.get("targetConsensus")
            if target is None or not isinstance(target, (int, float)) or target <= 0:
                return None
            return {
                "target_consensus": float(target),
                "target_high": float(r.get("target_high") or r.get("targetHigh") or target),
                "target_low": float(r.get("target_low") or r.get("targetLow") or target),
                "num_analysts": int(r.get("num_analysts") or r.get("numAnalysts") or 0),
            }
        except Exception:
            logger.debug("Polygon consensus target failed for %s", ticker)
            return None

    # ── Short Volume ─────────────────────────────────────────────

    def get_short_volume(
        self,
        ticker: str,
        limit: int = 30,
    ) -> list[dict]:
        """Daily short volume data from FINRA via Polygon.

        Returns list of dicts: {date, short_volume, total_volume, short_ratio}.
        """
        if not self._enabled():
            return []

        try:
            data = self._get(
                "/stocks/v1/short-volume",
                params={
                    "ticker": ticker,
                    "limit": str(limit),
                    "sort": "date.desc",
                },
            )
            results = data.get("results", [])
            records: list[dict] = []
            for r in results:
                short_vol = (
                    (r.get("short_volume") or 0)
                    + (r.get("adf_short_volume") or 0)
                    + (r.get("nasdaq_carteret_short_volume") or 0)
                )
                total_vol = r.get("total_volume") or r.get("volume") or 0
                if total_vol == 0 and short_vol > 0:
                    total_vol = short_vol * 2
                short_ratio = round(short_vol / total_vol, 4) if total_vol > 0 else 0.0
                records.append(
                    {
                        "date": r.get("date", ""),
                        "short_volume": short_vol,
                        "total_volume": total_vol,
                        "short_ratio": short_ratio,
                        "ticker": r.get("ticker", ticker),
                    }
                )
            return records
        except httpx.HTTPStatusError as exc:
            logger.error("Polygon short volume HTTP error for %s: %s", ticker, exc)
            return []
        except Exception:
            logger.exception("Polygon short volume failed for %s", ticker)
            return []

    # ── Earnings (Benzinga) ──────────────────────────────────────

    def get_earnings(
        self,
        ticker: str,
        limit: int = 12,
    ) -> list[dict]:
        """Historical earnings data from Benzinga via Polygon.

        Returns list of dicts matching the schema used by yfinance/FMP:
        {date, eps_actual, eps_estimate, surprise_pct}.
        """
        if not self._enabled():
            return []

        try:
            data = self._get(
                "/benzinga/v1/earnings",
                params={
                    "ticker": ticker,
                    "limit": str(limit),
                    "sort": "date.desc",
                    "importance": "0",
                },
            )
            results = data.get("results", [])
            records: list[dict] = []
            for r in results:
                eps_actual = r.get("eps")
                eps_est = r.get("eps_est")
                surprise = r.get("eps_surprise_percent")
                if eps_actual is None and eps_est is None:
                    continue
                records.append(
                    {
                        "date": r.get("date", ""),
                        "eps_actual": float(eps_actual) if eps_actual is not None else None,
                        "eps_estimate": float(eps_est) if eps_est is not None else None,
                        "surprise_pct": float(surprise) if surprise is not None else None,
                        "revenue": r.get("revenue"),
                        "revenue_est": r.get("revenue_est"),
                    }
                )
            return records
        except httpx.HTTPStatusError as exc:
            logger.error("Polygon earnings HTTP error for %s: %s", ticker, exc)
            return []
        except Exception:
            logger.exception("Polygon earnings failed for %s", ticker)
            return []

    # ── Premarket ─────────────────────────────────────────────────

    def get_premarket_prices(self, tickers: list[str]) -> dict[str, float]:
        """Fetch premarket prices for a batch of tickers via Polygon snapshot.

        Uses /v2/snapshot/locale/us/markets/stocks/tickers which returns
        preMarket price data when available (before market open). Falls back
        to previous close if premarket data is absent.

        Returns a dict mapping ticker -> premarket price (only tickers with
        valid data are included).
        """
        if not self._enabled() or not tickers:
            return {}

        result: dict[str, float] = {}
        batch_size = 50
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i : i + batch_size]
            ticker_param = ",".join(batch)
            try:
                data = self._get(
                    "/v2/snapshot/locale/us/markets/stocks/tickers",
                    params={"tickers": ticker_param},
                )
                for item in data.get("tickers", []):
                    sym = item.get("ticker", "")
                    pre = item.get("preMarket", {})
                    pre_price = pre.get("close") or pre.get("open") if isinstance(pre, dict) else None
                    if pre_price and pre_price > 0:
                        result[sym] = float(pre_price)
                    else:
                        prev = item.get("prevDay", {})
                        prev_close = prev.get("c", 0) if isinstance(prev, dict) else 0
                        if prev_close and prev_close > 0:
                            result[sym] = float(prev_close)
            except Exception:
                logger.debug("Polygon premarket batch failed for chunk starting at %d", i)

        logger.info("Polygon premarket: got %d/%d prices", len(result), len(tickers))
        return result

    # ── Snapshot ─────────────────────────────────────────────────

    def get_snapshot(self, ticker: str) -> dict:
        """Real-time ticker snapshot (price, volume, prev close)."""
        if not self._enabled():
            return {}

        try:
            data = self._get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
            snapshot = data.get("ticker", data.get("results", {}))
            if not snapshot:
                return {}

            day = snapshot.get("day", {})
            prev = snapshot.get("prevDay", {})
            return {
                "price": day.get("c", 0),
                "open": day.get("o", 0),
                "high": day.get("h", 0),
                "low": day.get("l", 0),
                "volume": day.get("v", 0),
                "prev_close": prev.get("c", 0),
                "change_pct": snapshot.get("todaysChangePerc", 0),
            }
        except httpx.HTTPStatusError as exc:
            logger.error("Polygon snapshot HTTP error for %s: %s", ticker, exc)
            return {}
        except Exception:
            logger.exception("Polygon snapshot failed for %s", ticker)
            return {}


polygon_source = PolygonSource()
