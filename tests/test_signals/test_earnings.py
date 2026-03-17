"""Tests for earnings signal functions."""

import pytest

from backend.signals.earnings import score_earnings_surprise


class TestEarningsSurprise:
    def test_positive_surprise_scores_high(self):
        result = score_earnings_surprise(eps_actual=2.50, eps_estimate=2.00)
        assert isinstance(result, (float, int, dict))
        if isinstance(result, (float, int)):
            assert result > 0
        else:
            assert result.get("surprise_pct", 0) > 0

    def test_negative_surprise_scores_low(self):
        result = score_earnings_surprise(eps_actual=1.50, eps_estimate=2.00)
        assert isinstance(result, (float, int, dict))
        if isinstance(result, (float, int)):
            assert result < 0
        else:
            assert result.get("surprise_pct", 0) < 0

    def test_returns_value(self):
        result = score_earnings_surprise(eps_actual=2.50, eps_estimate=2.00)
        assert result is not None
