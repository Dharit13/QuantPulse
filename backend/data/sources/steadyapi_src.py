"""SteadyAPI data source — institutional options flow and unusual activity.

SteadyAPI ($15/mo Starter) provides:
  - Options flow: large institutional sweeps, blocks, whale trades
  - Unusual options activity: contracts with volume >> open interest

Enable by setting STEADYAPI_API_KEY in .env.

Feeds into:
  - Catalyst Sub-C (institutional flow signal)
  - Flow Imbalance strategy (unusual volume detection)
"""

import logging
import re
from datetime import datetime

import httpx

from backend.config import settings
from backend.data.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://api.steadyapi.com/v1/markets/options"

# SteadyAPI trade conditions that indicate institutional activity
SWEEP_CONDITIONS = {"SLCN", "SLFT", "SLMN", "MLCN", "MLFT", "MLMN"}
BLOCK_CONDITIONS = {"BLCN", "BLFT", "BLMN"}
INSTITUTIONAL_CONDITIONS = SWEEP_CONDITIONS | BLOCK_CONDITIONS


def _parse_premium(raw: str) -> float:
    """Parse premium strings like '$41,500,000' or '41500000' to float."""
    if not raw:
        return 0.0
    cleaned = re.sub(r"[,$]", "", str(raw))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _parse_int(raw: str) -> int:
    """Parse comma-separated int strings like '10,000' to int."""
    if not raw:
        return 0
    cleaned = re.sub(r"[,]", "", str(raw))
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def _parse_pct(raw: str) -> float:
    """Parse percentage strings like '48.50%' to float."""
    if not raw:
        return 0.0
    cleaned = str(raw).replace("%", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _parse_trade_time(raw: str) -> datetime | None:
    """Parse trade time like '02/22/24 12:23:58' to datetime."""
    if not raw:
        return None
    for fmt in ("%m/%d/%y %H:%M:%S", "%m/%d/%y", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def _normalize_flow_record(raw: dict) -> dict:
    """Convert raw SteadyAPI options-flow record to clean typed dict."""
    premium = _parse_premium(raw.get("premium", ""))
    return {
        "symbol": raw.get("baseSymbol", ""),
        "option_symbol": raw.get("symbol", ""),
        "option_type": raw.get("symbolType", ""),  # "Call" or "Put"
        "strike": float(raw.get("strikePrice", 0) or 0),
        "expiration": raw.get("expiration", ""),
        "dte": int(raw.get("dte", 0) or 0),
        "underlying_price": float(raw.get("lastPrice", 0) or 0),
        "trade_price": float(raw.get("tradePrice", 0) or 0),
        "trade_size": _parse_int(raw.get("tradeSize", "")),
        "side": raw.get("side", ""),  # "ask", "bid", "mid"
        "premium": premium,
        "volume": _parse_int(raw.get("volume", "")),
        "open_interest": _parse_int(raw.get("openInterest", "")),
        "implied_vol": _parse_pct(raw.get("volatility", "")),
        "delta": float(raw.get("delta", 0) or 0),
        "trade_condition": raw.get("tradeCondition", ""),
        "label": raw.get("label", ""),  # "BuyToOpen", "SellToOpen", etc.
        "trade_time": _parse_trade_time(raw.get("tradeTime", "")),
        "is_sweep": raw.get("tradeCondition", "") in SWEEP_CONDITIONS,
        "is_block": raw.get("tradeCondition", "") in BLOCK_CONDITIONS,
        "is_institutional": raw.get("tradeCondition", "") in INSTITUTIONAL_CONDITIONS,
    }


def _normalize_unusual_record(raw: dict) -> dict:
    """Convert raw SteadyAPI unusual-options-activity record to clean typed dict."""
    vol = _parse_int(raw.get("volume", ""))
    oi = _parse_int(raw.get("openInterest", ""))
    return {
        "symbol": raw.get("baseSymbol", ""),
        "option_symbol": raw.get("symbol", ""),
        "option_type": raw.get("symbolType", ""),
        "strike": float(raw.get("strikePrice", 0) or 0),
        "expiration": raw.get("expirationDate", ""),
        "dte": int(raw.get("daysToExpiration", 0) or 0),
        "underlying_price": float(raw.get("baseLastPrice", 0) or 0),
        "bid": float(raw.get("bidPrice", 0) or 0),
        "ask": float(raw.get("askPrice", 0) or 0),
        "mid": float(raw.get("midpoint", 0) or 0),
        "last": float(raw.get("lastPrice", 0) or 0),
        "volume": vol,
        "open_interest": oi,
        "vol_oi_ratio": float(raw.get("volumeOpenInterestRatio", 0) or 0),
        "implied_vol": _parse_pct(raw.get("volatility", "")),
        "delta": float(raw.get("delta", 0) or 0),
    }


class SteadyAPISource:
    """SteadyAPI options data source for institutional flow signals.

    Exposes two main data feeds:
      1. Options flow — large individual trades (sweeps, blocks)
      2. Unusual activity — contracts with volume >> open interest
    """

    SOURCE_NAME = "steadyapi"

    def __init__(self) -> None:
        self._api_key = settings.steadyapi_api_key
        self._client: httpx.Client | None = None

    @property
    def _http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=BASE_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=15.0,
            )
        return self._client

    def _enabled(self) -> bool:
        return bool(self._api_key) and settings.enable_steadyapi

    def _get(self, path: str, params: dict | None = None) -> dict:
        """Rate-limited GET returning parsed JSON body."""
        resp = rate_limiter.request_with_retry(
            self.SOURCE_NAME,
            self._http,
            "GET",
            path,
            params=params,
        )
        data = resp.json()
        return data

    # ── Public API ──────────────────────────────────────────────

    def get_options_flow(
        self,
        asset_class: str = "STOCKS",
        max_pages: int = 3,
        min_premium: float = 100_000,
    ) -> list[dict]:
        """Fetch large options transactions, filtered for institutional signals.

        Args:
            asset_class: "STOCKS", "ETFS", or "INDICES".
            max_pages: How many pages to fetch (20 records per page).
            min_premium: Minimum premium in dollars to include.

        Returns:
            List of normalized flow records sorted by premium descending.
        """
        if not self._enabled():
            logger.debug("SteadyAPI disabled or no API key, skipping options flow")
            return []

        all_records: list[dict] = []
        try:
            for page in range(1, max_pages + 1):
                data = self._get("/options-flow", params={"type": asset_class, "page": str(page)})
                body = data.get("body", [])
                if not body:
                    break

                for raw in body:
                    rec = _normalize_flow_record(raw)
                    if rec["premium"] >= min_premium:
                        all_records.append(rec)

                total_pages = int(data.get("meta", {}).get("total", 0)) // 20 + 1
                if page >= total_pages:
                    break

        except httpx.HTTPStatusError as exc:
            logger.error("SteadyAPI options-flow HTTP error: %s", exc)
        except Exception:
            logger.exception("SteadyAPI options-flow unexpected error")

        all_records.sort(key=lambda r: r["premium"], reverse=True)
        logger.info("SteadyAPI: fetched %d flow records (>=$%.0fK premium)", len(all_records), min_premium / 1000)
        return all_records

    def get_unusual_options_activity(
        self,
        asset_class: str = "STOCKS",
        max_pages: int = 3,
        min_vol_oi_ratio: float = 3.0,
    ) -> list[dict]:
        """Fetch options with unusually high volume relative to open interest.

        Args:
            asset_class: "STOCKS", "ETFS", or "INDICES".
            max_pages: How many pages to fetch.
            min_vol_oi_ratio: Minimum volume/OI ratio threshold.

        Returns:
            List of normalized unusual activity records sorted by vol/OI descending.
        """
        if not self._enabled():
            logger.debug("SteadyAPI disabled or no API key, skipping unusual activity")
            return []

        all_records: list[dict] = []
        try:
            for page in range(1, max_pages + 1):
                data = self._get(
                    "/unusual-options-activity",
                    params={"type": asset_class, "page": str(page)},
                )
                body = data.get("body", [])
                if not body:
                    break

                for raw in body:
                    rec = _normalize_unusual_record(raw)
                    if rec["vol_oi_ratio"] >= min_vol_oi_ratio:
                        all_records.append(rec)

                total_pages = int(data.get("meta", {}).get("total", 0)) // 20 + 1
                if page >= total_pages:
                    break

        except httpx.HTTPStatusError as exc:
            logger.error("SteadyAPI unusual-activity HTTP error: %s", exc)
        except Exception:
            logger.exception("SteadyAPI unusual-activity unexpected error")

        all_records.sort(key=lambda r: r["vol_oi_ratio"], reverse=True)
        logger.info("SteadyAPI: fetched %d unusual activity records (vol/OI >= %.1f)", len(all_records), min_vol_oi_ratio)
        return all_records

    def get_flow_for_ticker(
        self,
        ticker: str,
        min_premium: float = 50_000,
        max_pages: int = 5,
    ) -> list[dict]:
        """Get options flow filtered to a single ticker.

        SteadyAPI doesn't support per-ticker filtering server-side, so we fetch
        broad flow and filter client-side. Cached at the DataFetcher layer.
        """
        if not self._enabled():
            return []

        all_flow = self.get_options_flow(max_pages=max_pages, min_premium=min_premium)
        ticker_upper = ticker.upper()
        return [r for r in all_flow if r["symbol"] == ticker_upper]

    def get_institutional_sweeps(
        self,
        min_premium: float = 100_000,
        max_pages: int = 5,
    ) -> list[dict]:
        """Get only sweep orders — the strongest institutional signal.

        Sweeps hit multiple exchanges simultaneously, indicating urgency.
        Combined with BuyToOpen label, this is a strong directional bet.
        """
        if not self._enabled():
            return []

        flow = self.get_options_flow(max_pages=max_pages, min_premium=min_premium)
        return [r for r in flow if r["is_sweep"]]

    def get_flow_summary(self, max_pages: int = 5) -> dict:
        """Aggregate flow into a market-level sentiment summary.

        Returns dict with:
          - total_call_premium, total_put_premium
          - call_put_premium_ratio
          - top_tickers: list of (ticker, net_premium) sorted by absolute flow
          - sweep_count, block_count
        """
        if not self._enabled():
            return {}

        flow = self.get_options_flow(max_pages=max_pages, min_premium=0)
        if not flow:
            return {}

        total_call = sum(r["premium"] for r in flow if r["option_type"] == "Call")
        total_put = sum(r["premium"] for r in flow if r["option_type"] == "Put")

        ticker_net: dict[str, float] = {}
        for r in flow:
            sign = 1.0 if r["option_type"] == "Call" else -1.0
            ticker_net[r["symbol"]] = ticker_net.get(r["symbol"], 0.0) + sign * r["premium"]

        top = sorted(ticker_net.items(), key=lambda x: abs(x[1]), reverse=True)[:20]

        return {
            "total_call_premium": total_call,
            "total_put_premium": total_put,
            "call_put_premium_ratio": round(total_call / total_put, 2) if total_put > 0 else float("inf"),
            "top_tickers": [{"ticker": t, "net_premium": round(p, 0)} for t, p in top],
            "sweep_count": sum(1 for r in flow if r["is_sweep"]),
            "block_count": sum(1 for r in flow if r["is_block"]),
            "total_records": len(flow),
        }


steadyapi_source = SteadyAPISource()
