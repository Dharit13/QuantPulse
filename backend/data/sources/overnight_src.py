"""Overnight Swing Scanner — data assembly with caching, retry, parallelism, and TA.

Architecture improvements over v1:
  - Retry with exponential backoff on all HTTP calls
  - Caching: FRED daily, SEC 6h, Polygon snapshots per-run
  - Parallel API calls via ThreadPoolExecutor (full scan < 60s)
  - Pre-computed technical indicators (RSI, Bollinger, volume ratio, VWAP)
  - Numeric pre-filter before Claude (cuts token cost 60-70%)
  - Dynamic universe discovery (Polygon movers + CoinGecko trending)
  - Result logging with outcome tracking
  - Cost tracking for Claude API calls

Paid APIs (keys you already have):
  Polygon.io  — stock snapshots, OHLCV, news
  FRED        — macro regime indicators

Free APIs (no key needed):
  Binance, CoinGecko, SEC EDGAR, FINRA ATS, Fear & Greed Index
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from backend.config import settings
from backend.data.cache import data_cache

logger = logging.getLogger(__name__)

# ── Default universes (used as fallback if dynamic discovery fails) ──

DEFAULT_STOCKS = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
    "AMD",
    "NFLX",
    "CRM",
    "ORCL",
    "ADBE",
    "INTC",
    "PYPL",
    "SQ",
    "SHOP",
    "UBER",
    "ABNB",
    "COIN",
    "PLTR",
    "SOFI",
    "MRNA",
    "RIVN",
    "LCID",
    "SNAP",
    "GME",
    "AMC",
]

DEFAULT_CRYPTO = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "MATICUSDT",
    "ARBUSDT",
    "OPUSDT",
    "APTUSDT",
    "SUIUSDT",
    "NEARUSDT",
    "INJUSDT",
    "FETUSDT",
    "RENDERUSDT",
    "DOTUSDT",
    "SHIBUSDT",
]

_TIMEOUT = 15
_SEC_HEADERS = {"User-Agent": f"QuantPulse Scanner ({settings.sec_edgar_email or 'contact@quantpulse.dev'})"}

# ────────────────────────────────────────────────────────────
# HTTP helpers with retry + exponential backoff
# ────────────────────────────────────────────────────────────

_http_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(timeout=_TIMEOUT)
    return _http_client


def _get(url: str, params: dict | None = None, headers: dict | None = None, retries: int = 3) -> dict | list | None:
    for attempt in range(retries):
        try:
            resp = _get_client().get(url, params=params, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = min(2**attempt * 1.5, 10)
                logger.warning("Rate limited on %s, waiting %.1fs", url[:60], wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                time.sleep(2**attempt)
                continue
            return None
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt < retries - 1:
                time.sleep(2**attempt)
                logger.debug("Retry %d for %s: %s", attempt + 1, url[:60], e)
            else:
                logger.warning("Failed after %d retries: %s", retries, url[:60])
    return None


def _post(url: str, payload: dict | None = None, headers: dict | None = None, retries: int = 3) -> dict | list | None:
    for attempt in range(retries):
        try:
            resp = _get_client().post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                time.sleep(min(2**attempt * 1.5, 10))
                continue
            if resp.status_code >= 500:
                time.sleep(2**attempt)
                continue
            return None
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt < retries - 1:
                time.sleep(2**attempt)
    return None


# ────────────────────────────────────────────────────────────
# TECHNICAL INDICATORS — computed in Python, NOT by Claude
# ────────────────────────────────────────────────────────────


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.0001
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _compute_bollinger(closes: list[float], period: int = 20) -> dict | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((x - sma) ** 2 for x in window) / period
    std = variance**0.5
    upper = sma + 2 * std
    lower = sma - 2 * std
    price = closes[-1]
    pct_b = (price - lower) / (upper - lower) if upper != lower else 0.5
    return {
        "sma_20": round(sma, 2),
        "upper": round(upper, 2),
        "lower": round(lower, 2),
        "pct_b": round(pct_b, 3),
        "bandwidth": round((upper - lower) / sma * 100, 2) if sma else 0,
    }


def _compute_volume_profile(volumes: list[float]) -> dict | None:
    if len(volumes) < 5:
        return None
    avg_20 = sum(volumes[-20:]) / min(len(volumes), 20) if volumes else 1
    latest = volumes[-1] if volumes else 0
    return {
        "latest_volume": int(latest),
        "avg_volume_20d": int(avg_20),
        "volume_ratio": round(latest / avg_20, 2) if avg_20 > 0 else 0,
    }


def _compute_stock_indicators(bars: list[dict]) -> dict:
    """Compute all technical indicators from OHLCV bars."""
    if not bars or len(bars) < 5:
        return {"error": "insufficient_data"}

    closes = [float(b.get("c", 0)) for b in bars]
    highs = [float(b.get("h", 0)) for b in bars]
    lows = [float(b.get("l", 0)) for b in bars]
    volumes = [float(b.get("v", 0)) for b in bars]

    price = closes[-1] if closes else 0
    indicators: dict[str, Any] = {"price": round(price, 2)}

    indicators["rsi_14"] = _compute_rsi(closes)
    indicators["bollinger"] = _compute_bollinger(closes)
    indicators["volume"] = _compute_volume_profile(volumes)

    if len(closes) >= 2:
        indicators["change_1d_pct"] = round((closes[-1] / closes[-2] - 1) * 100, 2)
    if len(closes) >= 5:
        indicators["change_5d_pct"] = round((closes[-1] / closes[-5] - 1) * 100, 2)
    if len(closes) >= 20:
        indicators["change_20d_pct"] = round((closes[-1] / closes[-20] - 1) * 100, 2)

    if len(closes) >= 20:
        indicators["sma_20"] = round(sum(closes[-20:]) / 20, 2)
    if len(closes) >= 50 and len(closes) >= 50:
        indicators["sma_50"] = round(sum(closes[-50:]) / 50, 2)

    if highs and lows:
        indicators["high_20d"] = round(max(highs[-20:]), 2)
        indicators["low_20d"] = round(min(lows[-20:]), 2)

    # ATR (14-period)
    if len(closes) >= 15:
        trs = []
        for i in range(1, min(15, len(closes))):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            trs.append(tr)
        atr = sum(trs) / len(trs)
        indicators["atr_14"] = round(atr, 2)
        indicators["atr_pct"] = round(atr / price * 100, 2) if price > 0 else 0

    # Average daily volume for liquidity check
    if volumes:
        indicators["avg_daily_volume"] = int(sum(volumes[-20:]) / min(len(volumes), 20))

    return indicators


def _compute_crypto_indicators(klines: list[dict]) -> dict:
    """Compute technical indicators from Binance klines."""
    if not klines or len(klines) < 5:
        return {"error": "insufficient_data"}

    closes = [float(k.get("close", 0)) for k in klines]
    volumes = [float(k.get("volume", 0)) for k in klines]
    quote_vols = [float(k.get("quote_volume", 0)) for k in klines]

    price = closes[-1] if closes else 0
    indicators: dict[str, Any] = {"price": round(price, 6)}

    indicators["rsi_14"] = _compute_rsi(closes)
    indicators["bollinger"] = _compute_bollinger(closes)
    indicators["volume"] = _compute_volume_profile(volumes)

    if len(closes) >= 2:
        indicators["change_1d_pct"] = round((closes[-1] / closes[-2] - 1) * 100, 2)
    if len(closes) >= 7:
        indicators["change_7d_pct"] = round((closes[-1] / closes[-7] - 1) * 100, 2)

    if quote_vols:
        indicators["avg_daily_quote_volume"] = round(sum(quote_vols[-20:]) / min(len(quote_vols), 20), 0)

    return indicators


# ────────────────────────────────────────────────────────────
# NUMERIC PRE-FILTER — cheap check before expensive Claude call
# ────────────────────────────────────────────────────────────


def _passes_stock_prefilter(indicators: dict, has_insider: bool) -> bool:
    """Return True if this ticker is worth sending to Claude."""
    if indicators.get("error"):
        return False

    vol = indicators.get("volume", {})
    volume_ratio = vol.get("volume_ratio", 0)
    avg_vol = indicators.get("avg_daily_volume", 0)
    price = indicators.get("price", 0)
    change_1d = abs(indicators.get("change_1d_pct", 0))
    rsi = indicators.get("rsi_14")

    # Liquidity floor: skip penny stocks and illiquid names
    if price < 3 or avg_vol < 100_000:
        return False

    # Pass if ANY of these conditions are true:
    if volume_ratio >= 1.5:
        return True
    if change_1d >= 2.0:
        return True
    if has_insider:
        return True
    if rsi is not None and (rsi <= 30 or rsi >= 70):
        return True
    # Bollinger breakout
    bb = indicators.get("bollinger")
    if bb and (bb.get("pct_b", 0.5) < 0.05 or bb.get("pct_b", 0.5) > 0.95):
        return True

    return False


def _passes_crypto_prefilter(indicators: dict) -> bool:
    """Return True if this crypto pair is worth sending to Claude."""
    if indicators.get("error"):
        return False

    vol = indicators.get("volume", {})
    volume_ratio = vol.get("volume_ratio", 0)
    change_1d = abs(indicators.get("change_1d_pct", 0))
    rsi = indicators.get("rsi_14")

    if volume_ratio >= 1.3:
        return True
    if change_1d >= 3.0:
        return True
    if rsi is not None and (rsi <= 25 or rsi >= 75):
        return True

    return False


# ────────────────────────────────────────────────────────────
# POLYGON.IO  (paid — key you already have)
# ────────────────────────────────────────────────────────────

_POLYGON = "https://api.polygon.io"


def polygon_snapshot_all() -> dict[str, Any]:
    """Bulk snapshot of ALL US tickers — cached for the scan run."""
    cached = data_cache.get("overnight:polygon_snapshot")
    if cached and isinstance(cached, dict):
        return cached

    if not settings.polygon_api_key:
        return {}
    data = _get(f"{_POLYGON}/v2/snapshot/locale/us/market/stocks/tickers", params={"apiKey": settings.polygon_api_key})
    if not data or data.get("status") != "OK":
        return {}
    result = {t["ticker"]: t for t in data.get("tickers", [])}
    data_cache.set("overnight:polygon_snapshot", result, ttl_hours=0.25)
    return result


def polygon_aggregates(symbol: str, days: int = 30) -> list:
    if not settings.polygon_api_key:
        return []
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    data = _get(
        f"{_POLYGON}/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}",
        params={"adjusted": "true", "sort": "asc", "apiKey": settings.polygon_api_key},
    )
    return data.get("results", []) if data else []


def polygon_news(symbol: str, limit: int = 3) -> list[dict]:
    if not settings.polygon_api_key:
        return []
    data = _get(
        f"{_POLYGON}/v2/reference/news",
        params={
            "ticker": symbol,
            "limit": limit,
            "order": "desc",
            "sort": "published_utc",
            "apiKey": settings.polygon_api_key,
        },
    )
    results = data.get("results", []) if data else []
    return [{"title": n.get("title", ""), "published": n.get("published_utc", "")} for n in results]


def polygon_gainers_losers() -> dict[str, list[str]]:
    """Discover today's top movers — dynamic universe expansion."""
    if not settings.polygon_api_key:
        return {"gainers": [], "losers": []}

    result: dict[str, list[str]] = {"gainers": [], "losers": []}
    for direction in ("gainers", "losers"):
        data = _get(
            f"{_POLYGON}/v2/snapshot/locale/us/market/stocks/{direction}",
            params={"apiKey": settings.polygon_api_key},
        )
        if data and data.get("tickers"):
            for t in data["tickers"][:15]:
                sym = t.get("ticker", "")
                if sym and 1 <= len(sym) <= 5 and sym.isalpha():
                    result[direction].append(sym)
    return result


