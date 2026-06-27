import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from jobboards.db import connect, init_db, job_stats, purge_stale, set_meta
from jobboards.scrape.ecoevo import scrape_ecoevo
from jobboards.scrape.evoldir import scrape_evoldir


@dataclass
class ScrapeState:
    running: bool = False
    message: str = "Idle"
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    phase: str = "idle"
    progress_percent: int = 0
    ecoevo_count: int = 0
    ecoevo_done: int = 0
    ecoevo_total: int = 0
    evoldir_count: int = 0
    evoldir_done: int = 0
    evoldir_total: int = 0
    sciencecareers_count: int = 0
    sciencecareers_done: int = 0
    sciencecareers_total: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    baseline_stats: Optional[dict] = None
    cached_stats: Optional[dict] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "message": self.message,
                "error": self.error,
                "warnings": list(self.warnings),
                "phase": self.phase,
                "progress_percent": self.progress_percent,
                "ecoevo_count": self.ecoevo_count,
                "ecoevo_done": self.ecoevo_done,
                "ecoevo_total": self.ecoevo_total,
                "evoldir_count": self.evoldir_count,
                "evoldir_done": self.evoldir_done,
                "evoldir_total": self.evoldir_total,
                "sciencecareers_count": self.sciencecareers_count,
                "sciencecareers_done": self.sciencecareers_done,
                "sciencecareers_total": self.sciencecareers_total,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def update(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)


def compute_progress_percent(snap: dict) -> int:
    phase = snap.get("phase", "idle")
    if phase in ("idle", "starting"):
        return 0
    if phase == "ecoevojobs":
        total = snap.get("ecoevo_total") or 0
        done = snap.get("ecoevo_done") or 0
        if total:
            return min(33, int(33 * done / total))
        return 3
    if phase == "evoldir":
        total = snap.get("evoldir_total") or 0
        done = snap.get("evoldir_done") or 0
        if total:
            return 33 + int(34 * done / total)
        return 36
    if phase == "sciencecareers":
        total = snap.get("sciencecareers_total") or 0
        done = snap.get("sciencecareers_done") or 0
        if total:
            return 67 + int(33 * done / total)
        return 70
    if phase == "done":
        return 100
    return snap.get("progress_percent") or 0


def build_progress_detail(snap: dict, stats: dict, batch_stats: Optional[dict] = None) -> str:
    phase = snap.get("phase", "idle")
    batch = batch_stats or {}
    if phase == "ecoevojobs":
        done = snap.get("ecoevo_done") or 0
        total = snap.get("ecoevo_total") or 0
        saved = batch.get("ecoevojobs", 0)
        return f"Spreadsheet rows {done}/{total} · {saved} saved this refresh"
    if phase == "evoldir":
        done = snap.get("evoldir_done") or 0
        total = snap.get("evoldir_total") or 0
        evo_saved = batch.get("ecoevojobs", 0)
        evd_saved = batch.get("evoldir", 0)
        return f"ecoevojobs {evo_saved} saved · EvolDir {done}/{total} · {evd_saved} saved this refresh"
    if phase == "sciencecareers":
        done = snap.get("sciencecareers_done") or 0
        total = snap.get("sciencecareers_total") or 0
        sc_saved = batch.get("sciencecareers", 0)
        return f"Science Careers {done}/{total} · {sc_saved} saved this refresh"
    if phase == "done":
        return f"{stats.get('total', 0)} listings total"
    return snap.get("message", "")


