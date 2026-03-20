"""Finnhub data source.

Enable by setting FINNHUB_API_KEY in .env.
Provides: analyst recommendation trends, upgrade/downgrade history,
          company news (for sentiment), earnings surprises.

Finnhub free tier: 60 API calls/min. Rate limiter registered as "finnhub" at 1 req/s.
Docs: https://finnhub.io/docs/api
"""

import logging
from datetime import date, datetime, timedelta

import httpx

from backend.config import settings
from backend.data.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubSource:
    """Finnhub data source for analyst data, news, and earnings.

    All methods degrade gracefully (return empty containers) when the API key
    is not configured or the request fails.
    """

    SOURCE_NAME = "finnhub"

    def __init__(self) -> None:
        self._api_key = settings.finnhub_api_key
        self._client: httpx.Client | None = None

    @property
    def _http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=BASE_URL,
                headers={"X-Finnhub-Token": self._api_key},
                timeout=15.0,
            )
        return self._client

    def _enabled(self) -> bool:
        return bool(self._api_key)

    def _get(self, path: str, params: dict | None = None) -> list | dict:
        """Rate-limited GET returning parsed JSON."""
        resp = rate_limiter.request_with_retry(
            self.SOURCE_NAME,
            self._http,
            "GET",
            path,
            params=params,
        )
        return resp.json()

    # ── Public API ──────────────────────────────────────────────

    def get_analyst_revisions(self, ticker: str) -> list[dict]:
        """Analyst revision data for breadth/acceleration signals.

        Tries upgrade/downgrade history first (premium endpoint), then
        falls back to recommendation trends (free) which provides the same
        strong_buy/buy/hold/sell/strong_sell shape that revisions.py needs.
        """
        if not self._enabled():
            return []

        # Try premium upgrade/downgrade endpoint first
        try:
            upgrades = self._get(
                "/stock/upgrade-downgrade",
                params={"symbol": ticker},
            )
            if isinstance(upgrades, list) and upgrades:
                records: list[dict] = []
                for item in upgrades:
                    grade_date_str = item.get("gradeDate", "")
                    try:
                        grade_date = date.fromisoformat(grade_date_str)
                    except (ValueError, TypeError):
                        continue

                    action = item.get("action", "").lower()
                    to_grade = item.get("toGrade", "")

                    is_upgrade = action in ("upgrade", "up")
                    is_downgrade = action in ("downgrade", "down")

                    records.append(
                        {
                            "date": grade_date,
                            "company": item.get("company", ""),
                            "action": action,
                            "from_grade": item.get("fromGrade", ""),
                            "to_grade": to_grade,
                            "is_upgrade": is_upgrade,
                            "is_downgrade": is_downgrade,
                            "strong_buy": 1 if to_grade.lower() in ("strong buy", "outperform") and is_upgrade else 0,
                            "buy": 1 if to_grade.lower() in ("buy", "overweight") else 0,
                            "hold": 1
                            if to_grade.lower() in ("hold", "neutral", "equal-weight", "market perform")
                            else 0,
                            "sell": 1 if to_grade.lower() in ("sell", "underweight") else 0,
                            "strong_sell": 1
                            if to_grade.lower() in ("strong sell", "underperform") and is_downgrade
                            else 0,
                        }
                    )

                records.sort(key=lambda r: r["date"], reverse=True)
                logger.info("Finnhub: fetched %d analyst revisions for %s", len(records), ticker)
                return records[:50]
        except httpx.HTTPStatusError:
            logger.debug("Finnhub upgrade/downgrade is premium, falling back to recommendations for %s", ticker)
        except Exception:
            logger.debug("Finnhub upgrade/downgrade failed for %s, trying recommendations", ticker)

        # Fall back to free recommendation trends (same shape revisions.py needs)
        return self.get_recommendation_trends(ticker)

    def get_recommendation_trends(self, ticker: str) -> list[dict]:
        """Monthly analyst recommendation aggregates.

        Returns list of dicts with: date (period), strong_buy, buy, hold, sell,
        strong_sell — matching the shape yfinance returns so downstream code
        (revisions.py, earnings.py) can use either interchangeably.
        """
        if not self._enabled():
            return []

        try:
            data = self._get(
                "/stock/recommendation",
                params={"symbol": ticker},
            )
            if not isinstance(data, list):
                return []

            records: list[dict] = []
            for item in data:
                period_str = item.get("period", "")
                try:
                    period_date = date.fromisoformat(period_str)
                except (ValueError, TypeError):
                    continue

                records.append(
                    {
                        "date": period_date,
                        "strong_buy": item.get("strongBuy", 0),
                        "buy": item.get("buy", 0),
                        "hold": item.get("hold", 0),
                        "sell": item.get("sell", 0),
                        "strong_sell": item.get("strongSell", 0),
                    }
                )

            records.sort(key=lambda r: r["date"], reverse=True)
            return records[:24]
        except httpx.HTTPStatusError as exc:
            logger.error("Finnhub recommendation trends HTTP error for %s: %s", ticker, exc)
            return []
        except Exception:
            logger.exception("Finnhub recommendation trends failed for %s", ticker)
            return []

    def get_news(self, ticker: str, days_back: int = 7) -> list[dict]:
        """Company news articles for sentiment analysis.

        Returns list of dicts with: headline, summary, source, url, datetime,
        category. Used by sentiment.py for FinBERT/VADER scoring.
        """
        if not self._enabled():
            return []

        try:
            to_date = date.today()
            from_date = to_date - timedelta(days=days_back)

            data = self._get(
                "/company-news",
                params={
                    "symbol": ticker,
                    "from": from_date.isoformat(),
                    "to": to_date.isoformat(),
                },
            )
            if not isinstance(data, list):
                return []

            records: list[dict] = []
            for item in data:
                ts = item.get("datetime", 0)
                try:
                    article_dt = datetime.fromtimestamp(ts) if isinstance(ts, (int, float)) else None
                except (OSError, ValueError):
                    article_dt = None

                records.append(
                    {
                        "headline": item.get("headline", ""),
                        "title": item.get("headline", ""),
                        "summary": item.get("summary", ""),
                        "source": item.get("source", ""),
                        "url": item.get("url", ""),
                        "datetime": article_dt,
                        "category": item.get("category", ""),
                        "related": item.get("related", ticker),
                        "image": item.get("image", ""),
                    }
                )

            records.sort(key=lambda r: r["datetime"] or datetime.min, reverse=True)
            logger.info("Finnhub: fetched %d news articles for %s", len(records), ticker)
            return records
        except httpx.HTTPStatusError as exc:
            logger.error("Finnhub news HTTP error for %s: %s", ticker, exc)
            return []
        except Exception:
            logger.exception("Finnhub news failed for %s", ticker)
            return []

    def get_earnings_surprises(self, ticker: str) -> list[dict]:
        """Historical EPS surprises.

        Returns list of dicts with: date, eps_actual, eps_estimate, surprise_pct.
        Compatible with the earnings.py consumption pattern.
        """
        if not self._enabled():
            return []

        try:
            data = self._get(
                "/stock/earnings",
                params={"symbol": ticker},
            )
            if not isinstance(data, list):
                return []

            records: list[dict] = []
            for item in data:
                actual = item.get("actual")
                estimate = item.get("estimate")
                if actual is None or estimate is None:
                    continue

                period_str = item.get("period", "")
                try:
                    report_date = date.fromisoformat(period_str)
                except (ValueError, TypeError):
                    continue

                surprise_pct = item.get("surprisePercent", 0.0) or (
                    (actual - estimate) / abs(estimate) * 100 if estimate != 0 else 0.0
                )

                records.append(
                    {
                        "date": report_date,
                        "eps_actual": float(actual),
                        "eps_estimate": float(estimate),
                        "surprise_pct": round(float(surprise_pct), 2),
                        "quarter": item.get("quarter"),
                        "year": item.get("year"),
                    }
                )

            records.sort(key=lambda r: r["date"], reverse=True)
            return records[:12]
        except httpx.HTTPStatusError as exc:
            logger.error("Finnhub earnings surprises HTTP error for %s: %s", ticker, exc)
            return []
        except Exception:
            logger.exception("Finnhub earnings surprises failed for %s", ticker)
            return []

    def get_company_profile(self, ticker: str) -> dict:
        """Basic company profile (sector, industry, market cap)."""
        if not self._enabled():
            return {}

        try:
            data = self._get(
                "/stock/profile2",
                params={"symbol": ticker},
            )
            if not isinstance(data, dict):
                return {}

            return {
                "ticker": data.get("ticker", ticker),
                "name": data.get("name", ""),
                "sector": data.get("finnhubIndustry", ""),
                "country": data.get("country", ""),
                "market_cap": data.get("marketCapitalization", 0) * 1_000_000,
                "ipo_date": data.get("ipo", ""),
                "exchange": data.get("exchange", ""),
                "logo": data.get("logo", ""),
                "web_url": data.get("weburl", ""),
            }
        except httpx.HTTPStatusError as exc:
            logger.error("Finnhub profile HTTP error for %s: %s", ticker, exc)
            return {}
        except Exception:
            logger.exception("Finnhub profile failed for %s", ticker)
            return {}


finnhub_source = FinnhubSource()
