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
    label: str          # "positive", "negative", "neutral"
    positive: float
    negative: float
    neutral: float
    model: str          # "finbert" or "vader"

    @property
    def compound(self) -> float:
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

    def _finbert_analyze(self, text: str) -> SentimentResult:
        result = self._pipeline(text[:MAX_LENGTH])[0]
        label = result["label"].lower()
        score = result["score"]
        return SentimentResult(
            text=text[:200],
            label=label,
            positive=score if label == "positive" else (1 - score) / 2,
            negative=score if label == "negative" else (1 - score) / 2,
            neutral=score if label == "neutral" else (1 - score) / 2,
            model="finbert",
        )

    def _finbert_batch(self, texts: list[str]) -> list[SentimentResult]:
        truncated = [t[:MAX_LENGTH] for t in texts]
        results = self._pipeline(truncated)
        out = []
        for text, result in zip(texts, results):
            label = result["label"].lower()
            score = result["score"]
            out.append(SentimentResult(
                text=text[:200],
                label=label,
                positive=score if label == "positive" else (1 - score) / 2,
                negative=score if label == "negative" else (1 - score) / 2,
                neutral=score if label == "neutral" else (1 - score) / 2,
                model="finbert",
            ))
        return out

    def _vader_analyze(self, text: str) -> SentimentResult:
        self._load_vader()
        if self._vader is None:
            return SentimentResult(
                text=text[:200], label="neutral",
                positive=0.0, negative=0.0, neutral=1.0, model="none",
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
        )


@lru_cache(maxsize=1)
def get_analyzer(use_finbert: bool = True) -> FinBERTAnalyzer:
    """Singleton accessor for the sentiment analyzer."""
    return FinBERTAnalyzer(use_finbert=use_finbert)
