"""SEC EDGAR data source — insider trades (Form 4) and institutional holdings (13F).

No API key required. SEC policy: include User-Agent with contact email.
Rate limit: 10 requests/sec (SEC fair access policy).

Form 4 (insider trades): filed within 2 business days of transaction.
  - CEO/CFO/director buying own stock is a strong conviction signal.
  - Cluster buys (3+ insiders in 30 days) are even stronger.

13F-HR (institutional holdings): filed quarterly within 45 days of quarter end.
  - Track institutional accumulation/trimming over quarters.

Docs: https://www.sec.gov/search#/dateRange=custom&q=form-type%3D%224%22
EDGAR full-text search API: https://efts.sec.gov/LATEST/search-index
"""

import logging
from datetime import date, datetime, timedelta
from xml.etree import ElementTree

import httpx
import pandas as pd

from backend.config import settings
from backend.data.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_FILINGS_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
EDGAR_FULL_TEXT_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_COMPANY_URL = "https://data.sec.gov/submissions"


class EDGARSource:
    """SEC EDGAR data source for insider trades and institutional filings.

    All methods degrade gracefully when no email is configured or requests fail.
    """

    SOURCE_NAME = "edgar"

    def __init__(self) -> None:
        self._email = settings.sec_edgar_email
        self._client: httpx.Client | None = None

    @property
    def _http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            ua = f"QuantPulse/2.0 ({self._email})" if self._email else "QuantPulse/2.0"
            self._client = httpx.Client(
                timeout=15.0,
                headers={
                    "User-Agent": ua,
                    "Accept": "application/json",
                },
            )
        return self._client

    def _enabled(self) -> bool:
        return bool(self._email)

    def _get(self, url: str, params: dict | None = None) -> dict | list:
        """Rate-limited GET returning parsed JSON."""
        resp = rate_limiter.request_with_retry(
            self.SOURCE_NAME,
            self._http,
            "GET",
            url,
            params=params,
        )
        return resp.json()

    def _get_text(self, url: str) -> str:
        """Rate-limited GET returning raw text (for XML parsing)."""
        rate_limiter.acquire(self.SOURCE_NAME)
        resp = self._http.get(url)
        resp.raise_for_status()
        return resp.text

    # ── CIK Lookup ──────────────────────────────────────────────

    def _get_cik(self, ticker: str) -> str | None:
        """Look up SEC CIK number for a ticker."""
        try:
            data = self._get(
                "https://www.sec.gov/files/company_tickers.json",
            )
            ticker_upper = ticker.upper()
            for entry in data.values():
                if entry.get("ticker", "").upper() == ticker_upper:
                    return str(entry["cik_str"]).zfill(10)
            return None
        except Exception:
            logger.debug("CIK lookup failed for %s", ticker)
            return None

    # ── Insider Trades (Form 4) ─────────────────────────────────

    def get_insider_trades(
        self,
        ticker: str,
        days_back: int = 90,
    ) -> list[dict]:
        """Fetch recent insider transactions (Form 4 filings).

        Returns list of dicts with: filing_date, insider_name, title,
        transaction_type (buy/sell), shares, price, value, ownership_type.

        For swing trading the key signal is: insiders BUYING their own stock,
        especially CEO/CFO/directors, especially in clusters.
        """
        if not self._enabled():
            return []

        try:
            cik = self._get_cik(ticker)
            if not cik:
                logger.debug("No CIK found for %s, skipping insider trades", ticker)
                return []

            data = self._get(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
            )

            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])

            cutoff = (date.today() - timedelta(days=days_back)).isoformat()
            records: list[dict] = []

            for i, form_type in enumerate(forms):
                if form_type not in ("4", "4/A"):
                    continue
                if i >= len(dates) or dates[i] < cutoff:
                    continue

                record = self._parse_form4_from_index(
                    ticker=ticker,
                    cik=cik,
                    filing_date=dates[i],
                    accession=accessions[i] if i < len(accessions) else "",
                    primary_doc=primary_docs[i] if i < len(primary_docs) else "",
                )
                if record:
                    records.extend(record)

            records.sort(key=lambda r: r["filing_date"], reverse=True)
            logger.info("EDGAR: fetched %d insider transactions for %s", len(records), ticker)
            return records
        except httpx.HTTPStatusError as exc:
            logger.error("EDGAR insider trades HTTP error for %s: %s", ticker, exc)
            return []
        except Exception:
            logger.exception("EDGAR insider trades failed for %s", ticker)
            return []

    def _parse_form4_from_index(
        self,
        ticker: str,
        cik: str,
        filing_date: str,
        accession: str,
        primary_doc: str,
    ) -> list[dict]:
        """Parse a Form 4 XML filing to extract transaction details."""
        if not accession or not primary_doc:
            return []

        acc_no = accession.replace("-", "")
        cik_num = cik.lstrip("0")

        # primaryDocument often has an XSLT prefix like "xslF345X05/" —
        # strip it to get the raw XML filename
        raw_doc = primary_doc.split("/")[-1] if "/" in primary_doc else primary_doc
        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_no}/{raw_doc}"

        try:
            xml_text = self._get_text(doc_url)
            return self._parse_form4_xml(xml_text, ticker, filing_date)
        except Exception:
            logger.debug("Failed to parse Form 4 for %s (%s)", ticker, accession)
            return []

    def _parse_form4_xml(
        self,
        xml_text: str,
        ticker: str,
        filing_date: str,
    ) -> list[dict]:
        """Parse Form 4 XML to extract individual transactions."""
        records: list[dict] = []

        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return []

        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        owner_el = root.find(f".//{ns}reportingOwner")
        insider_name = ""
        title = ""
        if owner_el is not None:
            name_el = owner_el.find(f".//{ns}rptOwnerName")
            insider_name = name_el.text.strip() if name_el is not None and name_el.text else ""
            title_el = owner_el.find(f".//{ns}officerTitle")
            title = title_el.text.strip() if title_el is not None and title_el.text else ""

        for txn in root.findall(f".//{ns}nonDerivativeTransaction"):
            code_el = txn.find(f".//{ns}transactionCode")
            code = code_el.text.strip() if code_el is not None and code_el.text else ""

            shares_el = txn.find(f".//{ns}transactionShares/{ns}value")
            shares = float(shares_el.text) if shares_el is not None and shares_el.text else 0

            price_el = txn.find(f".//{ns}transactionPricePerShare/{ns}value")
            price = float(price_el.text) if price_el is not None and price_el.text else 0.0

            acq_disp_el = txn.find(f".//{ns}transactionAcquiredDisposedCode/{ns}value")
            acq_disp = acq_disp_el.text.strip() if acq_disp_el is not None and acq_disp_el.text else ""

            if code == "P" or acq_disp == "A":
                txn_type = "buy"
            elif code == "S" or acq_disp == "D":
                txn_type = "sell"
            else:
                txn_type = code or "other"

            ownership_el = txn.find(f".//{ns}directOrIndirectOwnership/{ns}value")
            ownership = "direct" if ownership_el is None or ownership_el.text == "D" else "indirect"

            records.append({
                "ticker": ticker,
                "filing_date": filing_date,
                "insider_name": insider_name,
                "title": title,
                "transaction_type": txn_type,
                "shares": int(shares),
                "price": round(price, 2),
                "value": round(shares * price, 2),
                "ownership_type": ownership,
            })

        return records

    # ── Insider Signal Scoring ──────────────────────────────────

    def score_insider_buying(
        self,
        ticker: str,
        days_back: int = 90,
    ) -> dict:
        """Score insider buying activity for a ticker.

        Returns dict with:
          - buy_count: number of insider buy transactions
          - sell_count: number of insider sell transactions
          - net_buy_value: total buy value minus sell value
          - cluster_buy: True if 2+ insiders bought within 30 days
          - c_suite_buying: True if CEO/CFO/COO bought
          - signal_score: 0-100 composite score
          - transactions: list of individual transactions
        """
        if not self._enabled():
            return {"signal_score": 0, "transactions": []}

        trades = self.get_insider_trades(ticker, days_back=days_back)
        if not trades:
            return {"signal_score": 0, "transactions": []}

        buys = [t for t in trades if t["transaction_type"] == "buy"]
        sells = [t for t in trades if t["transaction_type"] == "sell"]

        buy_value = sum(t["value"] for t in buys)
        sell_value = sum(t["value"] for t in sells)

        # Cluster detection: 2+ distinct insiders buying within 30 days
        recent_cutoff = (date.today() - timedelta(days=30)).isoformat()
        recent_buyers = set()
        for t in buys:
            if t["filing_date"] >= recent_cutoff:
                recent_buyers.add(t["insider_name"])
        cluster_buy = len(recent_buyers) >= 2

        c_suite_titles = {"ceo", "cfo", "coo", "chief executive", "chief financial", "chief operating", "president"}
        c_suite_buying = any(
            any(cs in t.get("title", "").lower() for cs in c_suite_titles)
            for t in buys
        )

        # Composite scoring
        score = 0.0
        if buys:
            score += min(30.0, len(buys) * 10.0)
        if buy_value > 100_000:
            score += min(25.0, buy_value / 100_000 * 5.0)
        if cluster_buy:
            score += 20.0
        if c_suite_buying:
            score += 25.0
        if sell_value > 0 and buy_value > sell_value * 2:
            score += 10.0
        elif sells and not buys:
            score = max(0, score - 20.0)

        return {
            "buy_count": len(buys),
            "sell_count": len(sells),
            "net_buy_value": round(buy_value - sell_value, 2),
            "total_buy_value": round(buy_value, 2),
            "total_sell_value": round(sell_value, 2),
            "cluster_buy": cluster_buy,
            "c_suite_buying": c_suite_buying,
            "signal_score": min(100.0, round(score, 2)),
            "transactions": trades,
        }

    # ── 13F Institutional Holdings ──────────────────────────────

    def get_institutional_holders(self, ticker: str) -> list[dict]:
        """Get major institutional holders from recent 13F filings.

        Returns a simplified list since 13F parsing is complex. For the swing
        trading use case, the insider buying signal (Form 4) is more actionable.
        """
        if not self._enabled():
            return []

        try:
            cik = self._get_cik(ticker)
            if not cik:
                return []

            data = self._get(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
            )

            # Extract recent 13F filers who reference this company
            # This is a simplified approach — full 13F parsing would require
            # downloading and parsing SGML/XML information tables
            company_name = data.get("name", "")
            return [{
                "ticker": ticker,
                "company_name": company_name,
                "cik": cik,
                "note": "Full 13F institutional holdings parsing available via EDGAR XBRL feeds",
            }]
        except Exception:
            logger.debug("13F lookup failed for %s", ticker)
            return []


edgar_source = EDGARSource()
