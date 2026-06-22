import json
import re
from typing import Any


def parse_notes_thread(text: str) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return []

    if not re.search(r"(?<=\S)\s+(?:\d+|OP)\)\s*", text):
        return [{"index": 0, "label": "intro", "text": text, "parentIndex": None}]

    parts = re.split(r"(?<=\S)\s+(?:(\d+|OP)\)\s*)", text)
    items: list[dict[str, Any]] = []
    if parts[0].strip():
        items.append({"index": 0, "label": "intro", "text": parts[0].strip(), "parentIndex": None})

    i = 1
    idx = 1
    while i < len(parts) - 1:
        label, body = parts[i], parts[i + 1].strip()
        parent = None
        reply = re.match(r"@\s*(\d+)", body)
        if reply:
            parent = int(reply.group(1))
        items.append({"index": idx, "label": label, "text": body, "parentIndex": parent})
        idx += 1
        i += 2
    return items


def notes_thread_to_json(text: str) -> str:
    return json.dumps(parse_notes_thread(text))
