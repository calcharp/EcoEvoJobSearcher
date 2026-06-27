"""Build a static site bundle for GitHub Pages."""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jobboards.db import init_db, job_date_bounds, job_stats, list_jobs
from jobboards.config import ci_skip_geocode, is_github_actions, science_careers_fetch_details
from jobboards.dates import days_until, format_display
from jobboards.preview import can_preview, preview_target
from jobboards.geocode import (
    get_job_geo,
    get_place_map_status,
    import_geo_cache,
    list_map_jobs,
    map_coverage_summary,
    run_geocode_all,
)
from jobboards.notes import parse_notes_thread
from jobboards.scrape.runner import ScrapeState, scrape_all
from jobboards.subjects import subject_term_counts

ROOT = Path(__file__).resolve().parent.parent
GEO_CACHE_SEED = ROOT / "data" / "geo-cache.json"


def pages_base_path() -> str:
    if os.environ.get("GITHUB_ACTIONS"):
        repo = os.environ.get("GITHUB_REPOSITORY", "calcharp/EcoEvoJobSearcher")
        name = repo.split("/", 1)[-1]
        return f"/{name}/"
    return "./"


def enrich_export_job(job: dict[str, Any], include_detail: bool = False) -> dict[str, Any]:
    job = dict(job)
    job["posted_display"] = format_display(job.get("posted_at"), include_time=True)
    job["apply_display"] = format_display(job.get("apply_by"))
    job["updated_display"] = format_display(job.get("updated_at"), include_time=True)
    job["days_until"] = days_until(job.get("apply_by"))

    notes_raw = job.get("notes_raw") or ""
    thread_json = job.get("notes_thread_json")
    if thread_json:
        try:
            job["notes_thread"] = json.loads(thread_json)
        except json.JSONDecodeError:
            job["notes_thread"] = parse_notes_thread(notes_raw)
    else:
        job["notes_thread"] = parse_notes_thread(notes_raw)
    job["has_notes_thread"] = len(job["notes_thread"]) > 1

    geo = get_job_geo(job.get("institution", ""), job.get("location"))
    job["map_status"] = get_place_map_status(
        job.get("institution", ""), job.get("location")
    )
    if geo:
        job["map_geo"] = {
            "id": job["id"],
            "institution": job.get("institution"),
            "location": job.get("location"),
            "subject_area": job.get("subject_area"),
            "lat": geo["lat"],
            "lon": geo["lon"],
            "geo_precision": geo["geo_precision"],
        }

    if include_detail:
        _, open_url = preview_target(job)
        job["preview_open_url"] = open_url
        job["has_preview"] = can_preview(job)
    else:
        job.pop("description_raw", None)
        job.pop("notes_raw", None)
        job.pop("notes_thread_json", None)

    return job


def geocode_pending_loop(max_places: int | None = None) -> int:
    return run_geocode_all(max_total=max_places)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def copy_static_assets(out_dir: Path) -> None:
    src = ROOT / "static"
    dst = out_dir / "static"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def render_site_pages(out_dir: Path, base_path: str, stats: dict[str, Any]) -> None:
  from jinja2 import Environment, FileSystemLoader, select_autoescape

  env = Environment(
      loader=FileSystemLoader(str(ROOT / "templates" / "static_site")),
      autoescape=select_autoescape(["html", "xml"]),
  )
  env.globals["base_path"] = base_path
  env.globals["stats"] = stats

  pages = {
      "index.html": env.get_template("index.html").render(active_page="index", stats=stats),
      "subjects.html": env.get_template("subjects.html").render(active_page="subjects", stats=stats),
      "job.html": env.get_template("job.html").render(active_page="job", stats=stats),
      "404.html": env.get_template("404.html").render(active_page="", stats=stats),
  }
  for name, html in pages.items():
      (out_dir / name).write_text(html, encoding="utf-8")


def publish(
    out_dir: Path,
    *,
    base_path: str | None = None,
    scrape: bool = True,
    geocode_limit: int | None = None,
) -> dict[str, Any]:
    base_path = base_path if base_path is not None else pages_base_path()
    out_dir = out_dir.resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    init_db()
    t0 = time.monotonic()

    if GEO_CACHE_SEED.is_file():
        imported = import_geo_cache(GEO_CACHE_SEED)
        if imported:
            print(f"Imported {imported} geocode entries from {GEO_CACHE_SEED.name}")

    scrape_warnings: list[str] = []
    if scrape:
        if is_github_actions():
            mode = "listings-only Science Careers" if not science_careers_fetch_details() else "full scrape"
            print(f"CI scrape mode: {mode}")
        state = ScrapeState()
        started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        state.update(phase="starting", message="Scraping sources…", started_at=started)
        scrape_all(state)
        scrape_warnings = list(state.warnings or [])
        if state.phase == "error" or job_stats().get("total", 0) == 0:
            raise RuntimeError(state.error or "Scrape failed with no jobs")
        print(f"Scrape finished in {time.monotonic() - t0:.1f}s")

    if geocode_limit is None and ci_skip_geocode():
        geocode_limit = 0
    if geocode_limit != 0:
        geo_t0 = time.monotonic()
        geocode_pending_loop(geocode_limit)
        print(f"Geocoded pending places in {time.monotonic() - geo_t0:.1f}s")
    elif is_github_actions():
        print("Skipping geocode on CI (using committed geo-cache.json)")

    all_jobs = list_jobs(sort="posted_at", order="desc")
    export_jobs = [enrich_export_job(job, include_detail=True) for job in all_jobs]

    mapped, missing = list_map_jobs(sort="posted_at", order="desc")
    geo_summary = map_coverage_summary()
    stats = job_stats()
    bounds = job_date_bounds()
    terms = subject_term_counts(min_count=2)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    data_dir = out_dir / "data"
    write_json(data_dir / "meta.json", {
        "generated_at": generated_at,
        "last_fetched_at": stats.get("last_fetched_at"),
        "stats": stats,
        "map_summary": {
            "mapped": len(mapped),
            "missing": missing,
            "filtered_total": len(all_jobs),
            **geo_summary,
        },
        "scrape_warnings": scrape_warnings,
    })
    write_json(data_dir / "jobs.json", {"jobs": export_jobs, "stats": stats})
    jobs_dir = data_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    for job in export_jobs:
        write_json(jobs_dir / f"{job['id']}.json", job)
    write_json(data_dir / "map-jobs.json", {
        "jobs": mapped,
        "mapped": len(mapped),
        "missing": missing,
        "filtered_total": len(all_jobs),
        "geo_summary": geo_summary,
    })
    write_json(data_dir / "date-bounds.json", bounds)
    write_json(data_dir / "subject-cloud.json", {
        "terms": terms,
        "total_jobs": stats.get("total", 0),
    })

    copy_static_assets(out_dir)
    render_site_pages(out_dir, base_path, stats)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    print(f"Publish finished in {time.monotonic() - t0:.1f}s total")

    return {
        "out_dir": str(out_dir),
        "base_path": base_path,
        "jobs": len(export_jobs),
        "mapped": len(mapped),
        "generated_at": generated_at,
        "scrape_warnings": scrape_warnings,
    }
