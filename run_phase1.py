#!/usr/bin/env python3
"""Phase 1 runner — build the microcap universe and print the CP1 report.

Usage:
    python run_phase1.py                 # full run (needs SEC EDGAR reachable)
    python run_phase1.py --limit 200     # smoke test on the first 200 candidates
    python run_phase1.py --refresh       # ignore cache, re-pull raw data

Outputs:
    data/out/universe.csv        one row per name, provenance on every number
    data/out/CP1_REPORT.txt      the checkpoint report (also printed to stdout)
    data/microcap.duckdb         `universe` table

Research only. This script never trades and never connects to a brokerage.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from microcap import config
from microcap.universe import build_universe, write_universe_csv, write_universe_duckdb
from microcap.report import cp1_report


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Phase 1 microcap universe.")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap the number of on-exchange candidates processed (smoke test).")
    ap.add_argument("--refresh", action="store_true", help="ignore the raw cache and re-pull.")
    args = ap.parse_args()

    asof = date.today()
    print(f"Building universe as of {asof.isoformat()} "
          f"(User-Agent: {config.SEC_USER_AGENT}) ...", file=sys.stderr)

    try:
        rows, diag = build_universe(asof=asof, limit=args.limit, refresh=args.refresh)
    except PermissionError as exc:
        print(f"\nDATA-SOURCE BLOCKED: {exc}\n"
              "Phase 1 cannot complete where SEC EDGAR egress is denied. "
              "Run in an environment that allows www.sec.gov and data.sec.gov.",
              file=sys.stderr)
        return 2

    csv_path = write_universe_csv(rows)
    write_universe_duckdb(rows)

    report = cp1_report(rows, diag, asof)
    print(report)

    report_path = config.OUT_DIR / "CP1_REPORT.txt"
    report_path.write_text(report + "\n")
    print(f"\nwrote {csv_path}\nwrote {report_path}\nwrote {config.DUCKDB_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
