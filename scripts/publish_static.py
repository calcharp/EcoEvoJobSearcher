#!/usr/bin/env python3
"""Scrape job data and publish a static site to docs/ for GitHub Pages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobboards.static_publish import pages_base_path, publish  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish static GitHub Pages site")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs",
        help="Output directory (default: docs/)",
    )
    parser.add_argument(
        "--base-path",
        default=None,
        help="URL prefix for assets (default: auto from GITHUB_REPOSITORY)",
    )
    parser.add_argument(
        "--no-scrape",
        action="store_true",
        help="Reuse existing local database without scraping",
    )
    parser.add_argument(
        "--geocode-limit",
        type=int,
        default=int(__import__("os").environ.get("GEOCODE_LIMIT", "600")),
        help="Max places to geocode this run",
    )
    args = parser.parse_args()

    base = args.base_path if args.base_path is not None else pages_base_path()
    print(f"Publishing to {args.out} (base path: {base})")
    summary = publish(
        args.out,
        base_path=base,
        scrape=not args.no_scrape,
        geocode_limit=args.geocode_limit,
    )
    if summary.get("scrape_warnings"):
        for w in summary["scrape_warnings"]:
            print(f"Warning: {w}")
    print(
        f"Done: {summary['jobs']} jobs, {summary['mapped']} on map -> {summary['out_dir']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
