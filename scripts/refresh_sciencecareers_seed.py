"""Refresh the committed Science Careers seed from a live scrape.

GitHub Actions IPs are often blocked (HTTP 403) by Science Careers / CloudFront.
Run this on a residential network, then commit the updated seed so CI stays fresh:

  python scripts/refresh_sciencecareers_seed.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jobboards.db import connect, init_db, purge_stale
from jobboards.scrape.sciencecareers import (
    SCIENCE_CAREERS_SEED,
    export_sciencecareers_seed,
    scrape_sciencecareers,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--listings-only",
        action="store_true",
        help="Skip detail pages (faster; weaker deadlines/descriptions).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=SCIENCE_CAREERS_SEED,
        help=f"Seed path (default: {SCIENCE_CAREERS_SEED})",
    )
    args = parser.parse_args()

    if args.listings_only:
        import os

        os.environ["SCIENCE_CAREERS_FETCH_DETAILS"] = "0"

    init_db()
    scraped_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    print(f"Scraping Science Careers at {scraped_at}…")
    with connect() as conn:
        count = scrape_sciencecareers(conn, scraped_at=scraped_at)
        purge_stale(conn, "sciencecareers", scraped_at)
        written = export_sciencecareers_seed(conn, args.out)
    print(f"Scraped {count} listings; wrote {written} jobs to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