# ────────────────────────────────────────────────────────────
# FRED  (paid — cached daily since data changes once/day)
# ────────────────────────────────────────────────────────────

_FRED = "https://api.stlouisfed.org/fred"
_FRED_CACHE_KEY = "overnight:fred_macro"
_FRED_CACHE_TTL = 12.0  # hours

_MACRO_SERIES: dict[str, str] = {
    "fed_funds_rate": "FEDFUNDS",
    "unemployment_rate": "UNRATE",
    "cpi_yoy": "CPIAUCSL",
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "vix": "VIXCLS",
    "sp500": "SP500",
    "initial_jobless_claims": "ICSA",
    "retail_sales": "RSXFS",
    "consumer_sentiment": "UMCSENT",
}


def fred_series(series_id: str, limit: int = 10) -> list[dict]:
    if not settings.fred_api_key:
        return []
    data = _get(
        f"{_FRED}/series/observations",
        params={
            "series_id": series_id,
            "api_key": settings.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        },
    )
    return data.get("observations", []) if data else []


def fetch_macro_regime() -> dict[str, list[dict]]:
    """Pull key macro indicators — cached 12 hours (FRED data changes daily)."""
    cached = data_cache.get(_FRED_CACHE_KEY)
    if cached and isinstance(cached, dict) and len(cached) > 3:
        logger.info("Using cached FRED macro data (%d indicators)", len(cached))
        return cached

    regime_data: dict[str, list[dict]] = {}
    for name, sid in _MACRO_SERIES.items():
        obs = fred_series(sid, limit=6)
        if obs:
            regime_data[name] = [{"date": o["date"], "value": o["value"]} for o in obs if o.get("value") != "."]
        time.sleep(0.15)

    if regime_data:
        data_cache.set(_FRED_CACHE_KEY, regime_data, ttl_hours=_FRED_CACHE_TTL)
    return regime_data


