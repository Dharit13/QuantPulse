"""Tests for data source implementations.

Tests run without API keys by mocking HTTP responses.
Validates: correct URL construction, response parsing, error handling,
graceful degradation, and output format compatibility.
"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

# ── FMP Source Tests ─────────────────────────────────────────────


class TestFMPSource:
    def _make_source(self):
        with patch("backend.config.settings") as mock_settings:
            mock_settings.fmp_api_key = "test_key"
            from backend.data.sources.fmp_src import FMPSource
            src = FMPSource()
            src._api_key = "test_key"
            return src

    def test_disabled_without_key(self):
        from backend.data.sources.fmp_src import FMPSource
        src = FMPSource()
        src._api_key = ""
        assert src._enabled() is False
        assert src.get_fundamentals("AAPL") == {}
        assert src.get_earnings("AAPL") == []
        assert src.get_analyst_estimates("AAPL") == []
        assert src.get_earnings_calendar() == []

    def test_get_fundamentals_parses_profile(self):
        src = self._make_source()
        mock_profile = [{
            "marketCap": 3_000_000_000_000,
            "pe": 30.5,
            "eps": 6.5,
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "volAvg": 50_000_000,
            "beta": 1.2,
            "lastDividend": 0.96,
            "price": 195.0,
        }]
        mock_ratios = [{"priceEarningsRatio": 30.5, "netProfitMargin": 0.25, "debtEquityRatio": 1.8}]
        mock_metrics = [{"peRatio": 28.0, "debtToEquity": 1.5}]

        with patch.object(src, "_get", side_effect=[mock_profile, mock_ratios, mock_metrics]):
            result = src.get_fundamentals("AAPL")

        assert result["market_cap"] == 3_000_000_000_000
        assert result["pe_ratio"] == 30.5
        assert result["sector"] == "Technology"
        assert result["beta"] == 1.2

    def test_get_earnings_parses_income_statements(self):
        src = self._make_source()
        mock_data = [
            {"date": "2024-01-25", "eps": 2.18, "epsDiluted": 2.18, "revenue": 120_000_000_000, "netIncome": 33_000_000_000},
            {"date": "2023-10-26", "eps": 1.46, "epsDiluted": 1.46, "revenue": 110_000_000_000, "netIncome": 28_000_000_000},
        ]

        with patch.object(src, "_get", return_value=mock_data):
            result = src.get_earnings("AAPL")

        assert len(result) == 2
        assert result[0]["eps_actual"] == 2.18
        assert isinstance(result[0]["date"], date)

    def test_get_earnings_calendar_default_dates(self):
        src = self._make_source()
        mock_data = [
            {"date": "2024-02-01", "symbol": "AAPL", "epsEstimated": 2.10, "revenueEstimated": 120_000_000_000},
        ]

        with patch.object(src, "_get", return_value=mock_data):
            result = src.get_earnings_calendar()

        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"

    def test_get_fundamentals_http_error_returns_empty(self):
        src = self._make_source()
        import httpx
        with patch.object(src, "_get", side_effect=httpx.HTTPStatusError("403", request=MagicMock(), response=MagicMock())):
            result = src.get_fundamentals("AAPL")
        assert result == {}

    def test_eps_surprises_delegates_to_get_earnings(self):
        src = self._make_source()
        mock_data = [{"date": "2024-01-25", "eps": 2.0, "epsDiluted": 2.0, "revenue": 100_000_000_000, "netIncome": 25_000_000_000}]
        with patch.object(src, "_get", return_value=mock_data):
            result = src.get_eps_surprises("AAPL")
        assert len(result) == 1


# ── Finnhub Source Tests ─────────────────────────────────────────


class TestFinnhubSource:
    def _make_source(self):
        from backend.data.sources.finnhub_src import FinnhubSource
        src = FinnhubSource()
        src._api_key = "test_key"
        return src

    def test_disabled_without_key(self):
        from backend.data.sources.finnhub_src import FinnhubSource
        src = FinnhubSource()
        src._api_key = ""
        assert src._enabled() is False
        assert src.get_analyst_revisions("AAPL") == []
        assert src.get_news("AAPL") == []
        assert src.get_earnings_surprises("AAPL") == []
        assert src.get_recommendation_trends("AAPL") == []

    def test_get_recommendation_trends_shape(self):
        src = self._make_source()
        mock_data = [
            {"period": "2024-02-01", "strongBuy": 12, "buy": 20, "hold": 8, "sell": 2, "strongSell": 0},
            {"period": "2024-01-01", "strongBuy": 10, "buy": 18, "hold": 10, "sell": 3, "strongSell": 1},
        ]

        with patch.object(src, "_get", return_value=mock_data):
            result = src.get_recommendation_trends("AAPL")

        assert len(result) == 2
        assert "strong_buy" in result[0]
        assert "buy" in result[0]
        assert "hold" in result[0]
        assert "sell" in result[0]
        assert "strong_sell" in result[0]
        assert isinstance(result[0]["date"], date)

    def test_get_news_shape(self):
        src = self._make_source()
        mock_data = [
            {
                "headline": "Apple Reports Record Q1",
                "summary": "Revenue beats estimates",
                "source": "Reuters",
                "url": "https://example.com",
                "datetime": 1706745600,
                "category": "company",
                "related": "AAPL",
                "image": "",
            },
        ]

        with patch.object(src, "_get", return_value=mock_data):
            result = src.get_news("AAPL")

        assert len(result) == 1
        assert result[0]["headline"] == "Apple Reports Record Q1"
        assert result[0]["title"] == "Apple Reports Record Q1"
        assert isinstance(result[0]["datetime"], datetime)

    def test_get_analyst_revisions_classifies_actions(self):
        src = self._make_source()
        mock_data = [
            {"gradeDate": "2024-02-01", "company": "Morgan Stanley", "action": "upgrade", "fromGrade": "Hold", "toGrade": "Overweight"},
            {"gradeDate": "2024-01-15", "company": "Goldman Sachs", "action": "downgrade", "fromGrade": "Buy", "toGrade": "Neutral"},
        ]

        with patch.object(src, "_get", return_value=mock_data):
            result = src.get_analyst_revisions("AAPL")

        assert len(result) == 2
        assert result[0]["is_upgrade"] is True
        assert result[1]["is_downgrade"] is True

    def test_get_earnings_surprises_shape(self):
        src = self._make_source()
        mock_data = [
            {"actual": 2.18, "estimate": 2.10, "period": "2024-01-25", "surprisePercent": 3.81, "quarter": 1, "year": 2024},
        ]

        with patch.object(src, "_get", return_value=mock_data):
            result = src.get_earnings_surprises("AAPL")

        assert len(result) == 1
        assert result[0]["eps_actual"] == 2.18
        assert result[0]["surprise_pct"] == 3.81


# ── FRED Source Tests ────────────────────────────────────────────


class TestFREDSource:
    def _make_source(self):
        from backend.data.sources.fred_src import FREDSource
        src = FREDSource()
        src._api_key = "test_key"
        return src

    def test_disabled_without_key(self):
        from backend.data.sources.fred_src import FREDSource
        src = FREDSource()
        src._api_key = ""
        assert src._enabled() is False
        assert src.get_series("DGS10").empty
        assert src.get_yield_curve() == {}
        assert src.get_macro_snapshot() == {}

    def test_get_series_parses_observations(self):
        src = self._make_source()
        mock_data = {
            "observations": [
                {"date": "2024-02-01", "value": "4.15"},
                {"date": "2024-02-02", "value": "4.12"},
                {"date": "2024-02-03", "value": "."},  # missing value, should be skipped
            ]
        }

        with patch.object(src, "_get", return_value=mock_data):
            result = src.get_series("DGS10")

        assert isinstance(result, pd.Series)
        assert len(result) == 2
        assert result.iloc[0] == 4.15

    def test_get_series_by_name_maps_correctly(self):
        self._make_source()
        from backend.data.sources.fred_src import SERIES_IDS

        assert SERIES_IDS["10y_yield"] == "DGS10"
        assert SERIES_IDS["unemployment"] == "UNRATE"
        assert SERIES_IDS["hy_oas"] == "BAMLH0A0HYM2"

    def test_get_series_by_name_unknown_returns_empty(self):
        src = self._make_source()
        result = src.get_series_by_name("nonexistent_series")
        assert result.empty

    def test_get_macro_snapshot_returns_dict(self):
        src = self._make_source()
        mock_obs = {"observations": [{"date": "2024-02-01", "value": "4.15"}]}

        with patch.object(src, "_get", return_value=mock_obs):
            result = src.get_macro_snapshot()

        assert isinstance(result, dict)
        for key in ("10y_yield", "2y_yield", "fed_funds", "hy_oas", "unemployment"):
            assert key in result


# ── EDGAR Source Tests ───────────────────────────────────────────


class TestEDGARSource:
    def _make_source(self):
        from backend.data.sources.edgar_src import EDGARSource
        src = EDGARSource()
        src._email = "test@example.com"
        return src

    def test_disabled_without_email(self):
        from backend.data.sources.edgar_src import EDGARSource
        src = EDGARSource()
        src._email = ""
        assert src._enabled() is False
        assert src.get_insider_trades("AAPL") == []
        assert src.score_insider_buying("AAPL") == {"signal_score": 0, "transactions": []}

    def test_score_insider_buying_empty_trades(self):
        src = self._make_source()
        with patch.object(src, "get_insider_trades", return_value=[]):
            result = src.score_insider_buying("AAPL")
        assert result["signal_score"] == 0

    def test_score_insider_buying_with_buys(self):
        src = self._make_source()
        mock_trades = [
            {"ticker": "AAPL", "filing_date": date.today().isoformat(), "insider_name": "Tim Cook",
             "title": "Chief Executive Officer", "transaction_type": "buy", "shares": 10000,
             "price": 195.0, "value": 1_950_000, "ownership_type": "direct"},
            {"ticker": "AAPL", "filing_date": date.today().isoformat(), "insider_name": "Luca Maestri",
             "title": "Chief Financial Officer", "transaction_type": "buy", "shares": 5000,
             "price": 194.0, "value": 970_000, "ownership_type": "direct"},
        ]

        with patch.object(src, "get_insider_trades", return_value=mock_trades):
            result = src.score_insider_buying("AAPL")

        assert result["buy_count"] == 2
        assert result["sell_count"] == 0
        assert result["cluster_buy"] is True
        assert result["c_suite_buying"] is True
        assert result["signal_score"] > 50

    def test_form4_xml_parsing(self):
        src = self._make_source()
        xml = """<?xml version="1.0"?>
        <ownershipDocument>
            <reportingOwner>
                <reportingOwnerId><rptOwnerName>John Doe</rptOwnerName></reportingOwnerId>
                <reportingOwnerRelationship><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
            </reportingOwner>
            <nonDerivativeTable>
                <nonDerivativeTransaction>
                    <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
                    <transactionAmounts>
                        <transactionShares><value>1000</value></transactionShares>
                        <transactionPricePerShare><value>150.00</value></transactionPricePerShare>
                        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
                    </transactionAmounts>
                    <ownershipNature>
                        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
                    </ownershipNature>
                </nonDerivativeTransaction>
            </nonDerivativeTable>
        </ownershipDocument>"""

        result = src._parse_form4_xml(xml, "TEST", "2024-02-01")
        assert len(result) == 1
        assert result[0]["transaction_type"] == "buy"
        assert result[0]["shares"] == 1000
        assert result[0]["price"] == 150.00
        assert result[0]["insider_name"] == "John Doe"


# ── FINRA Source Tests ───────────────────────────────────────────


class TestFINRASource:
    def _make_source(self):
        from backend.data.sources.finra_src import FINRASource
        return FINRASource()

    def test_compute_metrics_empty_data(self):
        src = self._make_source()
        with patch.object(src, "get_weekly_ats_volume", return_value=pd.DataFrame()):
            result = src.compute_dark_pool_metrics("AAPL")
        assert result["signal_score"] == 0.0
        assert result["avg_weekly_volume"] == 0

    def test_compute_metrics_rising_volume(self):
        src = self._make_source()
        df = pd.DataFrame({
            "week_start": pd.date_range("2024-01-01", periods=8, freq="W"),
            "ats_volume": [100, 110, 120, 130, 150, 170, 200, 250],
            "trades_count": [50, 55, 60, 65, 75, 85, 100, 125],
        })

        with patch.object(src, "get_weekly_ats_volume", return_value=df):
            result = src.compute_dark_pool_metrics("AAPL")

        assert result["recent_volume"] == 250
        assert result["volume_zscore"] > 0
        assert result["weeks_increasing"] > 0
        assert result["signal_score"] > 0

    def test_scan_for_accumulation_filters_by_score(self):
        src = self._make_source()
        high_score = {"signal_score": 60.0, "avg_weekly_volume": 1000}
        low_score = {"signal_score": 10.0, "avg_weekly_volume": 100}

        with patch.object(src, "compute_dark_pool_metrics", side_effect=[high_score, low_score]):
            results = src.scan_for_accumulation(["AAPL", "MSFT"], min_score=40.0)

        assert len(results) == 1
        assert results[0]["ticker"] == "AAPL"


# ── SteadyAPI Source Tests ───────────────────────────────────────


class TestSteadyAPISource:
    def test_disabled_without_key_and_flag(self):
        from backend.data.sources.steadyapi_src import SteadyAPISource
        src = SteadyAPISource()
        src._api_key = ""
        assert src._enabled() is False
        assert src.get_options_flow() == []
        assert src.get_unusual_options_activity() == []

    def test_normalize_flow_record(self):
        from backend.data.sources.steadyapi_src import _normalize_flow_record
        raw = {
            "baseSymbol": "AAPL",
            "symbol": "AAPL240216C00195000",
            "symbolType": "Call",
            "strikePrice": 195,
            "expiration": "02/16/24",
            "dte": 14,
            "lastPrice": 195.50,
            "tradePrice": 3.20,
            "tradeSize": "500",
            "side": "ask",
            "premium": "$160,000",
            "volume": "1,200",
            "openInterest": "5,000",
            "volatility": "25.50%",
            "delta": 0.55,
            "tradeCondition": "SLCN",
            "label": "BuyToOpen",
            "tradeTime": "02/01/24 14:30:00",
        }

        result = _normalize_flow_record(raw)
        assert result["symbol"] == "AAPL"
        assert result["option_type"] == "Call"
        assert result["premium"] == 160_000
        assert result["volume"] == 1200
        assert result["is_sweep"] is True
        assert result["is_block"] is False
        assert result["is_institutional"] is True
