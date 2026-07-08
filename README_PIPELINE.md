# Microcap Deep-Value Pipeline

Research-only system that reads the US microcap universe and surfaces deep-value
names in three lanes (net-nets, special situations, ignored compounders). Full
design in **SPEC.md**. **This system never trades, never connects to a
brokerage, and never asserts compliance.**

Build is checkpoint-gated (SPEC §8). **Phase 1 (universe) is implemented; the
pipeline stops at Checkpoint 1 and waits for explicit sign-off before Phase 2.**

## Layout

```
microcap/
  config.py      SPEC §0 parameters (one place to read/change), paths, SEC User-Agent
  sec_edgar.py   rate-limited (<10 req/s), cached SEC client; provenance-friendly
  sec_parse.py   pure parsing of SEC JSON -> shares, latest annual, SIC, FPI, domicile
  prices.py      the one fragile dependency, isolated: yfinance -> Stooq -> PRICE_UNKNOWN
  universe.py    Phase 1 build: filter, assemble, write universe.csv + duckdb
  report.py      Checkpoint-1 report (counts, cap buckets, samples, failures)
run_phase1.py    CLI entry point
tests/           offline unit + integration tests (no network required)
```

## Run Phase 1

```bash
pip install -r requirements.txt
export SEC_USER_AGENT="Vim vimanyuawal@gmail.com"   # required by SEC etiquette
python run_phase1.py                 # full universe (needs SEC EDGAR reachable)
python run_phase1.py --limit 200     # smoke test on first 200 on-exchange names
```

Outputs (git-ignored, under `data/`):
- `data/out/universe.csv` — one row per name, **provenance on every number**
- `data/out/CP1_REPORT.txt` — the checkpoint report (also printed to stdout)
- `data/microcap.duckdb` — `universe` table
- `data/raw/…` — cached raw pulls so re-runs never re-hit EDGAR unnecessarily

Re-runs are **idempotent**: cached raw pulls are reused; the universe table is
replaced, not duplicated.

## Offline tests

```bash
python tests/test_phase1_offline.py   # or: pytest tests/
```

These stub every network call with synthetic fixtures and verify the filtering,
provenance, multi-class cross-check, dark-name, and exclusion logic without
touching the network.

## What Phase 1 does (SPEC §3)

1. Pull `company_tickers_exchange.json`; keep NYSE / Nasdaq / NYSE American
   (drop OTC unless `OTC_ALLOWED=yes`).
2. Shares outstanding from XBRL `dei:EntityCommonStockSharesOutstanding`,
   cross-checked against yfinance — >10% apart flags `MULTI_CLASS_CHECK`.
3. Market cap = shares × latest close; keep `CAP_MIN..CAP_MAX`.
4. ADV(20d) dollar volume; drop below `ADV_FLOOR`.
5. Latest 10-K/20-F older than 15 months → `DARK` (kept, loudly flagged;
   permitted in Lane A only downstream).
6. Structured exclusions applied here: SIC 6770 blank-checks/SPACs, and
   China-domiciled issuers (by SEC business-address country). VIE detection is
   a text check deferred to Phase 2.

Every figure carries its source (XBRL accession, filing accession + date, or
price source). Missing data is surfaced as `UNKNOWN` / `PRICE_UNKNOWN` /
`SHARES_UNKNOWN` — never silently estimated.

## Environment note

Phase 1 requires outbound access to `www.sec.gov`, `data.sec.gov`, and a price
source (Yahoo/Stooq). In network-restricted environments those hosts may be
blocked by egress policy; the runner detects this and exits with a clear
message rather than producing partial data. Run the full universe where EDGAR
is reachable.