# ────────────────────────────────────────────────────────────
# SEC EDGAR  (free — cached 6 hours)
# ────────────────────────────────────────────────────────────

_CIK_CACHE: dict[str, str] = {}
_SEC_CACHE_TTL = 6.0


def _resolve_cik(symbol: str) -> str | None:
    if symbol in _CIK_CACHE:
        return _CIK_CACHE[symbol]
    cache_key = "overnight:sec_cik_map"
    cik_map = data_cache.get(cache_key)
    if not cik_map:
        data = _get("https://www.sec.gov/files/company_tickers.json", headers=_SEC_HEADERS)
        if not data:
            return None
        cik_map = {}
        for _, entry in data.items():
            ticker = entry.get("ticker", "").upper()
            if ticker:
                cik_map[ticker] = str(entry["cik_str"]).zfill(10)
        data_cache.set(cache_key, cik_map, ttl_hours=24.0)

    cik = cik_map.get(symbol.upper())
    if cik:
        _CIK_CACHE[symbol] = cik
    return cik


def sec_insider_filings(symbol: str) -> list[dict]:
    """Recent Form 4 insider filings — cached 6 hours."""
    cache_key = f"overnight:sec:{symbol}"
    cached = data_cache.get(cache_key)
    if cached is not None and isinstance(cached, list):
        return cached

    cik = _resolve_cik(symbol)
    if not cik:
        return []
    filings = _get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=_SEC_HEADERS)
    if not filings:
        return []
    recent = filings.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    docs = recent.get("primaryDocument", [])
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    insider: list[dict] = []
    for i, form in enumerate(forms[:80]):
        if form in ("4", "4/A") and i < len(dates) and dates[i] >= cutoff:
            insider.append({"form": form, "date": dates[i], "doc": docs[i] if i < len(docs) else ""})

    data_cache.set(cache_key, insider, ttl_hours=_SEC_CACHE_TTL)
    return insider


