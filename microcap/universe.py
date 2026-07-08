"""Phase 1 — build the tradable microcap universe (SPEC Section 3).

Pipeline per candidate:
  1. ticker/CIK/exchange from company_tickers_exchange.json
  2. keep configured exchanges (drop OTC unless OTC_ALLOWED)
  3. shares outstanding from XBRL dei:EntityCommonStockSharesOutstanding,
     cross-checked against yfinance -> MULTI_CLASS_CHECK if >10% apart
  4. market cap = shares * latest close; keep CAP_MIN..CAP_MAX
  5. ADV(20d) from price data; drop below ADV_FLOOR
  6. staleness: latest 10-K/20-F older than 15 months -> DARK (kept, flagged)
  7. write universe.csv (+ duckdb) with provenance on every number

The row-assembly step (`assemble_row`) is pure given the fetched payloads, so
it is unit-tested offline. The driver (`build_universe`) does the I/O.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, asdict, field
from datetime import date
from typing import Any, Iterable

from . import config, sec_edgar, sec_parse
from .prices import PriceInfo, get_price


@dataclass
class UniverseRow:
    ticker: str
    cik: int
    exchange: str
    name: str
    # Figures (each with provenance columns alongside).
    shares_outstanding: float | None
    shares_accession: str | None       # provenance for shares (XBRL accn)
    shares_asof: str | None
    last_close: float | None
    price_source: str | None           # provenance for price
    price_asof: str | None
    market_cap: float | None
    adv20: float | None                # 20-day avg daily dollar volume
    sic: int | None
    latest_annual_form: str | None
    latest_annual_accession: str | None  # provenance for staleness
    latest_annual_date: str | None
    # Flags.
    financial_track: bool
    fpi: bool
    dark: bool
    multi_class_check: bool
    # Free-text notes for anything UNKNOWN or worth a human's eye.
    notes: str = ""


@dataclass
class BuildDiagnostics:
    """Everything CP1 needs to report (SPEC 8 CP1)."""

    total_in_master: int = 0
    considered_after_exchange: int = 0
    drop_counts: dict[str, int] = field(default_factory=dict)
    source_failures: dict[str, int] = field(default_factory=dict)  # e.g. no_companyfacts, price_unknown
    kept: int = 0

    def drop(self, reason: str) -> None:
        self.drop_counts[reason] = self.drop_counts.get(reason, 0) + 1

    def fail(self, reason: str) -> None:
        self.source_failures[reason] = self.source_failures.get(reason, 0) + 1


def iter_master(master: dict[str, Any]) -> Iterable[tuple[int, str, str]]:
    """Yield (cik, ticker, exchange) from company_tickers_exchange.json."""
    fields = master["fields"]
    i_cik = fields.index("cik")
    i_ticker = fields.index("ticker")
    i_exch = fields.index("exchange")
    for row in master["data"]:
        exch = row[i_exch]
        yield int(row[i_cik]), str(row[i_ticker]), (str(exch) if exch else "")


def _exchange_kept(exchange: str, params: config.Params) -> bool:
    if not exchange:
        return False
    label = exchange.strip().lower()
    if label in {"otc", "otcqb", "otcqx", "pinx", "grey"}:
        return params.otc_allowed
    return any(label == e.lower() for e in params.exchanges)


def assemble_row(
    cik: int,
    ticker: str,
    exchange: str,
    name: str,
    companyfacts: dict[str, Any] | None,
    submissions: dict[str, Any] | None,
    price: PriceInfo,
    *,
    asof: date,
    params: config.Params | None = None,
) -> UniverseRow:
    """Turn fetched payloads into a fully-annotated universe row (pure)."""
    p = params or config.PARAMS

    shares = sec_parse.latest_shares_outstanding(companyfacts)
    annual = sec_parse.latest_annual_report(submissions, p.annual_forms)
    sic = sec_parse.sic_code(submissions)
    fpi = sec_parse.files_form(submissions, p.fpi_forms)
    dark = sec_parse.is_dark(annual.filing_date, asof, p.dark_after_months)

    notes: list[str] = []

    # Market cap = shares * last close, only if both are known (never guess).
    market_cap: float | None = None
    if shares.value is not None and price.last_close is not None:
        market_cap = shares.value * price.last_close
    else:
        if shares.value is None:
            notes.append("SHARES_UNKNOWN")
        if price.last_close is None:
            notes.append("PRICE_UNKNOWN")

    # Multi-class / dual-class cross-check (SPEC 3.3).
    multi_class = False
    if shares.value and price.yf_shares:
        disc = abs(shares.value - price.yf_shares) / price.yf_shares
        if disc > p.multi_class_discrepancy:
            multi_class = True
            notes.append(
                f"MULTI_CLASS_CHECK: XBRL {shares.value:.0f} vs yfinance "
                f"{price.yf_shares:.0f} ({disc:.0%} apart) — resolve from 10-K cover page"
            )

    if shares.value is None:
        notes.append("shares provenance: none (dei tag absent)")
    if dark:
        notes.append("DARK: latest annual report older than "
                     f"{p.dark_after_months} months — Lane A only")

    return UniverseRow(
        ticker=ticker,
        cik=cik,
        exchange=exchange,
        name=name,
        shares_outstanding=shares.value,
        shares_accession=shares.accession,
        shares_asof=shares.end,
        last_close=price.last_close,
        price_source=price.source,
        price_asof=price.asof,
        market_cap=market_cap,
        adv20=price.adv20,
        sic=sic,
        latest_annual_form=annual.form,
        latest_annual_accession=annual.accession,
        latest_annual_date=annual.filing_date,
        financial_track=sec_parse.is_financial_track(sic),
        fpi=fpi,
        dark=dark,
        multi_class_check=multi_class,
        notes="; ".join(notes),
    )


def build_universe(
    *,
    asof: date | None = None,
    limit: int | None = None,
    refresh: bool = False,
    params: config.Params | None = None,
) -> tuple[list[UniverseRow], BuildDiagnostics]:
    """Fetch, filter, and assemble the universe. Idempotent via the raw cache."""
    p = params or config.PARAMS
    asof = asof or date.today()
    config.ensure_dirs()
    diag = BuildDiagnostics()

    master = sec_edgar.fetch_tickers_exchange(refresh=refresh)
    candidates = list(iter_master(master))
    diag.total_in_master = len(candidates)

    kept: list[UniverseRow] = []
    processed = 0
    for cik, ticker, exchange in candidates:
        # Step 2 — exchange gate (cheapest filter first, before any fetch).
        if not _exchange_kept(exchange, p):
            diag.drop("exchange")
            continue
        diag.considered_after_exchange += 1

        if limit is not None and processed >= limit:
            break
        processed += 1

        submissions = sec_edgar.fetch_submissions(cik, refresh=refresh)
        if submissions is None:
            diag.fail("no_submissions")

        # Structured exclusions (SPEC hard rule 6) — skip before spending price calls.
        sic = sec_parse.sic_code(submissions)
        if sec_parse.is_excluded_sic(sic):
            diag.drop("excluded_sic_6770")
            continue
        if sec_parse.is_china_domiciled(submissions):
            diag.drop("china_domiciled")
            continue

        companyfacts = sec_edgar.fetch_companyfacts(cik, refresh=refresh)
        if companyfacts is None:
            diag.fail("no_companyfacts")

        name = (submissions or {}).get("name") or master_name(master, cik) or ticker
        price = get_price(ticker, refresh=refresh)
        if price.unknown:
            diag.fail("price_unknown")

        row = assemble_row(
            cik, ticker, exchange, name, companyfacts, submissions, price,
            asof=asof, params=p,
        )

        # Step 4 — cap band. Unknown cap cannot enter the band; log and drop.
        if row.market_cap is None:
            diag.drop("cap_unknown")
            continue
        if not (p.cap_min <= row.market_cap <= p.cap_max):
            diag.drop("cap_out_of_band")
            continue

        # Step 5 — ADV floor.
        if row.adv20 is None:
            diag.drop("adv_unknown")
            continue
        if row.adv20 < p.adv_floor:
            diag.drop("adv_below_floor")
            continue

        kept.append(row)

    diag.kept = len(kept)
    return kept, diag


def master_name(master: dict[str, Any], cik: int) -> str | None:
    fields = master["fields"]
    if "name" not in fields:
        return None
    i_cik = fields.index("cik")
    i_name = fields.index("name")
    for row in master["data"]:
        if int(row[i_cik]) == cik:
            return str(row[i_name])
    return None


UNIVERSE_COLUMNS = list(UniverseRow.__dataclass_fields__.keys())


def write_universe_csv(rows: list[UniverseRow], path=None) -> str:
    path = path or (config.OUT_DIR / "universe.csv")
    config.ensure_dirs()
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=UNIVERSE_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))
    return str(path)


def write_universe_duckdb(rows: list[UniverseRow]) -> None:
    """Persist to duckdb (idempotent: table is replaced each build)."""
    import duckdb

    config.ensure_dirs()
    con = duckdb.connect(str(config.DUCKDB_PATH))
    try:
        import pandas as pd

        df = pd.DataFrame([asdict(r) for r in rows]) if rows else pd.DataFrame(columns=UNIVERSE_COLUMNS)
        con.execute("CREATE OR REPLACE TABLE universe AS SELECT * FROM df")
    finally:
        con.close()
