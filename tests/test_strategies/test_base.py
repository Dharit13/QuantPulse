"""Tests for BaseStrategy interface and strategy instantiation."""

import pytest

from backend.adaptive.vol_context import VolContext
from backend.models.schemas import StrategyName, TradeSignal
from backend.strategies.base import BaseStrategy
from backend.strategies.catalyst_event import CatalystEventStrategy
from backend.strategies.cross_asset_momentum import CrossAssetMomentumStrategy
from backend.strategies.flow_imbalance import FlowImbalanceStrategy
from backend.strategies.gap_reversion import GapReversionStrategy
from backend.strategies.stat_arb import StatArbStrategy


class TestBaseStrategy:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseStrategy()

    def test_validate_signal_rejects_low_conviction(self):
        class Dummy(BaseStrategy):
            @property
            def name(self) -> str:
                return "dummy"
            def generate_signals(self, vol, **kw):
                return []
            def get_params(self, vol):
                return {}

        d = Dummy()
        signal = TradeSignal(
            strategy=StrategyName.STAT_ARB, ticker="AAPL", direction="long",
            conviction=0.1, kelly_size_pct=3.0, entry_price=150, stop_loss=145,
            target=160, max_hold_days=14, edge_reason="test", kill_condition="test",
            expected_sharpe=1.0,
        )
        assert d.validate_signal(signal) is False

    def test_validate_signal_rejects_missing_edge(self):
        class Dummy(BaseStrategy):
            @property
            def name(self) -> str:
                return "dummy"
            def generate_signals(self, vol, **kw):
                return []
            def get_params(self, vol):
                return {}

        d = Dummy()
        signal = TradeSignal(
            strategy=StrategyName.STAT_ARB, ticker="AAPL", direction="long",
            conviction=0.8, kelly_size_pct=3.0, entry_price=150, stop_loss=145,
            target=160, max_hold_days=14, edge_reason="", kill_condition="test",
            expected_sharpe=1.0,
        )
        assert d.validate_signal(signal) is False

    def test_validate_signal_accepts_good_signal(self):
        class Dummy(BaseStrategy):
            @property
            def name(self) -> str:
                return "dummy"
            def generate_signals(self, vol, **kw):
                return []
            def get_params(self, vol):
                return {}

        d = Dummy()
        signal = TradeSignal(
            strategy=StrategyName.STAT_ARB, ticker="AAPL", direction="long",
            conviction=0.8, kelly_size_pct=3.0, entry_price=150, stop_loss=145,
            target=160, max_hold_days=14, edge_reason="test edge", kill_condition="stop hit",
            expected_sharpe=1.5,
        )
        assert d.validate_signal(signal) is True


class TestStrategyInstantiation:
    """All 5 strategies should instantiate and have the correct name."""

    @pytest.mark.parametrize("cls,expected_name", [
        (StatArbStrategy, "stat_arb"),
        (CatalystEventStrategy, "catalyst"),
        (CrossAssetMomentumStrategy, "cross_asset"),
        (FlowImbalanceStrategy, "flow"),
        (GapReversionStrategy, "intraday"),
    ])
    def test_strategy_name(self, cls, expected_name):
        strategy = cls()
        assert strategy.name == expected_name

    @pytest.mark.parametrize("cls", [
        StatArbStrategy, CatalystEventStrategy, CrossAssetMomentumStrategy,
        FlowImbalanceStrategy, GapReversionStrategy,
    ])
    def test_get_params_returns_dict(self, cls, vol_normal):
        strategy = cls()
        params = strategy.get_params(vol_normal)
        assert isinstance(params, dict)

    @pytest.mark.parametrize("cls", [
        StatArbStrategy, CatalystEventStrategy, CrossAssetMomentumStrategy,
        FlowImbalanceStrategy, GapReversionStrategy,
    ])
    def test_params_change_with_vol(self, cls, vol_normal, vol_crisis):
        strategy = cls()
        params_normal = strategy.get_params(vol_normal)
        params_crisis = strategy.get_params(vol_crisis)
        assert isinstance(params_normal, dict)
        assert isinstance(params_crisis, dict)