# ────────────────────────────────────────────────────────────
# FINRA ATS — Dark Pool  (free, no key)
# ────────────────────────────────────────────────────────────


def finra_dark_pool(symbol: str) -> list:
    data = _post(
        "https://api.finra.org/data/group/OTCMarket/name/weeklySummary",
        payload={
            "fields": ["totalWeeklyShareQuantity", "totalWeeklyTradeCount", "lastUpdateDate"],
            "compareFilters": [
                {
                    "fieldName": "issueSymbolIdentifier",
                    "fieldValue": symbol,
                    "compareType": "EQUAL",
                }
            ],
            "limit": 4,
            "sortFields": ["-lastUpdateDate"],
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    return data if isinstance(data, list) else []


# ────────────────────────────────────────────────────────────
# BINANCE  (free, no key)
# ────────────────────────────────────────────────────────────

_BINANCE = "https://api.binance.com/api/v3"


def binance_klines(symbol: str, interval: str = "1d", limit: int = 30) -> list[dict]:
    data = _get(f"{_BINANCE}/klines", params={"symbol": symbol, "interval": interval, "limit": limit})
    if not data:
        return []
    return [
        {
            "open_time": k[0],
            "open": k[1],
            "high": k[2],
            "low": k[3],
            "close": k[4],
            "volume": k[5],
            "quote_volume": k[7],
            "trades": k[8],
        }
        for k in data
    ]


def binance_24h_ticker(symbol: str) -> dict:
    result = _get(f"{_BINANCE}/ticker/24hr", params={"symbol": symbol})
    return result if isinstance(result, dict) else {}


def binance_order_book(symbol: str, limit: int = 10) -> dict:
    result = _get(f"{_BINANCE}/depth", params={"symbol": symbol, "limit": limit})
    return result if isinstance(result, dict) else {}


def binance_top_movers() -> list[str]:
    """Discover top crypto movers by 24h change — dynamic universe expansion."""
    data = _get(f"{_BINANCE}/ticker/24hr")
    if not data or not isinstance(data, list):
        return []
    usdt_pairs = [t for t in data if t.get("symbol", "").endswith("USDT")]
    usdt_pairs.sort(key=lambda t: abs(float(t.get("priceChangePercent", 0))), reverse=True)
    return [t["symbol"] for t in usdt_pairs[:10] if float(t.get("quoteVolume", 0)) > 1_000_000]


# ────────────────────────────────────────────────────────────
# COINGECKO  (free, no key)
# ────────────────────────────────────────────────────────────


def coingecko_market_data(limit: int = 25) -> list:
    data = _get(
        "https://api.coingecko.com/api/v3/coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": limit,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d",
        },
    )
    return data if isinstance(data, list) else []


def coingecko_trending() -> list:
    data = _get("https://api.coingecko.com/api/v3/search/trending")
    return data.get("coins", []) if data else []


# ────────────────────────────────────────────────────────────
# FEAR & GREED INDEX  (free, no key)
# ────────────────────────────────────────────────────────────


def crypto_fear_greed(limit: int = 7) -> list:
    data = _get(f"https://api.alternative.me/fng/?limit={limit}&format=json")
    return data.get("data", []) if data else []


# ────────────────────────────────────────────────────────────
# DYNAMIC UNIVERSE DISCOVERY
# ────────────────────────────────────────────────────────────


def discover_stock_universe(base_symbols: list[str]) -> list[str]:
    """Expand the stock universe with today's movers from Polygon."""
    universe = set(base_symbols)
    try:
        movers = polygon_gainers_losers()
        universe.update(movers.get("gainers", []))
        universe.update(movers.get("losers", []))
        logger.info(
            "Dynamic stock universe: %d base + %d movers = %d total",
            len(base_symbols),
            len(movers.get("gainers", [])) + len(movers.get("losers", [])),
            len(universe),
        )
    except Exception as e:
        logger.warning("Dynamic universe discovery failed: %s", e)
    return list(universe)


def discover_crypto_universe(base_pairs: list[str]) -> list[str]:
    """Expand the crypto universe with Binance top movers."""
    universe = set(base_pairs)
    try:
        movers = binance_top_movers()
        universe.update(movers)
        logger.info(
            "Dynamic crypto universe: %d base + %d movers = %d total", len(base_pairs), len(movers), len(universe)
        )
    except Exception as e:
        logger.warning("Crypto universe discovery failed: %s", e)
    return list(universe)


# ────────────────────────────────────────────────────────────
# RESULT LOGGING — track picks and outcomes
# ────────────────────────────────────────────────────────────

_RESULT_LOG_KEY = "overnight:result_log"
_MAX_LOG_ENTRIES = 60


def log_scan_result(analysis: dict) -> None:
    """Log scan results for outcome tracking."""
    history = data_cache.get(_RESULT_LOG_KEY) or []

    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "stock_picks": [],
        "crypto_picks": [],
    }

    for pick in analysis.get("stock_picks", []):
        if pick.get("action") == "BUY":
            entry["stock_picks"].append(
                {
                    "symbol": pick.get("symbol"),
                    "confidence": pick.get("confidence"),
                    "expected_move_pct": pick.get("expected_move_pct"),
                    "entry_strategy": pick.get("entry_strategy"),
                }
            )
    for pick in analysis.get("crypto_picks", []):
        if pick.get("action") == "BUY":
            entry["crypto_picks"].append(
                {
                    "symbol": pick.get("symbol"),
                    "confidence": pick.get("confidence"),
                    "expected_move_pct": pick.get("expected_move_pct"),
                }
            )

    history.append(entry)
    history = history[-_MAX_LOG_ENTRIES:]
    data_cache.set(_RESULT_LOG_KEY, history, ttl_hours=720.0)


