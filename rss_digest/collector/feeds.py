from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

import feedparser
import requests

from ..models import Item
from .normalize import to_item

log = logging.getLogger(__name__)

_USER_AGENT = "rss-digest/0.1 (+https://github.com/)"
_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 30


@dataclass(frozen=True)
class FeedSpec:
    url: str
    name: str


@dataclass
class FeedGroup:
    name: str
    feeds: list[FeedSpec]
    profile_file: Path | None = None
    interests_file: Path | None = None


def load_groups(path: Path, root: Path | None = None) -> dict[str, FeedGroup]:
    """Load feed groups from feeds.json.

    Two supported shapes:
      Flat (single default group):
        {"feeds": [...]}
      Grouped:
        {"groups": {"ai": {"feeds": [...], "profile": "...", "interests": "..."}, ...}}
    """
    if not path.exists():
        raise FileNotFoundError(f"feeds file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    root = root or path.parent

    if isinstance(raw, dict) and "groups" in raw:
        groups_raw = raw["groups"]
        if not isinstance(groups_raw, dict) or not groups_raw:
            raise ValueError("'groups' must be a non-empty object")
        out: dict[str, FeedGroup] = {}
        for name, body in groups_raw.items():
            out[name] = _group_from_body(name, body, root)
        return out

    # Flat fallback.
    entries = raw.get("feeds", []) if isinstance(raw, dict) else raw
    return {"default": FeedGroup(name="default", feeds=_parse_feeds(entries))}


def _group_from_body(name: str, body: dict, root: Path) -> FeedGroup:
    if not isinstance(body, dict):
        raise ValueError(f"group {name!r} must be an object")
    feeds = _parse_feeds(body.get("feeds", []))
    if not feeds:
        log.warning("Group %r has no feeds", name)
    profile = body.get("profile")
    interests = body.get("interests")
    return FeedGroup(
        name=name,
        feeds=feeds,
        profile_file=_resolve(root, profile),
        interests_file=_resolve(root, interests),
    )


def _resolve(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else root / p


def _parse_feeds(entries: list) -> list[FeedSpec]:
    specs: list[FeedSpec] = []
    for entry in entries:
        if isinstance(entry, str):
            specs.append(FeedSpec(url=entry, name=_default_name(entry)))
        elif isinstance(entry, dict) and entry.get("url"):
            url = entry["url"]
            specs.append(FeedSpec(url=url, name=entry.get("name") or _default_name(url)))
        else:
            log.warning("Skipping malformed feed entry: %r", entry)
    return specs


def _default_name(url: str) -> str:
    return urlparse(url).hostname or url


def fetch_feed(spec: FeedSpec) -> list[Item]:
    try:
        resp = requests.get(
            spec.url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5",
            },
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("Fetch failed for %s: %s", spec.url, e)
        return []

    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        log.warning("Feed parse error for %s: %s", spec.url, parsed.bozo_exception)
        return []

    feed_title = getattr(parsed.feed, "title", "") if hasattr(parsed, "feed") else ""
    source_name = spec.name or feed_title or _default_name(spec.url)

    items: list[Item] = []
    for raw in parsed.entries:
        item = to_item(raw, source_name)
        if item is not None:
            items.append(item)
    log.info("Fetched %d items from %s", len(items), spec.url)
    return items


def fetch_all(specs: list[FeedSpec]) -> Iterator[Item]:
    for spec in specs:
        yield from fetch_feed(spec)
