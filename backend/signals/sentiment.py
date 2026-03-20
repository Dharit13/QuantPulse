"""News sentiment pipeline — FinBERT + VADER scoring for catalyst signals.

Fetches recent news for a ticker (via yfinance or Finnhub when available),
scores each headline/article, and produces an aggregate sentiment signal.

The output feeds into CatalystEventStrategy as an additional conviction factor.

Reference: QUANTPULSE_FINAL_SPEC.md §5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from nlp.finbert_sentiment import get_analyzer

logger = logging.getLogger(__name__)

MIN_ARTICLES = 3
STRONG_POSITIVE_THRESHOLD = 0.6
STRONG_NEGATIVE_THRESHOLD = -0.3


@dataclass
class NewsSentiment:
    ticker: str
    article_count: int
    avg_compound: float
    pct_positive: float
    pct_negative: float
    pct_neutral: float
    strongest_positive: str
    strongest_negative: str
    sentiment_label: str  # "bullish", "bearish", "neutral"
    composite_score: float  # 0-100 for integration with signal scoring
    analyzed_at: datetime


def analyze_ticker_sentiment(
    ticker: str,
    use_finbert: bool = True,
) -> NewsSentiment:
    """Fetch news for a ticker and produce aggregate sentiment."""
    headlines = _fetch_news_headlines(ticker)

    if len(headlines) < MIN_ARTICLES:
        return NewsSentiment(
            ticker=ticker,
            article_count=len(headlines),
            avg_compound=0.0,
            pct_positive=0.0,
            pct_negative=0.0,
            pct_neutral=1.0,
            strongest_positive="",
            strongest_negative="",
            sentiment_label="neutral",
            composite_score=50.0,
            analyzed_at=datetime.now(timezone.utc),
        )

    analyzer = get_analyzer(use_finbert=use_finbert)
    results = analyzer.analyze_batch(headlines)

    positives = [r for r in results if r.label == "positive"]
    negatives = [r for r in results if r.label == "negative"]
    neutrals = [r for r in results if r.label == "neutral"]

    n = len(results)
    avg_compound = sum(r.compound for r in results) / n

    pct_pos = len(positives) / n
    pct_neg = len(negatives) / n
    pct_neu = len(neutrals) / n

    best_pos = max(results, key=lambda r: r.compound)
    best_neg = min(results, key=lambda r: r.compound)

    if avg_compound >= STRONG_POSITIVE_THRESHOLD:
        label = "bullish"
    elif avg_compound <= STRONG_NEGATIVE_THRESHOLD:
        label = "bearish"
    else:
        label = "neutral"

    composite = 50.0 + avg_compound * 50.0
    composite = max(0.0, min(100.0, composite))

    return NewsSentiment(
        ticker=ticker,
        article_count=n,
        avg_compound=round(avg_compound, 4),
        pct_positive=round(pct_pos, 4),
        pct_negative=round(pct_neg, 4),
        pct_neutral=round(pct_neu, 4),
        strongest_positive=best_pos.text,
        strongest_negative=best_neg.text,
        sentiment_label=label,
        composite_score=round(composite, 2),
        analyzed_at=datetime.now(timezone.utc),
    )


def scan_universe_sentiment(
    tickers: list[str],
    use_finbert: bool = True,
    min_score: float = 70.0,
) -> list[NewsSentiment]:
    """Scan a list of tickers and return those with strong sentiment signals."""
    results = []
    for ticker in tickers:
        try:
            sentiment = analyze_ticker_sentiment(ticker, use_finbert=use_finbert)
            if sentiment.composite_score >= min_score or sentiment.composite_score <= (100 - min_score):
                results.append(sentiment)
        except Exception as e:
            logger.debug("Sentiment scan failed for %s: %s", ticker, e)
    results.sort(key=lambda s: abs(s.avg_compound), reverse=True)
    return results


def _fetch_news_headlines(ticker: str) -> list[str]:
    """Fetch recent news headlines for a ticker.

    Primary: Finnhub news (when API key set).
    Fallback: yfinance ticker.news attribute.
    """
    headlines: list[str] = []

    try:
        from backend.data.fetcher import data_fetcher

        news = data_fetcher.get_news_sentiment(ticker)
        for item in news[:20]:
            title = item.get("headline", "") or item.get("title", "")
            if title and title not in headlines:
                headlines.append(title)
    except Exception as e:
        logger.debug("Finnhub news fetch failed for %s: %s", ticker, e)

    if len(headlines) < MIN_ARTICLES:
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            for item in (t.news or [])[:20]:
                title = item.get("title", "")
                if not title:
                    content = item.get("content", {})
                    if isinstance(content, dict):
                        title = content.get("title", "")
                if title and title not in headlines:
                    headlines.append(title)
        except Exception as e:
            logger.debug("yfinance news fallback failed for %s: %s", ticker, e)

    return headlines