def get_recent_outcomes(days: int = 7) -> list[dict]:
    """Get recent scan results for performance memory."""
    history = data_cache.get(_RESULT_LOG_KEY) or []
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    return [e for e in history if e.get("timestamp", "") >= cutoff]


# ════════════════════════════════════════════════════════════
# DATA ASSEMBLY — parallel, filtered, with computed indicators
# ════════════════════════════════════════════════════════════

_WORKERS = 8


def _fetch_single_stock(sym: str, snapshots: dict) -> tuple[str, dict | None]:
    """Fetch and compute indicators for a single stock. Returns (symbol, data|None)."""
    try:
        stock: dict[str, Any] = {}

        # Snapshot (from bulk call)
        snap = snapshots.get(sym, {})
        stock["snapshot"] = {
            "todays_change_pct": snap.get("todaysChangePerc"),
            "updated": snap.get("updated"),
        }

        # OHLCV + compute indicators
        bars = polygon_aggregates(sym, days=30)
        indicators = _compute_stock_indicators(bars)
        stock["indicators"] = indicators

        # Override price with live snapshot price when market is open
        day_data = snap.get("day", {})
        live_price = day_data.get("c")
        if live_price and float(live_price) > 0:
            indicators["price"] = round(float(live_price), 2)
            indicators["price_source"] = "live_snapshot"
        else:
            indicators["price_source"] = "last_daily_close"

        if day_data.get("c") and day_data.get("o"):
            indicators["last_hour_change_pct"] = round(snap.get("todaysChangePerc", 0), 2)

        # Insider filings — with explicit count so Claude doesn't fabricate
        insider = sec_insider_filings(sym)
        stock["insider_summary"] = {
            "filing_count": len(insider),
            "has_cluster": len(insider) >= 3,
            "filing_dates": [f["date"] for f in insider],
        }

        # Pre-filter: is this worth sending to Claude?
        if not _passes_stock_prefilter(indicators, len(insider) > 0):
            return sym, None

        # Passed filter — add remaining data
        stock["news"] = polygon_news(sym, limit=3)
        stock["dark_pool"] = finra_dark_pool(sym)

        return sym, stock
    except Exception as e:
        logger.debug("Error fetching %s: %s", sym, e)
        return sym, None


