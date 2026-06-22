import re
from datetime import datetime
from typing import Optional

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _infer_year(month: int, ref: Optional[datetime] = None) -> int:
    ref = ref or datetime.now()
    year = ref.year
    if month > ref.month + 2:
        year -= 1
    return year


def parse_ecoevo_datetime(value: str, ref: Optional[datetime] = None) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%m/%d/%y %H:%M", "%m/%d/%Y %H:%M", "%m/%d/%y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def parse_ecoevo_date(value: str) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.date().isoformat()
        except ValueError:
            continue
    return None


def parse_evoldir_posted(value: str, ref: Optional[datetime] = None) -> Optional[str]:
    """Parse 'Jun 16 09:14' from EvolDir index."""
    value = (value or "").strip()
    m = re.match(r"([A-Za-z]{3})\s+(\d{1,2})\s+(\d{2}):(\d{2})", value)
    if not m:
        return None
    month = MONTHS.get(m.group(1).lower()[:3])
    if not month:
        return None
    ref = ref or datetime.now()
    year = _infer_year(month, ref)
    try:
        dt = datetime(year, month, int(m.group(2)), int(m.group(3)), int(m.group(4)))
        return dt.isoformat()
    except ValueError:
        return None


def parse_sciencecareers_closing(value: str) -> Optional[str]:
    """Parse 'Aug 17, 2026' from Science Careers detail pages."""
    return _parse_fuzzy_date((value or "").strip())


def parse_deadline_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"[Dd]eadline for applications is\s+(\d{1,2}\s+\w+\s+\d{4})",
        r"[Aa]pplications received by\s+(\w+\s+\d{1,2},?\s+\d{4})",
        r"\bby\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b",
        r"through\s+\w+day\s+(\d{1,2}/\d{1,2}/\d{2,4})",
        r"from\s+\w+day\s+\d{1,2}/\d{1,2}/\d{2,4}\s+through\s+\w+day\s+(\d{1,2}/\d{1,2}/\d{2,4})",
        r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}),?\s*23:59",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            parsed = _parse_fuzzy_date(m.group(1))
            if parsed:
                return parsed
    return None


def parse_deadline_from_slug(slug: str) -> Optional[str]:
    m = re.search(r"Deadline(\d{1,2})-(\d{1,2})-(\d{2})", slug, re.I)
    if not m:
        return None
    day, month, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    year = 2000 + yy if yy < 100 else yy
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def _parse_fuzzy_date(value: str) -> Optional[str]:
    value = value.strip().rstrip(",")
    for fmt in (
        "%B %d, %Y", "%B %d %Y", "%d %B %Y", "%m/%d/%Y", "%m/%d/%y",
        "%d/%m/%Y", "%d %B, %Y",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.date().isoformat()
        except ValueError:
            continue
    return None


def days_until(iso_date: Optional[str]) -> Optional[int]:
    if not iso_date:
        return None
    try:
        from datetime import date
        if "T" in iso_date:
            target = datetime.fromisoformat(iso_date).date()
        else:
            target = date.fromisoformat(iso_date[:10])
        return (target - datetime.now().date()).days
    except ValueError:
        return None


def format_display(iso_value: Optional[str], include_time: bool = False) -> str:
    if not iso_value:
        return "—"
    try:
        if "T" in iso_value:
            dt = datetime.fromisoformat(iso_value)
            if include_time:
                return dt.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
            return dt.strftime("%b %d, %Y")
        from datetime import date
        d = date.fromisoformat(iso_value[:10])
        return d.strftime("%b %d, %Y")
    except ValueError:
        return iso_value
