import os
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from flask import Flask, Response, jsonify, render_template, request, redirect

from jobboards.config import HEARTBEAT_TIMEOUT_SEC, static_dir, templates_dir
from jobboards.dates import days_until, format_display
from jobboards.db import get_job, init_db, job_date_bounds, job_stats, list_jobs
from jobboards.embed import can_preview, preview_target, render_preview
from jobboards.geocode import geo_stats, get_job_geo, list_map_jobs
from jobboards.scrape.runner import ScrapeState, build_progress_detail, compute_progress_percent, run_scrape_async
from jobboards.user_data import (
    attach_user_flags,
    delete_saved_search,
    dismiss_job,
    list_saved_searches,
    restore_job,
    save_job,
    save_search,
    unsave_job,
    user_data_snapshot,
)


def enrich_job(job: dict) -> dict:
    job["posted_display"] = format_display(job.get("posted_at"), include_time=True)
    job["apply_display"] = format_display(job.get("apply_by"))
    job["updated_display"] = format_display(job.get("updated_at"), include_time=True)
    job["days_until"] = days_until(job.get("apply_by"))
    return job

_last_seen = time.time()
_shutdown_at: Optional[float] = None
_lifecycle_lock = threading.Lock()

SHUTDOWN_GRACE_SEC = 3.0


def _parse_bbox(raw: Optional[str]) -> Optional[tuple[float, float, float, float]]:
    if not raw:
        return None
    try:
        parts = [float(x.strip()) for x in raw.split(",")]
        if len(parts) != 4:
            return None
        return (parts[0], parts[1], parts[2], parts[3])
    except ValueError:
        return None


def _parse_date_range(req) -> Optional[dict[str, str]]:
    field = (req.args.get("date_field") or "posted_at").strip()
    if field not in {"posted_at", "apply_by"}:
        field = "posted_at"
    date_from = (req.args.get("from") or "").strip() or None
    date_to = (req.args.get("to") or "").strip() or None
    if not date_from and not date_to:
        return None
    return {"field": field, "from": date_from or "", "to": date_to or ""}


def _date_filter_label(date_range: dict[str, str]) -> str:
    field_label = "Posted" if date_range["field"] == "posted_at" else "Apply by"
    start = date_range.get("from") or "…"
    end = date_range.get("to") or "…"
    return f"{field_label}: {start} – {end}"


def _parse_view(req) -> str:
    view = (req.args.get("view") or "all").strip().lower()
    if view in {"saved", "dismissed"}:
        return view
    return "all"


def _parse_job_filters(req) -> tuple[Optional[list[str]], Optional[tuple[float, float, float, float]], Optional[dict[str, str]]]:
    terms = [t.strip() for t in req.args.getlist("q") if t.strip()]
    terms.extend(t.strip() for t in req.args.getlist("kw") if t.strip())
    bbox = _parse_bbox(req.args.get("bbox"))
    date_range = _parse_date_range(req)
    return (terms or None, bbox, date_range)


def _initial_filters(req) -> list[dict]:
    filters: list[dict] = []
    for term in req.args.getlist("q"):
        t = term.strip()
        if t:
            filters.append({"type": "search", "value": t, "label": t})
    for term in req.args.getlist("kw"):
        t = term.strip()
        if t:
            filters.append({"type": "keyword", "value": t, "label": t})
    bbox = _parse_bbox(req.args.get("bbox"))
    if bbox:
        filters.append({
            "type": "area",
            "label": "Map area",
            "bounds": {
                "south": bbox[0],
                "west": bbox[1],
                "north": bbox[2],
                "east": bbox[3],
            },
        })
    date_range = _parse_date_range(req)
    if date_range:
        filters.append({
            "type": "date",
            "field": date_range["field"],
            "from": date_range.get("from") or "",
            "to": date_range.get("to") or "",
            "label": _date_filter_label(date_range),
        })
    return filters


def touch_heartbeat():
    global _last_seen, _shutdown_at
    with _lifecycle_lock:
        _last_seen = time.time()
        _shutdown_at = None


def request_shutdown():
    global _shutdown_at
    with _lifecycle_lock:
        _shutdown_at = time.time() + SHUTDOWN_GRACE_SEC


def start_watchdog():
    def _watch():
        while True:
            time.sleep(1)
            with _lifecycle_lock:
                if _shutdown_at and time.time() >= _shutdown_at:
                    os._exit(0)
                if time.time() - _last_seen > HEARTBEAT_TIMEOUT_SEC:
                    os._exit(0)

    threading.Thread(target=_watch, daemon=True).start()