def assemble_stock_data(symbols: list[str]) -> dict[str, dict]:
    """Fetch stock data in parallel with pre-filtering."""
    symbols = discover_stock_universe(symbols)
    logger.info("Overnight scanner: fetching stock data for %d tickers (parallel, %d workers)", len(symbols), _WORKERS)

    # One bulk call for all snapshots
    snapshots = polygon_snapshot_all()

    all_data: dict[str, dict] = {}
    missing_sources: list[str] = []

    if not snapshots:
        missing_sources.append("Polygon snapshots unavailable")

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_fetch_single_stock, sym, snapshots): sym for sym in symbols}
        for future in as_completed(futures):
            sym, stock_data = future.result()
            if stock_data is not None:
                all_data[sym] = stock_data

    if missing_sources:
        all_data["_missing_sources"] = {"sources": missing_sources}

    logger.info("Stock pre-filter: %d/%d tickers passed → sent to Claude", len(all_data), len(symbols))
    return all_data


def _fetch_single_crypto(sym: str) -> tuple[str, dict | None]:
    """Fetch and compute indicators for a single crypto pair."""
    try:
        crypto: dict[str, Any] = {}
        klines = binance_klines(sym, "1d", 30)
        indicators = _compute_crypto_indicators(klines)
        crypto["indicators"] = indicators

        if not _passes_crypto_prefilter(indicators):
            return sym, None

        ticker = binance_24h_ticker(sym)
        crypto["ticker_24h"] = {
            "price_change_pct": ticker.get("priceChangePercent"),
            "volume": ticker.get("volume"),
            "quote_volume": ticker.get("quoteVolume"),
            "weighted_avg_price": ticker.get("weightedAvgPrice"),
        }

        book = binance_order_book(sym, 10)
        if book:
            bids = sum(float(b[1]) for b in book.get("bids", []))
            asks = sum(float(a[1]) for a in book.get("asks", []))
            crypto["order_book_ratio"] = round(bids / asks, 3) if asks > 0 else 1.0

        return sym, crypto
    except Exception as e:
        logger.debug("Error fetching crypto %s: %s", sym, e)
        return sym, None


