from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ..models import Item

log = logging.getLogger(__name__)


def load_items(kind: str, path: Path, since: datetime | None = None) -> list[Item]:
    kind = kind.lower()
    if kind == "jsonl":
        items = _load_jsonl(path)
    elif kind == "directory":
        items = _load_directory(path)
    else:
        raise ValueError(f"Unknown input kind: {kind}")

    if since is not None:
        items = [i for i in items if i.fetched_at >= since]

    # Deduplicate by id — the raw store may contain duplicates if a user re-ran collection.
    dedup: dict[str, Item] = {}
    for item in items:
        existing = dedup.get(item.id)
        if existing is None or item.fetched_at > existing.fetched_at:
            dedup[item.id] = item
    return list(dedup.values())


def _load_jsonl(path: Path) -> list[Item]:
    if not path.exists():
        log.warning("JSONL input not found: %s", path)
        return []
    out: list[Item] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(Item.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError) as e:
                log.warning("Bad JSONL line %d in %s: %s", lineno, path, e)
    return out


def _load_directory(path: Path) -> list[Item]:
    if not path.exists():
        log.warning("Directory input not found: %s", path)
        return []
    out: list[Item] = []
    for file in sorted(path.glob("*.json")):
        try:
            out.append(Item.from_dict(json.loads(file.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, KeyError, OSError) as e:
            log.warning("Could not read %s: %s", file, e)
    return out
