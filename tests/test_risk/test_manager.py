"""Tests for the multi-layer risk manager."""


from backend.models.schemas import StrategyName, TradeSignal
from backend.risk.manager import RiskManager


def _make_signal(**overrides) -> TradeSignal:
    defaults = dict(
        strategy=StrategyName.STAT_ARB, ticker="AAPL", direction="long",
        conviction=0.8, kelly_size_pct=5.0, entry_price=150, stop_loss=145,
        target=165, max_hold_days=14, edge_reason="test", kill_condition="stop",
        expected_sharpe=1.5,
    )
    defaults.update(overrides)
    return TradeSignal(**defaults)


class TestRiskManager:
    def test_approves_valid_trade(self, vol_normal):
        rm = RiskManager(initial_capital=100_000)
        signal = _make_signal()
        result = rm.check_trade(signal, vol_normal, [], {})
        assert result["approved"] is True
        assert result["adjusted_size"] > 0

    def test_rejects_no_stop_loss(self, vol_normal):
        rm = RiskManager()
        signal = _make_signal(stop_loss=0)
        result = rm.check_trade(signal, vol_normal, [], {})
        assert result["approved"] is False

    def test_caps_gross_exposure(self, vol_normal):
        rm = RiskManager()
        existing = [_make_signal(kelly_size_pct=80) for _ in range(3)]
        signal = _make_signal(kelly_size_pct=50)
        result = rm.check_trade(signal, vol_normal, existing, {})
        assert result["adjusted_size"] < signal.kelly_size_pct / 100

    def test_drawdown_flattens(self, vol_normal):
        rm = RiskManager(initial_capital=100_000)
        rm.current_capital = 80_000  # -20% drawdown
        signal = _make_signal()
        result = rm.check_trade(signal, vol_normal, [], {})
        assert result["approved"] is False

    def test_update_capital(self):
        rm = RiskManager(initial_capital=100_000)
        rm.update_capital(110_000)
        assert rm.peak_capital == 110_000
        rm.update_capital(105_000)
        assert rm.peak_capital == 110_000  # Peak doesn't decrease

    def test_strategy_circuit_breaker(self):
        rm = RiskManager()
        rm.record_strategy_pnl("stat_arb", -0.12)
        assert "stat_arb" in rm.strategy_pause_until

    def test_returns_risk_limits(self, vol_normal):
        rm = RiskManager()
        signal = _make_signal()
        result = rm.check_trade(signal, vol_normal, [], {})
        assert "risk_limits" in result
