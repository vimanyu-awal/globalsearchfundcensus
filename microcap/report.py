"""Checkpoint 1 report (SPEC Section 8, CP1).

Emits: counts by exchange and cap bucket, 10 sample rows, and any data-source
failures. Pure text so it can be printed to stdout and committed to a file.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from . import config
from .universe import UniverseRow, BuildDiagnostics


def _fmt_money(x: float | None) -> str:
    if x is None:
        return "UNKNOWN"
    if x >= 1_000_000:
        return f"${x/1_000_000:.1f}M"
    if x >= 1_000:
        return f"${x/1_000:.0f}K"
    return f"${x:.0f}"


def cp1_report(rows: list[UniverseRow], diag: BuildDiagnostics, asof: date) -> str:
    p = config.PARAMS
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("CHECKPOINT 1 — PHASE 1 UNIVERSE")
    lines.append(f"as of {asof.isoformat()}  |  OTC_ALLOWED={p.otc_allowed}  "
                 f"cap band {_fmt_money(p.cap_min)}–{_fmt_money(p.cap_max)}  "
                 f"ADV floor {_fmt_money(p.adv_floor)}")
    lines.append("=" * 70)

    lines.append("")
    lines.append("PIPELINE FUNNEL")
    lines.append(f"  names in master map ............ {diag.total_in_master}")
    lines.append(f"  on target exchanges ............ {diag.considered_after_exchange}")
    lines.append(f"  KEPT in universe ............... {diag.kept}")

    lines.append("")
    lines.append("DROPS BY REASON")
    if diag.drop_counts:
        for reason, n in sorted(diag.drop_counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {reason:.<32} {n}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("COUNTS BY EXCHANGE (kept)")
    exch = Counter(r.exchange for r in rows)
    for name, n in sorted(exch.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {name:.<32} {n}")
    if not exch:
        lines.append("  (none)")

    lines.append("")
    lines.append("COUNTS BY CAP BUCKET (kept)")
    buckets = Counter(config.cap_bucket(r.market_cap) for r in rows if r.market_cap is not None)
    for b in ("5-10M", "10-25M", "25-50M", "50-100M"):
        lines.append(f"  {b:.<32} {buckets.get(b, 0)}")

    lines.append("")
    lines.append("FLAG TALLIES (kept)")
    lines.append(f"  financial-track ................ {sum(r.financial_track for r in rows)}")
    lines.append(f"  FPI (20-F filers) .............. {sum(r.fpi for r in rows)}")
    lines.append(f"  DARK (stale annual) ............ {sum(r.dark for r in rows)}")
    lines.append(f"  MULTI_CLASS_CHECK .............. {sum(r.multi_class_check for r in rows)}")

    lines.append("")
    lines.append("DATA-SOURCE FAILURES")
    if diag.source_failures:
        for reason, n in sorted(diag.source_failures.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {reason:.<32} {n}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("10 SAMPLE ROWS")
    header = f"  {'TICKER':<8}{'EXCH':<14}{'CAP':>9}  {'ADV20':>9}  {'SIC':>5}  FLAGS"
    lines.append(header)
    for r in rows[:10]:
        flags = "".join([
            "F" if r.financial_track else "-",
            "I" if r.fpi else "-",
            "D" if r.dark else "-",
            "M" if r.multi_class_check else "-",
        ])
        lines.append(
            f"  {r.ticker:<8}{r.exchange:<14}{_fmt_money(r.market_cap):>9}  "
            f"{_fmt_money(r.adv20):>9}  {str(r.sic or ''):>5}  {flags}"
        )
    if not rows:
        lines.append("  (universe empty — see data-source failures above)")
    lines.append("  flags: F=financial-track I=FPI D=dark M=multi-class-check")

    lines.append("")
    lines.append("STOP — awaiting explicit OK to proceed to Phase 2 (SPEC checkpoint rule).")
    lines.append("=" * 70)
    return "\n".join(lines)
