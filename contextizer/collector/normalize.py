from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

from ..models import Item


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return raw
    return " ".join(parser.text().split())


def _struct_time_to_dt(st: Any) -> datetime | None:
    if not st:
        return None
    try:
        return datetime.fromtimestamp(time.mktime(st), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _stable_id(link: str, guid: str | None, title: str, source: str) -> str:
    basis = (link or guid or f"{source}::{title}").strip()
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def to_item(raw: Any, source_name: str) -> Item | None:
    title = (getattr(raw, "title", "") or "").strip()
    link = (getattr(raw, "link", "") or "").strip()
    if not title and not link:
        return None

    guid = getattr(raw, "id", None) or getattr(raw, "guid", None)
    guid = guid.strip() if isinstance(guid, str) else None

    summary_raw = getattr(raw, "summary", "") or getattr(raw, "description", "") or ""
    summary = strip_html(summary_raw)
    if len(summary) > 2000:
        summary = summary[:1997] + "..."

    published = (
        _struct_time_to_dt(getattr(raw, "published_parsed", None))
        or _struct_time_to_dt(getattr(raw, "updated_parsed", None))
    )

    return Item(
        id=_stable_id(link, guid, title, source_name),
        title=title or link,
        link=link,
        source=source_name,
        published=published,
        summary=summary,
        guid=guid,
        fetched_at=datetime.now(timezone.utc),
    )
