import os
import sys
from pathlib import Path

ECOEVO_SHEET_ID = "1P7BfU0emdcGFVIWIs_erFxyy0UGXXORw7h0rpU19gQ8"
ECOEVO_FACULTY_GID = "1219796980"
ECOEVO_POSTDOC_GID = "1228591705"

EVOLDIR_INDEX = "https://www.evoldir.net/brian/Jobs.html"
EVOLDIR_DETAIL_BASE = "https://www.evoldir.net/brian/evoldir/Jobs//"

SCIENCE_CAREERS_BASE = "https://jobs.sciencecareers.org"

JOB_URL_PATTERNS = (
    "jobs.",
    "ukjobs.",
    "myworkdayjobs.com",
    "usajobs.gov",
    "employment.ku.dk",
    "euraxess.",
    "calcareers.",
    "karriereportal.",
    "facultypositions.",
    "workday",
    "schooljobs.com",
    "linkedin.com/jobs",
    "wd1.myworkdaysite.com",
    "wd3.myworkdayjobs.com",
    "wd5.myworkdayjobs.com",
    "wd12.myworkdayjobs.com",
    "uiowa.edu/faculty",
    "postings/",
    "/job/",
    "/jobs/",
)

HEARTBEAT_INTERVAL_SEC = 3
HEARTBEAT_TIMEOUT_SEC = 10
EVOLDIR_REQUEST_DELAY_SEC = 0.0
EVOLDIR_PARALLEL_WORKERS = 3
SCIENCE_CAREERS_PARALLEL_WORKERS = 3


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "JobBoards"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return app_data_dir() / "jobs.db"


def bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def static_dir() -> Path:
    return bundle_dir() / "static"


def templates_dir() -> Path:
    return bundle_dir() / "templates"
