"""Pure parsing of SEC JSON payloads into the fields Phase 1 needs.

Kept free of network I/O so it can be unit-tested on synthetic fixtures. Every
extracted number carries its provenance (the XBRL tag + accession, or the
filing form + accession + date) per SPEC hard rule 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from . import config


@dataclass
class SharesOutstanding:
    value: float | None          # share count, or None => UNKNOWN
    end: str | None              # "as of" date of the measurement
    accession: str | None        # provenance: accession number of the filing
    form: str | None             # provenance: form the value came from


@dataclass
class LatestAnnual:
    form: str | None
    accession: str | None
    filing_date: str | None      # ISO date the annual report was filed


def latest_shares_outstanding(companyfacts: dict[str, Any] | None) -> SharesOutstanding:
    """Most recent dei:EntityCommonStockSharesOutstanding (SPEC 3.3).

    Chooses the entry with the latest "end" date; ties broken by latest filing.
    Sums concurrent entries sharing the same end date (multi-class cover pages
    report one row per class) so the cross-check against a consolidated
    yfinance figure is apples-to-apples.
    """
    unknown = SharesOutstanding(None, None, None, None)
    if not companyfacts:
        return unknown
    try:
        units = companyfacts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]
    except (KeyError, TypeError):
        return unknown

    entries: list[dict[str, Any]] = []
    for unit_key, rows in units.items():  # unit_key is typically "shares"
        for row in rows:
            if row.get("val") is None or not row.get("end"):
                continue
            entries.append(row)
    if not entries:
        return unknown

    latest_end = max(e["end"] for e in entries)
    same_end = [e for e in entries if e["end"] == latest_end]
    # Among rows sharing that end date, the newest filing wins for provenance.
    same_end.sort(key=lambda e: (e.get("filed", ""), e.get("accn", "")))
    winner = same_end[-1]
    total = float(sum(float(e["val"]) for e in same_end))
    return SharesOutstanding(
        value=total,
        end=latest_end,
        accession=winner.get("accn"),
        form=winner.get("form"),
    )


def latest_annual_report(submissions: dict[str, Any] | None,
                         annual_forms: tuple[str, ...] | None = None) -> LatestAnnual:
    """Most recent 10-K / 20-F (or amendment) from the submissions history."""
    forms_wanted = annual_forms or config.PARAMS.annual_forms
    empty = LatestAnnual(None, None, None)
    if not submissions:
        return empty
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accns = recent.get("accessionNumber", [])
    best: LatestAnnual | None = None
    for form, fdate, accn in zip(forms, dates, accns):
        if form in forms_wanted:
            if best is None or fdate > (best.filing_date or ""):
                best = LatestAnnual(form=form, accession=accn, filing_date=fdate)
    return best or empty


def files_form(submissions: dict[str, Any] | None, wanted: tuple[str, ...]) -> bool:
    """True if the issuer's recent history contains any of `wanted` forms."""
    if not submissions:
        return False
    forms = submissions.get("filings", {}).get("recent", {}).get("form", [])
    wanted_set = set(wanted)
    return any(f in wanted_set for f in forms)


def sic_code(submissions: dict[str, Any] | None) -> int | None:
    if not submissions:
        return None
    raw = submissions.get("sic")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def business_country(submissions: dict[str, Any] | None) -> str | None:
    """Business-address country/state code, upper-cased (for domicile checks)."""
    if not submissions:
        return None
    addr = submissions.get("addresses", {}).get("business", {})
    code = addr.get("stateOrCountry")
    return code.upper() if isinstance(code, str) else None


def is_financial_track(sic: int | None) -> bool:
    p = config.PARAMS
    return sic is not None and p.financial_sic_lo <= sic <= p.financial_sic_hi


def is_excluded_sic(sic: int | None) -> bool:
    return sic in set(config.PARAMS.excluded_sic)


def is_china_domiciled(submissions: dict[str, Any] | None) -> bool:
    country = business_country(submissions)
    return country in set(config.PARAMS.china_country_codes)


def is_dark(filing_date: str | None, asof: date, months: int) -> bool:
    """True if the latest annual report is older than `months` (SPEC 3.6)."""
    if not filing_date:
        return True  # no annual report on record => treat as dark
    try:
        y, m, d = (int(x) for x in filing_date.split("-"))
    except (ValueError, AttributeError):
        return True
    age_months = (asof.year - y) * 12 + (asof.month - m)
    if asof.day < d:
        age_months -= 1
    return age_months > months