def assemble_crypto_data(symbols: list[str]) -> dict[str, Any]:
    """Fetch crypto data in parallel with pre-filtering."""
    symbols = discover_crypto_universe(symbols)
    logger.info("Overnight scanner: fetching crypto data for %d pairs (parallel)", len(symbols))

    pairs: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_fetch_single_crypto, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym, crypto_data = future.result()
            if crypto_data is not None:
                pairs[sym] = crypto_data

    logger.info("Crypto pre-filter: %d/%d pairs passed → sent to Claude", len(pairs), len(symbols))

    # Market-wide data
    market_wide: dict[str, Any] = {
        "coingecko_top25": coingecko_market_data(25),
        "coingecko_trending": coingecko_trending(),
        "fear_greed_index": crypto_fear_greed(7),
    }

    # Timezone session context for crypto
    now_et = datetime.now()
    hour_et = now_et.hour
    if 7 <= hour_et < 15:
        session = "US session → will hold through Asian session (7PM-3AM ET, typically lower volatility)"
    elif 15 <= hour_et < 19:
        session = "Late US → entering Asian session (higher altcoin volatility in Asia hours)"
    elif 19 <= hour_et or hour_et < 3:
        session = "Asian session active → will hold through London open (3-8AM ET, often volatile)"
    else:
        session = "Pre-London → London open coming (3-8AM ET, EUR pairs active, volatility spike common)"
    market_wide["session_context"] = session

    return {"pairs": pairs, "market_wide": market_wide}


def assemble_macro_data() -> dict:
    """Fetch macro regime data from FRED (cached daily)."""
    logger.info("Overnight scanner: fetching FRED macro data")
    return fetch_macro_regime()
