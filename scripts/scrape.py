#!/usr/bin/env python3
"""Scrape all job listings from ecoevojobs, EvolDir, and Science Careers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobboards.db import init_db, job_stats  # noqa: E402
from jobboards.scrape.runner import ScrapeState, scrape_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape all three job boards into jobs.db")
    parser.add_argument(
        "--skip-evoldir",
        action="store_true",
        help="Skip EvolDir (faster; not recommended)",
    )
    args = parser.parse_args()

    init_db()
    state = ScrapeState()
    print("Scraping ecoevojobs, EvolDir, and Science Careers…")
    scrape_all(state, skip_evoldir=args.skip_evoldir)

    snap = state.snapshot()
    stats = job_stats()
    print()
    print(f"ecoevojobs:       {snap['ecoevo_count']}")
    print(f"EvolDir:          {snap['evoldir_count']}")
    print(f"Science Careers:  {snap['sciencecareers_count']}")
    print(f"Total in database: {stats['total']}")
    if snap.get("warnings"):
        for w in snap["warnings"]:
            print(f"Warning: {w}")
        return 1
    if snap.get("phase") == "error":
        print(f"Error: {snap.get('error')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
