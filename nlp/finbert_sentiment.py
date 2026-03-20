"""FinBERT wrapper — local financial sentiment analysis.

Uses ProsusAI/finbert (HuggingFace) for financial-domain sentiment.
Falls back to VADER for general-purpose NLP when FinBERT is unavailable
(e.g., no GPU, model not downloaded).

Reference: QUANTPULSE_FINAL_SPEC.md §5 (catalyst signals)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

FINBERT_MODEL = "ProsusAI/finbert"
MAX_LENGTH = 512


@dataclass
class SentimentResult:
    text: str
    label: str  # "positive", "negative", "neutral"
    positive: float
    negative: float
    neutral: float
    model: str  # "finbert" or "vader"
    compound_raw: float | None = None

    @property
    def compound(self) -> float:
        if self.compound_raw is not None:
            return self.compound_raw
        return self.positive - self.negative


class FinBERTAnalyzer:
    """Financial sentiment analysis using FinBERT with VADER fallback."""

    def __init__(self, use_finbert: bool = True):
        self._pipeline = None
        self._vader = None
        self._use_finbert = use_finbert
        self._model_loaded = False

    def _load_finbert(self) -> bool:
        if self._model_loaded:
            return self._pipeline is not None
        self._model_loaded = True
        if not self._use_finbert:
            return False
        try:
            from transformers import pipeline

            self._pipeline = pipeline(
                "sentiment-analysis",
                model=FINBERT_MODEL,
                truncation=True,
                max_length=MAX_LENGTH,
                top_k=None,
            )
            logger.info("FinBERT model loaded successfully")
            return True
        except Exception as e:
            logger.warning("FinBERT unavailable, using VADER fallback: %s", e)
            return False

    def _load_vader(self) -> None:
        if self._vader is not None:
            return
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

            self._vader = SentimentIntensityAnalyzer()
        except ImportError:
            logger.error("VADER not installed — pip install vaderSentiment")

    def analyze(self, text: str) -> SentimentResult:
        """Analyze a single text. Returns SentimentResult."""
        if self._load_finbert():
            return self._finbert_analyze(text)
        return self._vader_analyze(text)

    def analyze_batch(self, texts: list[str]) -> list[SentimentResult]:
        """Analyze multiple texts efficiently."""
        if self._load_finbert():
            return self._finbert_batch(texts)
        return [self._vader_analyze(t) for t in texts]

    @staticmethod
    def _parse_finbert_scores(raw: list[dict]) -> dict[str, float]:
        """Parse all 3 class probabilities from top_k=None output."""
        scores = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
        for entry in raw:
            scores[entry["label"].lower()] = entry["score"]
        return scores

    def _finbert_analyze(self, text: str) -> SentimentResult:
        raw = self._pipeline(text[:MAX_LENGTH])
        if raw and isinstance(raw[0], list):
            raw = raw[0]
        scores = self._parse_finbert_scores(raw)
        label = max(scores, key=scores.get)
        return SentimentResult(
            text=text[:200],
            label=label,
            positive=scores["positive"],
            negative=scores["negative"],
            neutral=scores["neutral"],
            model="finbert",
        )

    def _finbert_batch(self, texts: list[str]) -> list[SentimentResult]:
        truncated = [t[:MAX_LENGTH] for t in texts]
        results = self._pipeline(truncated)
        out = []
        for text, raw in zip(texts, results):
            scores = self._parse_finbert_scores(raw)
            label = max(scores, key=scores.get)
            out.append(
                SentimentResult(
                    text=text[:200],
                    label=label,
                    positive=scores["positive"],
                    negative=scores["negative"],
                    neutral=scores["neutral"],
                    model="finbert",
                )
            )
        return out

    def _vader_analyze(self, text: str) -> SentimentResult:
        self._load_vader()
        if self._vader is None:
            return SentimentResult(
                text=text[:200],
                label="neutral",
                positive=0.0,
                negative=0.0,
                neutral=1.0,
                model="none",
            )
        scores = self._vader.polarity_scores(text)
        compound = scores["compound"]
        if compound >= 0.05:
            label = "positive"
        elif compound <= -0.05:
            label = "negative"
        else:
            label = "neutral"
        return SentimentResult(
            text=text[:200],
            label=label,
            positive=scores["pos"],
            negative=scores["neg"],
            neutral=scores["neu"],
            model="vader",
            compound_raw=compound,
        )


@lru_cache(maxsize=1)
def get_analyzer(use_finbert: bool = True) -> FinBERTAnalyzer:
    """Singleton accessor for the sentiment analyzer."""
    return FinBERTAnalyzer(use_finbert=use_finbert)
