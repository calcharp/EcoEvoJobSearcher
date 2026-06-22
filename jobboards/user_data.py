import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from jobboards.db import connect

USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_jobs (
    job_id TEXT PRIMARY KEY,
    saved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dismissed_jobs (
    job_id TEXT PRIMARY KEY,
    dismissed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_saved_jobs_at ON saved_jobs(saved_at);
CREATE INDEX IF NOT EXISTS idx_dismissed_jobs_at ON dismissed_jobs(dismissed_at);
CREATE INDEX IF NOT EXISTS idx_saved_searches_name ON saved_searches(name);
"""


def init_user_schema(conn) -> None:
    conn.executescript(USER_SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_saved_job_ids() -> set[str]:
    with connect() as conn:
        rows = conn.execute("SELECT job_id FROM saved_jobs").fetchall()
    return {r["job_id"] for r in rows}


def get_dismissed_job_ids() -> set[str]:
    with connect() as conn:
        rows = conn.execute("SELECT job_id FROM dismissed_jobs").fetchall()
    return {r["job_id"] for r in rows}


def save_job(job_id: str) -> bool:
    with connect() as conn:
        conn.execute(
            "INSERT INTO saved_jobs(job_id, saved_at) VALUES(?, ?) "
            "ON CONFLICT(job_id) DO NOTHING",
            (job_id, _now()),
        )
        return conn.execute("SELECT changes()").fetchone()[0] > 0


def unsave_job(job_id: str) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM saved_jobs WHERE job_id = ?", (job_id,))
        return conn.execute("SELECT changes()").fetchone()[0] > 0


def dismiss_job(job_id: str) -> bool:
    with connect() as conn:
        conn.execute(
            "INSERT INTO dismissed_jobs(job_id, dismissed_at) VALUES(?, ?) "
            "ON CONFLICT(job_id) DO NOTHING",
            (job_id, _now()),
        )
        return conn.execute("SELECT changes()").fetchone()[0] > 0


def restore_job(job_id: str) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM dismissed_jobs WHERE job_id = ?", (job_id,))
        return conn.execute("SELECT changes()").fetchone()[0] > 0


def list_saved_searches() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, name, payload_json, created_at, updated_at "
            "FROM saved_searches ORDER BY lower(name), created_at"
        ).fetchall()
    items = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        items.append({
            "id": row["id"],
            "name": row["name"],
            "payload": payload,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return items


def save_search(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    clean = name.strip()
    if not clean:
        raise ValueError("Search name is required")
    search_id = str(uuid.uuid4())
    now = _now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO saved_searches(id, name, payload_json, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (search_id, clean, json.dumps(payload), now, now),
        )
    return {"id": search_id, "name": clean, "payload": payload, "created_at": now, "updated_at": now}


def delete_saved_search(search_id: str) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM saved_searches WHERE id = ?", (search_id,))
        return conn.execute("SELECT changes()").fetchone()[0] > 0


def user_data_snapshot() -> dict[str, Any]:
    return {
        "saved_job_ids": sorted(get_saved_job_ids()),
        "dismissed_job_ids": sorted(get_dismissed_job_ids()),
        "saved_searches": list_saved_searches(),
    }


def attach_user_flags(jobs: list[dict[str, Any]]) -> None:
    saved = get_saved_job_ids()
    dismissed = get_dismissed_job_ids()
    for job in jobs:
        job_id = job.get("id")
        job["is_saved"] = job_id in saved
        job["is_dismissed"] = job_id in dismissed