def create_app(scrape_state: Optional[ScrapeState] = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(templates_dir()),
        static_folder=str(static_dir()),
    )
    state = scrape_state or ScrapeState()

    with state._lock:
        if state.cached_stats is None:
            state.cached_stats = job_stats()

    @app.before_request
    def _touch():
        if request.path.startswith("/api/heartbeat"):
            return
        touch_heartbeat()

    @app.route("/")
    def index():
        stats = job_stats()
        terms, _bbox, date_range = _parse_job_filters(request)
        if stats["total"]:
            preview_jobs = [
                enrich_job(j)
                for j in list_jobs(
                    limit=120,
                    sort="posted_at",
                    order="desc",
                    terms=terms,
                    date_field=date_range["field"] if date_range else None,
                    date_from=date_range.get("from") or None if date_range else None,
                    date_to=date_range.get("to") or None if date_range else None,
                    view=_parse_view(request),
                )
            ]
            attach_user_flags(preview_jobs)
        else:
            preview_jobs = []
        return render_template(
            "index.html",
            stats=stats,
            preview_jobs=preview_jobs,
            initial_filters=_initial_filters(request),
        )

    @app.route("/subjects")
    def subject_cloud():
        terms = subject_term_counts(min_count=2)
        stats = job_stats()
        return render_template(
            "cloud.html",
            terms=terms,
            total_jobs=stats["total"],
            prefs=get_phrase_prefs(),
        )

    @app.route("/api/subject-cloud")
    def api_subject_cloud():
        min_count = request.args.get("min", 2, type=int)
        return jsonify({"terms": subject_term_counts(min_count=max(1, min_count))})

    @app.route("/api/subject-phrases", methods=["GET", "POST"])
    def api_subject_phrases():
        if request.method == "GET":
            return jsonify(get_phrase_prefs())

        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "").strip()
        phrase = (data.get("phrase") or "").strip()
        try:
            prefs = update_phrase_prefs(action, phrase)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        stats = job_stats()
        return jsonify({
            "prefs": prefs,
            "terms": subject_term_counts(min_count=2),
            "total_jobs": stats["total"],
        })

    @app.route("/map")
    def map_page():
        qs = request.query_string.decode()
        return redirect("/" + ("?" + qs if qs else ""))

    @app.route("/api/user-data")
    def api_user_data():
        return jsonify(user_data_snapshot())

    @app.route("/api/saved-jobs", methods=["POST"])
    def api_saved_jobs():
        data = request.get_json(silent=True) or {}
        job_id = (data.get("job_id") or "").strip()
        action = (data.get("action") or "").strip()
        if not job_id:
            return jsonify({"error": "job_id required"}), 400
        if action == "save":
            save_job(job_id)
        elif action == "unsave":
            unsave_job(job_id)
        else:
            return jsonify({"error": "action must be save or unsave"}), 400
        return jsonify(user_data_snapshot())

    @app.route("/api/dismissed-jobs", methods=["POST"])
    def api_dismissed_jobs():
        data = request.get_json(silent=True) or {}
        job_id = (data.get("job_id") or "").strip()
        action = (data.get("action") or "").strip()
        if not job_id:
            return jsonify({"error": "job_id required"}), 400
        if action == "dismiss":
            dismiss_job(job_id)
        elif action == "restore":
            restore_job(job_id)
        else:
            return jsonify({"error": "action must be dismiss or restore"}), 400
        return jsonify(user_data_snapshot())

    @app.route("/api/saved-searches", methods=["GET", "POST"])
    def api_saved_searches():
        if request.method == "GET":
            return jsonify({"searches": list_saved_searches()})

        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "save").strip()
        if action == "save":
            try:
                item = save_search(data.get("name") or "", data.get("payload") or {})
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            return jsonify({"search": item, **user_data_snapshot()})
        if action == "delete":
            search_id = (data.get("id") or "").strip()
            if not search_id:
                return jsonify({"error": "id required"}), 400
            delete_saved_search(search_id)
            return jsonify(user_data_snapshot())
        return jsonify({"error": "unknown action"}), 400

    @app.route("/api/date-bounds")
    def api_date_bounds():
        return jsonify(job_date_bounds())

    @app.route("/api/map-jobs")
    def api_map_jobs():
        source = request.args.get("source", "all")
        terms, bbox, date_range = _parse_job_filters(request)
        sort = request.args.get("sort", "posted_at")
        order = request.args.get("order", "desc")
        jobs, missing = list_map_jobs(
            source=source,
            terms=terms,
            sort=sort,
            order=order,
            bbox=bbox,
            date_field=date_range["field"] if date_range else None,
            date_from=date_range.get("from") or None if date_range else None,
            date_to=date_range.get("to") or None if date_range else None,
            view=_parse_view(request),
        )
        return jsonify({
            "jobs": jobs,
            "mapped": len(jobs),
            "missing": missing,
            "geo": geo_stats(),
        })

    @app.route("/api/geo-status")
    def api_geo_status():
        return jsonify(geo_stats())

    @app.route("/jobs/<job_id>")
    def job_detail(job_id: str):
        job = get_job(job_id)
        if not job:
            return render_template("404.html"), 404
        enrich_job(job)
        _, open_url = preview_target(job)
        job["preview_open_url"] = open_url
        job["has_preview"] = can_preview(job)
        geo = get_job_geo(job.get("institution", ""), job.get("location"))
        if geo:
            job["map_geo"] = {
                "id": job_id,
                "institution": job.get("institution"),
                "location": job.get("location"),
                "subject_area": job.get("subject_area"),
                "lat": geo["lat"],
                "lon": geo["lon"],
                "geo_precision": geo["geo_precision"],
            }
        return render_template("job.html", job=job)

    @app.route("/embed/<job_id>")
    def embed_job(job_id: str):
        job = get_job(job_id)
        if not job:
            return Response("Not found", status=404)
        body, status = render_preview(job)
        return Response(body, status=status, mimetype="text/html; charset=utf-8")

    @app.route("/api/status")
    def api_status():
        snap = state.snapshot()
        active = snap.get("running") or snap.get("phase") in (
            "starting", "ecoevojobs", "evoldir", "sciencecareers",
        )

        if active:
            with state._lock:
                baseline = state.baseline_stats or state.cached_stats or {}
            started = snap.get("started_at")
            batch_stats = job_stats(since=started) if started else None
            if not batch_stats:
                batch_stats = {
                    "total": snap.get("ecoevo_done") or 0,
                    "ecoevojobs": snap.get("ecoevo_done") or 0,
                    "evoldir": snap.get("evoldir_done") or 0,
                    "sciencecareers": snap.get("sciencecareers_done") or 0,
                    "with_deadline": 0,
                    "last_fetched_at": baseline.get("last_fetched_at"),
                }
            stats = baseline
        else:
            stats = job_stats()
            batch_stats = None
            with state._lock:
                state.cached_stats = stats
                state.baseline_stats = None

        snap["stats"] = stats
        snap["batch_stats"] = batch_stats
        snap["has_cache"] = (stats.get("total") or 0) > 0 or (
            (batch_stats or {}).get("total") or 0
        ) > 0
        snap["progress_percent"] = compute_progress_percent(snap)
        snap["progress_detail"] = build_progress_detail(snap, stats, batch_stats)
        return jsonify(snap)

    @app.route("/api/jobs")
    def api_jobs():
        source = request.args.get("source", "all")
        terms, _bbox, date_range = _parse_job_filters(request)
        sort = request.args.get("sort", "posted_at")
        order = request.args.get("order", "desc")
        jobs = list_jobs(
            source=source,
            terms=terms,
            sort=sort,
            order=order,
            date_field=date_range["field"] if date_range else None,
            date_from=date_range.get("from") or None if date_range else None,
            date_to=date_range.get("to") or None if date_range else None,
            view=_parse_view(request),
        )
        for job in jobs:
            enrich_job(job)
            job.pop("description_raw", None)
            job.pop("notes_raw", None)
            job.pop("notes_thread_json", None)
        attach_user_flags(jobs)
        with state._lock:
            stats = state.cached_stats if state.running else job_stats()
            if not state.running:
                state.cached_stats = stats
        return jsonify({"jobs": jobs, "stats": stats})

    @app.route("/api/jobs/<job_id>")
    def api_job(job_id: str):
        job = get_job(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        enrich_job(job)
        return jsonify(job)

    @app.route("/api/heartbeat", methods=["POST"])
    def api_heartbeat():
        touch_heartbeat()
        return "", 204

    @app.route("/api/shutdown", methods=["POST"])
    def api_shutdown():
        request_shutdown()
        return "", 204

    @app.route("/api/refresh", methods=["POST"])
    def api_refresh():
        snap = state.snapshot()
        if snap["running"] or snap.get("phase") == "starting":
            return jsonify({"ok": False, "message": "Scrape already in progress"}), 409
        state.update(
            phase="starting",
            message="Starting refresh…",
            error=None,
            started_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        run_scrape_async(state)
        return jsonify({"ok": True})

    app.scrape_state = state
    return app
