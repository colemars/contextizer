from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    link: str
    source: str
    published: datetime | None
    summary: str
    guid: str | None
    fetched_at: datetime

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["published"] = self.published.isoformat() if self.published else None
        d["fetched_at"] = self.fetched_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Item":
        return cls(
            id=d["id"],
            title=d["title"],
            link=d["link"],
            source=d["source"],
            published=_parse_dt(d.get("published")),
            summary=d.get("summary", ""),
            guid=d.get("guid"),
            fetched_at=_parse_dt(d["fetched_at"]) or datetime.now(timezone.utc),
        )


@dataclass
class ScoredItem:
    item: Item
    score: float
    matched_keywords: list[str] = field(default_factory=list)
    group: str = "General"


@dataclass
class DigestSection:
    title: str
    body: str


@dataclass
class Digest:
    generated_at: datetime
    sections: list[DigestSection]
    rendered_markdown: str
    item_count: int


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
