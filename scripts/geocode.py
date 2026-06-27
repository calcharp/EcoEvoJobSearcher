#!/usr/bin/env python3
"""Geocode job locations locally and export a seed file for GitHub Actions."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobboards.db import init_db, job_stats  # noqa: E402
from jobboards.geocode import (  # noqa: E402
    export_geo_cache,
    geo_stats,
    import_geo_cache,
    repair_geo_cache_location_fallbacks,
    run_geocode_all,
    run_geocode_retry_all,
)
from jobboards.scrape.runner import ScrapeState, scrape_all  # noqa: E402

DEFAULT_EXPORT = ROOT / "data" / "geo-cache.json"


def _print_stats(label: str) -> None:
    stats = geo_stats()
    print(
        f"{label}: {stats['cached']} mapped, "
        f"{stats['failed']} failed, "
        f"{stats['pending']} not yet tried "
        f"(of {stats['total_places']} unique places)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Geocode institutions locally and export data/geo-cache.json for CI"
    )
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Scrape job sources before geocoding (uses your local jobs.db)",
    )
    parser.add_argument(
        "--repair-fallbacks",
        action="store_true",
        help="Copy coordinates from mapped places that share the same normalized location",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry places that failed geocoding on a previous run",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Skip geocoding; only write data/geo-cache.json from the current database",
    )
    parser.add_argument(
        "--export",
        nargs="?",
        const=str(DEFAULT_EXPORT),
        metavar="PATH",
        help=f"Export geo cache after geocoding (default: {DEFAULT_EXPORT})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max places to geocode this run (default: all pending)",
    )
    args = parser.parse_args()

    export_path = args.export or (
        str(DEFAULT_EXPORT) if args.export_only or args.repair_fallbacks else None
    )
    run_geocode = not args.export_only and not args.repair_fallbacks

    init_db()

    if args.repair_fallbacks and not Path(DEFAULT_EXPORT).is_file():
        print(f"Missing seed file: {DEFAULT_EXPORT}", file=sys.stderr)
        return 1

    if args.repair_fallbacks:
        imported = import_geo_cache(DEFAULT_EXPORT)
        if imported:
            print(f"Loaded {imported} geo cache entries from {DEFAULT_EXPORT}")

    if args.scrape:
        print("Scraping sources…")
        state = ScrapeState()
        scrape_all(state)
        if state.warnings:
            for w in state.warnings:
                print(f"Warning: {w}")
        if state.phase == "error":
            print(f"Scrape error: {state.error}", file=sys.stderr)
            return 1
        print(f"Scraped {job_stats().get('total', 0)} jobs")

    _print_stats("Before")

    started = time.monotonic()
    total = 0

    if run_geocode:
        if args.retry_failed:
            retried = run_geocode_retry_all(max_total=args.limit)
            total += retried
            if retried:
                print(f"Retried {retried} previously failed place(s)")

        remaining = None if args.limit is None else max(args.limit - total, 0)
        if remaining != 0:
            geocoded = run_geocode_all(max_total=remaining)
            total += geocoded
            if geocoded:
                print(f"Geocoded {geocoded} new place(s)")

        elapsed = time.monotonic() - started
        if total:
            print(f"Done in {elapsed:.1f}s ({total / elapsed:.1f} places/s)")

        _print_stats("After")

    if args.repair_fallbacks:
        fixed = repair_geo_cache_location_fallbacks()
        if fixed:
            print(f"Repaired {fixed} place(s) via location fallback")
        _print_stats("After repair")

    if export_path:
        out = Path(export_path)
        count = export_geo_cache(out)
        print(f"Exported {count} entries -> {out}")
        if run_geocode or args.repair_fallbacks:
            print("Commit data/geo-cache.json so GitHub Actions can skip bulk geocoding.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
