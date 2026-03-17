import logging

import pandas as pd

from backend.data.cache import data_cache

logger = logging.getLogger(__name__)

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CACHE_KEY = "sp500_constituents"
CACHE_TTL_HOURS = 168  # 1 week


def fetch_sp500_constituents() -> pd.DataFrame:
    """Fetch S&P 500 constituents from Wikipedia with sector/industry mapping."""
    cached = data_cache.get(CACHE_KEY)
    if cached is not None and isinstance(cached, pd.DataFrame) and not cached.empty:
        logger.info("Using cached S&P 500 constituents (%d stocks)", len(cached))
        return cached

    try:
        tables = pd.read_html(SP500_WIKI_URL, header=0)
        df = tables[0]
        df = df.rename(columns={
            "Symbol": "ticker",
            "Security": "name",
            "GICS Sector": "sector",
            "GICS Sub-Industry": "sub_industry",
            "Headquarters Location": "hq",
            "Date added": "date_added",
            "CIK": "cik",
            "Founded": "founded",
        })
        df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)
        df = df[["ticker", "name", "sector", "sub_industry"]].copy()
        data_cache.set(CACHE_KEY, df, ttl_hours=CACHE_TTL_HOURS)
        logger.info("Fetched %d S&P 500 constituents", len(df))
        return df
    except Exception:
        logger.exception("Failed to fetch S&P 500 constituents")
        return pd.DataFrame(columns=["ticker", "name", "sector", "sub_industry"])


def get_tickers_by_sector(sector: str) -> list[str]:
    df = fetch_sp500_constituents()
    return df[df["sector"] == sector]["ticker"].tolist()


def get_tickers_by_sub_industry(sub_industry: str) -> list[str]:
    df = fetch_sp500_constituents()
    return df[df["sub_industry"] == sub_industry]["ticker"].tolist()


def get_sector_groups() -> dict[str, list[str]]:
    """Return {sector: [tickers]} mapping."""
    df = fetch_sp500_constituents()
    return df.groupby("sector")["ticker"].apply(list).to_dict()


def get_sub_industry_groups() -> dict[str, list[str]]:
    """Return {sub_industry: [tickers]} mapping for pair finding."""
    df = fetch_sp500_constituents()
    groups = df.groupby("sub_industry")["ticker"].apply(list).to_dict()
    return {k: v for k, v in groups.items() if len(v) >= 2}


def get_all_tickers() -> list[str]:
    df = fetch_sp500_constituents()
    return df["ticker"].tolist()
