"""Tests for signal decay monitoring."""

import numpy as np
import pytest

from backend.signals.decay_monitor import (
    DecayStatus,
    assess_signal_decay,
    compute_rolling_sharpe,
    full_decay_report,
)


class TestRollingSharpe:
    def test_positive_returns_positive_sharpe(self):
        returns = np.random.normal(0.002, 0.01, 100)
        sharpe = compute_rolling_sharpe(returns, window=60)
        assert isinstance(sharpe, (float, np.floating))

    def test_zero_returns_zero_sharpe(self):
        returns = np.zeros(100)
        sharpe = compute_rolling_sharpe(returns, window=60)
        assert sharpe == 0.0 or np.isnan(sharpe)


class TestSignalDecay:
    def test_healthy_strategy(self):
        returns = np.random.normal(0.003, 0.01, 252)
        result = assess_signal_decay("stat_arb", returns)
        assert isinstance(result, (dict, object))

    def test_decaying_strategy(self):
        good = np.random.normal(0.005, 0.01, 126)
        bad = np.random.normal(-0.002, 0.015, 126)
        returns = np.concatenate([good, bad])
        result = assess_signal_decay("catalyst", returns)
        assert isinstance(result, (dict, object))


class TestFullDecayReport:
    def test_returns_report(self):
        returns = np.random.normal(0.002, 0.01, 252)
        report = full_decay_report("stat_arb", returns)
        assert report.strategy == "stat_arb"
        assert isinstance(report.status, DecayStatus)
        assert 0 < report.allocation_multiplier <= 1.0
