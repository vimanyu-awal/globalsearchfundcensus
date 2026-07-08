"""Central configuration for the microcap pipeline.

Every tunable parameter from SPEC.md Section 0 lives here so there is exactly
one place to read and one place to change. Values marked TBD in the SPEC keep
the SPEC's stated default and are flagged so the CP1 report can surface them.

Environment overrides (useful for CI and headless runs):
    SEC_USER_AGENT   e.g. "Vim vimanyuawal@gmail.com"  (required by SEC etiquette)
    OTC_ALLOWED      "yes" / "no"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Paths. Everything the pipeline writes lives under the repo, so a fresh clone
# plus a run reproduces state. Raw pulls are cached so re-runs never re-hit
# EDGAR unnecessarily (SPEC hard rule 7).
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OUT_DIR = DATA_DIR / "out"
DUCKDB_PATH = DATA_DIR / "microcap.duckdb"

# --------------------------------------------------------------------------
# SEC fair-access etiquette (SPEC hard rule 7).
# --------------------------------------------------------------------------
# A real, contactable User-Agent is mandatory. Default to the owner's address
# from the SPEC; override via env for other operators or CI.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "Vim vimanyuawal@gmail.com")
# Stay comfortably under SEC's 10 req/s ceiling. 8/s leaves headroom for jitter.
SEC_MAX_REQUESTS_PER_SEC = 8.0
SEC_TIMEOUT_SECONDS = 30
SEC_MAX_RETRIES = 4  # network errors only, with exponential backoff

# SEC endpoints used in Phase 1.
TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"


def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class Params:
    """SPEC Section 0 parameters."""

    # Size band (USD).
    cap_min: float = 5_000_000
    cap_max: float = 100_000_000

    # 20-day average daily *dollar* volume floor.
    adv_floor: float = 50_000

    # Exchanges to keep. Matched case-insensitively against the exchange label
    # in company_tickers_exchange.json ("NYSE", "Nasdaq", "NYSE American",
    # historically also "NYSEArca"/"OTC").
    exchanges: tuple[str, ...] = ("NYSE", "Nasdaq", "NYSE American")

    # TBD in SPEC — assume NO until compliance confirms (SPEC 0).
    otc_allowed: bool = field(default_factory=lambda: _bool_env("OTC_ALLOWED", False))

    # Staleness: latest annual report older than this many months => DARK.
    dark_after_months: int = 15

    # Shares-outstanding cross-check tolerance (SPEC 3.3).
    multi_class_discrepancy: float = 0.10  # >10% => MULTI_CLASS_CHECK

    # Annual-report form types that reset the staleness clock.
    annual_forms: tuple[str, ...] = ("10-K", "10-K/A", "20-F", "20-F/A")

    # Foreign-private-issuer marker: files 20-F (SPEC: FPI included, flagged).
    fpi_forms: tuple[str, ...] = ("20-F", "20-F/A")

    # Exclusions we can detect from structured data in Phase 1 (SPEC hard rule 6).
    # SIC 6770 = blank checks / SPACs.
    excluded_sic: tuple[int, ...] = (6770,)
    # Financials are NOT excluded; they route to the financial-metrics track.
    financial_sic_lo: int = 6000
    financial_sic_hi: int = 6799
    # Country codes (SEC business-address stateOrCountry) treated as China-domiciled.
    china_country_codes: tuple[str, ...] = ("CHINA", "F4", "HONG KONG", "K3")


PARAMS = Params()


def cap_bucket(cap: float) -> str:
    """Coarse market-cap bucket for CP1 distribution reporting."""
    if cap < 10_000_000:
        return "5-10M"
    if cap < 25_000_000:
        return "10-25M"
    if cap < 50_000_000:
        return "25-50M"
    if cap < 100_000_000:
        return "50-100M"
    return "100M+"


def ensure_dirs() -> None:
    for d in (DATA_DIR, RAW_DIR, OUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
