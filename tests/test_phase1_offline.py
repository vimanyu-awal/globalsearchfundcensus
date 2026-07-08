"""Offline unit + integration tests for Phase 1.

No network: every SEC/price call is stubbed with synthetic fixtures. Runnable
with pytest OR directly (`python tests/test_phase1_offline.py`). This is the
verification that the transformation logic is correct where live EDGAR is
blocked; a full live run additionally requires www.sec.gov reachability.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from microcap import config, sec_edgar, sec_parse, universe  # noqa: E402
from microcap.prices import PriceInfo  # noqa: E402
from microcap.report import cp1_report  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
def make_companyfacts(entries):
    """entries: list of (val, end, accn, filed, form)."""
    rows = [{"val": v, "end": e, "accn": a, "filed": f, "form": fm} for (v, e, a, f, fm) in entries]
    return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": rows}}}}}


def make_submissions(*, sic="3559", forms, dates, accns, country="NY", name="Test Co"):
    return {
        "name": name,
        "sic": sic,
        "addresses": {"business": {"stateOrCountry": country}},
        "filings": {"recent": {"form": forms, "filingDate": dates, "accessionNumber": accns}},
    }


ASOF = date(2026, 7, 8)


# --------------------------------------------------------------------------
# Unit tests
# --------------------------------------------------------------------------
def test_iter_master():
    master = {"fields": ["cik", "name", "ticker", "exchange"],
              "data": [[320193, "Apple", "AAPL", "Nasdaq"], [111, "OTC Co", "OTCC", "OTC"]]}
    got = list(universe.iter_master(master))
    assert got == [(320193, "AAPL", "Nasdaq"), (111, "OTCC", "OTC")], got


def test_exchange_gate():
    p = config.Params(otc_allowed=False)
    assert universe._exchange_kept("NYSE", p)
    assert universe._exchange_kept("Nasdaq", p)
    assert universe._exchange_kept("NYSE American", p)
    assert not universe._exchange_kept("OTC", p)
    assert not universe._exchange_kept("", p)
    assert universe._exchange_kept("OTC", config.Params(otc_allowed=True))


def test_shares_latest_and_multiclass_sum():
    # Two share classes reported on the same cover-page date -> summed.
    cf = make_companyfacts([
        (9_000_000, "2025-03-31", "acc-old", "2025-04-01", "10-K"),
        (6_000_000, "2026-03-31", "acc-A", "2026-04-01", "10-K"),
        (4_000_000, "2026-03-31", "acc-B", "2026-04-02", "10-K"),
    ])
    s = sec_parse.latest_shares_outstanding(cf)
    assert s.value == 10_000_000, s.value
    assert s.end == "2026-03-31"
    assert s.accession == "acc-B"  # newest filed among the latest-end rows


def test_shares_unknown_when_absent():
    assert sec_parse.latest_shares_outstanding({"facts": {"dei": {}}}).value is None
    assert sec_parse.latest_shares_outstanding(None).value is None


def test_latest_annual_report_picks_newest():
    sub = make_submissions(
        forms=["8-K", "10-K", "10-Q", "10-K"],
        dates=["2026-05-01", "2024-03-15", "2026-02-01", "2025-03-20"],
        accns=["a8k", "aOld", "a10q", "aNew"],
    )
    la = sec_parse.latest_annual_report(sub)
    assert la.filing_date == "2025-03-20" and la.accession == "aNew", la


def test_dark_boundary():
    # 15 months is the threshold; older than 15 months => dark.
    assert not sec_parse.is_dark("2025-05-08", ASOF, 15)   # 14 months -> fresh
    assert sec_parse.is_dark("2025-03-08", ASOF, 15)       # 16 months -> dark
    assert sec_parse.is_dark(None, ASOF, 15)               # no filing -> dark


def test_exclusions():
    assert sec_parse.is_excluded_sic(6770)
    assert not sec_parse.is_excluded_sic(3559)
    assert sec_parse.is_financial_track(6022)      # a bank
    assert not sec_parse.is_financial_track(3559)
    china = make_submissions(forms=["20-F"], dates=["2026-01-01"], accns=["x"], country="F4")
    assert sec_parse.is_china_domiciled(china)


def test_assemble_row_cap_and_flags():
    cf = make_companyfacts([(10_000_000, "2026-03-31", "acc-A", "2026-04-01", "10-K")])
    sub = make_submissions(sic="6022", forms=["10-K"], dates=["2026-04-01"], accns=["acc-A"])
    price = PriceInfo(last_close=5.0, adv20=120_000, source="yfinance", asof="2026-07-07", yf_shares=10_050_000)
    row = universe.assemble_row(999, "BANKX", "Nasdaq", "Bank X", cf, sub, price, asof=ASOF)
    assert row.market_cap == 50_000_000
    assert row.financial_track is True
    assert row.dark is False
    assert row.multi_class_check is False       # 0.5% apart
    assert "acc-A" == row.shares_accession


def test_assemble_row_multiclass_trigger_and_unknowns():
    cf = make_companyfacts([(20_000_000, "2026-03-31", "acc-A", "2026-04-01", "10-K")])
    sub = make_submissions(forms=["20-F"], dates=["2026-04-01"], accns=["acc-A"])
    price = PriceInfo(last_close=3.0, adv20=None, source="yfinance", asof="x", yf_shares=10_000_000)
    row = universe.assemble_row(1, "FPIX", "NYSE American", "FPI X", cf, sub, price, asof=ASOF)
    assert row.multi_class_check is True and "MULTI_CLASS_CHECK" in row.notes
    assert row.fpi is True
    # Missing shares -> cap unknown, PRICE known.
    row2 = universe.assemble_row(2, "NOSH", "NYSE", "No Shares", None, sub, price, asof=ASOF)
    assert row2.market_cap is None and "SHARES_UNKNOWN" in row2.notes


# --------------------------------------------------------------------------
# Integration test — full build with stubbed I/O
# --------------------------------------------------------------------------
def test_build_universe_end_to_end(monkeypatch=None):
    master = {"fields": ["cik", "name", "ticker", "exchange"], "data": [
        [1, "Keep Me", "KEEP", "Nasdaq"],       # in band -> kept
        [2, "Too Big", "BIG", "NYSE"],           # cap over band -> dropped
        [3, "Illiquid", "ILQ", "NYSE American"], # ADV below floor -> dropped
        [4, "OTC Co", "OTCC", "OTC"],            # OTC -> dropped at gate
        [5, "Spac Co", "SPAC", "Nasdaq"],        # SIC 6770 -> excluded
        [6, "China Co", "CHN", "Nasdaq"],        # China domicile -> excluded
    ]}

    facts = {
        1: make_companyfacts([(10_000_000, "2026-03-31", "acc1", "2026-04-01", "10-K")]),
        2: make_companyfacts([(50_000_000, "2026-03-31", "acc2", "2026-04-01", "10-K")]),
        3: make_companyfacts([(5_000_000, "2026-03-31", "acc3", "2026-04-01", "10-K")]),
        5: make_companyfacts([(1_000_000, "2026-03-31", "acc5", "2026-04-01", "10-K")]),
        6: make_companyfacts([(5_000_000, "2026-03-31", "acc6", "2026-04-01", "10-K")]),
    }
    subs = {
        1: make_submissions(sic="3559", forms=["10-K"], dates=["2026-04-01"], accns=["acc1"]),
        2: make_submissions(sic="3559", forms=["10-K"], dates=["2026-04-01"], accns=["acc2"]),
        3: make_submissions(sic="3559", forms=["10-K"], dates=["2026-04-01"], accns=["acc3"]),
        5: make_submissions(sic="6770", forms=["10-K"], dates=["2026-04-01"], accns=["acc5"]),
        6: make_submissions(sic="3559", forms=["10-K"], dates=["2026-04-01"], accns=["acc6"], country="F4"),
    }
    prices = {
        "KEEP": PriceInfo(6.0, 200_000, "yfinance", "2026-07-07", 10_000_000),   # cap 60M, adv ok
        "BIG": PriceInfo(4.0, 500_000, "yfinance", "2026-07-07", 50_000_000),    # cap 200M
        "ILQ": PriceInfo(5.0, 1_000, "yfinance", "2026-07-07", 5_000_000),       # cap 25M, adv 1k
    }

    def fake_master(refresh=False):
        return master

    def fake_facts(cik, refresh=False):
        return facts.get(cik)

    def fake_subs(cik, refresh=False):
        return subs.get(cik)

    def fake_price(ticker, refresh=False):
        return prices.get(ticker, PriceInfo(None, None, None, None))

    # Patch without requiring pytest's monkeypatch fixture.
    orig = (sec_edgar.fetch_tickers_exchange, sec_edgar.fetch_companyfacts,
            sec_edgar.fetch_submissions, universe.get_price)
    sec_edgar.fetch_tickers_exchange = fake_master
    sec_edgar.fetch_companyfacts = fake_facts
    sec_edgar.fetch_submissions = fake_subs
    universe.get_price = fake_price
    try:
        rows, diag = universe.build_universe(asof=ASOF)
    finally:
        (sec_edgar.fetch_tickers_exchange, sec_edgar.fetch_companyfacts,
         sec_edgar.fetch_submissions, universe.get_price) = orig

    kept = {r.ticker for r in rows}
    assert kept == {"KEEP"}, kept
    assert diag.drop_counts.get("exchange") == 1
    assert diag.drop_counts.get("excluded_sic_6770") == 1
    assert diag.drop_counts.get("china_domiciled") == 1
    assert diag.drop_counts.get("cap_out_of_band") == 1
    assert diag.drop_counts.get("adv_below_floor") == 1
    # CP1 report renders without error and mentions the kept name.
    text = cp1_report(rows, diag, ASOF)
    assert "KEEP" in text and "CHECKPOINT 1" in text


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} offline tests passed.")


if __name__ == "__main__":
    _run_all()
