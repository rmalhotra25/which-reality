"""Tests for the insider service (services/insider.py).

The insider signal comes from SEC EDGAR Form 4 filings, parsed
directly: only open-market purchases (P) and sales (S) count.
Grants, option exercises, gifts and dispositions to the issuer
are excluded. The summary is a pure function of the parsed
transactions, so it is pinned here; fetching is stubbed, no
network is used.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import insider as insider_service
from services.insider import (
    _parse_form4_xml,
    clear_insider_cache,
    fetch_insider,
    summarize_insider,
)

_SAMPLE_FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Financial Officer</officerTitle>
      <isTenPercentOwner>0</isTenPercentOwner>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-11-05</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value>180.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-11-06</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>2000</value></transactionShares>
        <transactionPricePerShare><value>190.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-11-07</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-11-08</value></transactionDate>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>3000</value></transactionShares>
        <transactionPricePerShare><value>50.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_parse_form4_keeps_only_open_market():
    txs = _parse_form4_xml(_SAMPLE_FORM4)
    assert len(txs) == 2
    codes = sorted(t["code"] for t in txs)
    assert codes == ["P", "S"]
    buy = next(t for t in txs if t["code"] == "P")
    assert buy["date"] == "2026-11-05"
    assert buy["shares"] == 5000
    assert buy["price"] == 180.00
    assert buy["value"] == 900000.00
    assert buy["insider"] == "DOE JANE"
    assert "Chief Financial Officer" in (buy["role"] or "")
    sell = next(t for t in txs if t["code"] == "S")
    assert sell["value"] == 380000.00


def test_parse_form4_bad_xml_returns_empty():
    assert _parse_form4_xml("not xml at all") == []
    assert _parse_form4_xml("") == []


def test_parse_form4_skips_zero_price():
    xml = _SAMPLE_FORM4.replace(
        "<transactionPricePerShare><value>180.00</value>",
        "<transactionPricePerShare><value>0</value>", 1)
    txs = _parse_form4_xml(xml)
    assert all(t["code"] != "P" for t in txs)


def _tx(code, value, date="2026-11-05", is_10b5=False):
    return {"date": date, "code": code, "shares": 100,
            "price": value / 100.0, "value": value,
            "insider": "X", "role": "Officer", "is_10b5": is_10b5}


def test_summary_buying_signal():
    out = summarize_insider([_tx("P", 2_000_000), _tx("P", 500_000)])
    assert out["signal"] == "buying"
    assert out["buys"]["count"] == 2
    assert out["buys"]["value"] == 2_500_000
    assert out["sells"]["count"] == 0
    assert out["net_value"] == 2_500_000
    assert out["heavy_sell"] is False


def test_summary_selling_signal():
    out = summarize_insider([_tx("S", 3_000_000), _tx("P", 100_000)])
    assert out["signal"] == "selling"
    assert out["net_value"] == -2_900_000
    assert out["heavy_sell"] is False


def test_summary_heavy_sell_trigger():
    # $30M of discretionary selling clears the $25M bar.
    out = summarize_insider([_tx("S", 30_000_000), _tx("P", 100_000)])
    assert out["signal"] == "selling"
    assert out["heavy_sell"] is True


def test_summary_heavy_sell_needs_discretionary():
    # $30M of selling that is all under 10b5-1 plans is routine,
    # not heavy: pre-arranged sales never trigger a sell on
    # their own. The same $30M sold discretionarily does.
    out = summarize_insider([_tx("S", 30_000_000, is_10b5=True)])
    assert out["signal"] == "mixed"
    assert out["heavy_sell"] is False
    out = summarize_insider([_tx("S", 30_000_000, is_10b5=False)])
    assert out["heavy_sell"] is True


def test_summary_heavy_sell_below_bar():
    # $13M of discretionary selling is routine executive
    # selling, below the $25M bar.
    out = summarize_insider([_tx("S", 13_000_000), _tx("P", 7_000_000)])
    assert out["signal"] == "selling"
    assert out["net_value"] == -6_000_000
    assert out["heavy_sell"] is False


def test_summary_mixed_and_quiet():
    out = summarize_insider([_tx("P", 400_000), _tx("S", 300_000)])
    assert out["signal"] == "mixed"
    assert out["net_value"] == 100_000
    out = summarize_insider([])
    assert out["signal"] == "quiet"
    assert out["buys"]["count"] == 0
    assert out["sells"]["count"] == 0


def test_summary_10b5_share_of_sales():
    out = summarize_insider([_tx("S", 2_000_000, is_10b5=True),
                             _tx("S", 1_000_000, is_10b5=False)])
    assert out["sell_10b5_value"] == 2_000_000
    assert out["sells"]["value"] == 3_000_000
    assert out["disc_sell_value"] == 1_000_000
    # Only the $1M discretionary sale moves the signal; the
    # $2M of planned sales does not.
    assert out["signal"] == "mixed"


def test_summary_notable_largest_first():
    out = summarize_insider([_tx("P", 100_000), _tx("P", 5_000_000),
                             _tx("S", 2_000_000)])
    assert out["notable"][0]["value"] == 5_000_000
    assert out["notable"][1]["value"] == 100_000
    assert out["notable"][2]["value"] == 2_000_000


def test_fetch_insider_edgar_success(monkeypatch):
    clear_insider_cache()
    txs = [_tx("P", 2_000_000)]
    monkeypatch.setattr(insider_service, "_fetch_edgar_transactions",
                        lambda ticker, window: (txs, None))
    payload = fetch_insider("AAPL")
    assert payload["status"] == "ok"
    assert payload["source"] == "edgar"
    assert payload["summary"]["signal"] == "buying"
    assert payload["transactions"] == txs


def test_fetch_insider_falls_back_to_yfinance(monkeypatch):
    clear_insider_cache()
    txs = [_tx("S", 2_000_000)]
    monkeypatch.setattr(insider_service, "_fetch_edgar_transactions",
                        lambda ticker, window: ([], "EDGAR down"))
    monkeypatch.setattr(insider_service, "_fetch_yfinance_transactions",
                        lambda ticker, window: (txs, None))
    payload = fetch_insider("MSFT")
    assert payload["status"] == "ok"
    assert payload["source"] == "yfinance"
    assert payload["summary"]["signal"] == "selling"


def test_fetch_insider_both_fail_reports_unavailable(monkeypatch):
    clear_insider_cache()
    monkeypatch.setattr(insider_service, "_fetch_edgar_transactions",
                        lambda ticker, window: ([], "EDGAR down"))
    monkeypatch.setattr(insider_service, "_fetch_yfinance_transactions",
                        lambda ticker, window: ([], "yfinance empty"))
    payload = fetch_insider("ZZZZ")
    assert payload["status"] == "unavailable"
    assert "EDGAR" in payload["reason"]
    assert payload["summary"]["signal"] == "quiet"


def test_fetch_form4_xml_prefers_raw_xml_over_rendered_html(monkeypatch):
    # The submissions JSON names the rendered HTML version
    # (xslF345X06/wk-form4_*.xml). The raw XML sits at the
    # accession root under the same file name. The fetcher must
    # use the raw XML, not the HTML rendering, or every filing
    # fails to parse and the signal reads "quiet" on real data.
    from services.insider import _fetch_form4_xml

    html = "<!DOCTYPE html><html><head></head><body>SEC Form 4</body></html>"
    seen = []

    def fake_get(url, timeout=15):
        seen.append(url)
        if "xslF345X06" in url:
            return html.encode()
        return _SAMPLE_FORM4.encode()

    monkeypatch.setattr(insider_service, "_http_get", fake_get)
    text = _fetch_form4_xml(1045810, "000119764726000013",
                            "xslF345X06/wk-form4_1793999520.xml")
    assert text is not None
    assert "<ownershipDocument" in text
    # The raw XML at the accession root is tried first, so the
    # HTML rendering is never even fetched.
    assert len(seen) == 1
    assert "xslF345X06" not in seen[0]
    assert seen[0].endswith("/wk-form4_1793999520.xml")


def test_fetch_form4_xml_falls_back_to_primary_doc(monkeypatch):
    # If the accession root has no raw XML, the full primary
    # document URL is tried next.
    from services.insider import _fetch_form4_xml

    seen = []

    def fake_get(url, timeout=15):
        seen.append(url)
        if "xslF345X06" in url:
            return _SAMPLE_FORM4.encode()
        raise RuntimeError("404")

    monkeypatch.setattr(insider_service, "_http_get", fake_get)
    text = _fetch_form4_xml(1045810, "000119764726000013",
                            "xslF345X06/wk-form4_1793999520.xml")
    assert text is not None
    assert "<ownershipDocument" in text
    assert len(seen) == 2