def scrape_all(
    state: ScrapeState,
    skip_evoldir: bool = False,
) -> None:
    with state._lock:
        if state.running:
            return
        state.running = True
        state.error = None
        state.warnings = []
        state.ecoevo_count = 0
        state.ecoevo_done = 0
        state.ecoevo_total = 0
        state.evoldir_count = 0
        state.evoldir_done = 0
        state.evoldir_total = 0
        state.sciencecareers_count = 0
        state.sciencecareers_done = 0
        state.sciencecareers_total = 0
        state.finished_at = None
        state.message = state.message or "Starting update…"
        state.baseline_stats = job_stats()

    scrape_ts = state.started_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ecoevo_n = 0
    evoldir_n = 0
    sciencecareers_n = 0
    ecoevo_ok = False
    evoldir_ok = False
    sciencecareers_ok = False
    warnings: list[str] = []

    try:
        init_db()

        state.update(phase="ecoevojobs", message="Downloading ecoevojobs…")
        try:
            with connect() as conn:
                ecoevo_n = scrape_ecoevo(conn, state=state, scraped_at=scrape_ts)
            ecoevo_ok = True
            with state._lock:
                state.ecoevo_count = ecoevo_n
        except Exception as exc:
            warnings.append(f"ecoevojobs: {exc}")

        if not skip_evoldir:
            from jobboards.scrape.evoldir import fetch_index, scrape_evoldir

            try:
                entries = fetch_index()
                state.update(
                    phase="evoldir",
                    evoldir_total=len(entries),
                    evoldir_done=0,
                    message=f"EvolDir 0/{len(entries)}",
                )
                with connect() as conn:
                    evoldir_n = scrape_evoldir(
                        conn, state=state, scraped_at=scrape_ts, entries=entries,
                    )
                evoldir_ok = True
                with state._lock:
                    state.evoldir_count = evoldir_n
            except Exception as exc:
                warnings.append(f"EvolDir: {exc}")

        from jobboards.scrape.sciencecareers import fetch_all_listings, scrape_sciencecareers

        try:
            listings = fetch_all_listings()
            state.update(
                phase="sciencecareers",
                sciencecareers_total=len(listings),
                sciencecareers_done=0,
                message=f"Science Careers 0/{len(listings)}",
            )
            with connect() as conn:
                sciencecareers_n = scrape_sciencecareers(
                    conn, state=state, scraped_at=scrape_ts, listings=listings,
                )
            sciencecareers_ok = True
            with state._lock:
                state.sciencecareers_count = sciencecareers_n
        except Exception as exc:
            warnings.append(f"Science Careers: {exc}")

        with connect() as conn:
            if ecoevo_ok:
                purge_stale(conn, "ecoevojobs", scrape_ts)
            if evoldir_ok and not skip_evoldir:
                purge_stale(conn, "evoldir", scrape_ts)
            if sciencecareers_ok:
                purge_stale(conn, "sciencecareers", scrape_ts)

        stats = job_stats()
        if stats.get("total", 0) == 0:
            detail = "; ".join(warnings) if warnings else "No jobs fetched from any source"
            raise RuntimeError(detail)

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if ecoevo_ok or evoldir_ok or sciencecareers_ok:
            set_meta("last_fetched_at", now)

        message = "Up to date"
        if warnings:
            message = f"Partial update ({len(warnings)} source(s) skipped)"

        state.update(
            phase="done",
            message=message,
            finished_at=now,
            cached_stats=stats,
            error=None,
            ecoevo_count=ecoevo_n,
            evoldir_count=evoldir_n if not skip_evoldir else state.evoldir_count,
            sciencecareers_count=sciencecareers_n,
            warnings=warnings,
        )
        from jobboards.subjects import clear_subject_cache
        clear_subject_cache()
        from jobboards.geocode import start_geocoder_daemon
        start_geocoder_daemon()
    except Exception as exc:
        state.update(
            error=str(exc),
            message=f"Error: {exc}",
            phase="error",
            finished_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            warnings=warnings,
        )
    finally:
        with state._lock:
            state.running = False


def run_scrape_async(
    state: ScrapeState,
    skip_evoldir: bool = False,
    on_complete: Optional[Callable[[], None]] = None,
) -> threading.Thread:
    def _run():
        scrape_all(state, skip_evoldir=skip_evoldir)
        if on_complete:
            on_complete()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
