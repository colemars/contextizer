from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable
from urllib.parse import urlparse

import feedparser
import requests

from ..models import Item
from .normalize import to_item

log = logging.getLogger(__name__)

_USER_AGENT = "contextizer/0.1 (+https://github.com/)"
_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 30


@runtime_checkable
class Source(Protocol):
    """A thing that produces Items. RSS feeds, Slack channels, and future source
    types all share this shape so the collector pipeline doesn't care how an
    Item was born.
    """

    name: str

    def fetch(self) -> list[Item]: ...


@dataclass(frozen=True)
class RssSource:
    url: str
    name: str

    def fetch(self) -> list[Item]:
        return _fetch_rss(self)


# Back-compat alias — external callers and older code may still import FeedSpec.
FeedSpec = RssSource


@dataclass
class FeedGroup:
    name: str
    sources: list[Source]
    profile_file: Path | None = None
    interests_file: Path | None = None
    # Per-group digest output overrides. None means "inherit from .env".
    digest_output_type: str | None = None
    slack_notify_channel: str | None = None
    digest_prompt_file: Path | None = None
    digest_css_file: Path | None = None
    digest_include_header: bool | None = None


def load_groups(path: Path, root: Path | None = None) -> dict[str, FeedGroup]:
    """Load source groups from feeds.json.

    `root` is the project root against which relative paths in feeds.json
    (profile, interests, digest.prompt, digest.css, …) are resolved. If
    omitted, we fall back to `path.parent.parent` on the assumption that
    feeds.json lives in `<root>/data/`.

    Two supported shapes:
      Flat (single default group):
        {"feeds": [...]}
      Grouped:
        {"groups": {"ai": {"feeds": [...], "profile": "...", "interests": "..."}, ...}}

    Each entry in a `feeds` list may be an RSS URL (string), an object
    {"url": ..., "name": ...} (RSS, back-compat), or a typed object
    {"type": "slack", "channel": "...", ...}.
    """
    if not path.exists():
        raise FileNotFoundError(f"feeds file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    root = root or path.parent.parent

    defaults_raw = raw.get("defaults") if isinstance(raw, dict) else None
    defaults_digest = _parse_digest_block(defaults_raw, context="defaults")

    if isinstance(raw, dict) and "groups" in raw:
        groups_raw = raw["groups"]
        if not isinstance(groups_raw, dict) or not groups_raw:
            raise ValueError("'groups' must be a non-empty object")
        out: dict[str, FeedGroup] = {}
        for name, body in groups_raw.items():
            out[name] = _group_from_body(name, body, root, defaults_digest)
        return out

    # Flat fallback.
    entries = raw.get("feeds", []) if isinstance(raw, dict) else raw
    return {
        "default": FeedGroup(
            name="default",
            sources=_parse_sources(entries),
            digest_output_type=defaults_digest.get("output_type"),
            slack_notify_channel=defaults_digest.get("notify_channel"),
        )
    }


def _parse_digest_block(parent: dict | None, *, context: str) -> dict:
    if not isinstance(parent, dict):
        return {}
    block = parent.get("digest")
    if block is None:
        return {}
    if not isinstance(block, dict):
        log.warning("%s has non-object `digest`; ignoring", context)
        return {}
    return block


def _group_from_body(
    name: str, body: dict, root: Path, defaults_digest: dict
) -> FeedGroup:
    if not isinstance(body, dict):
        raise ValueError(f"group {name!r} must be an object")
    sources = _parse_sources(body.get("feeds", []))
    if not sources:
        log.warning("Group %r has no sources", name)
    profile = body.get("profile")
    interests = body.get("interests")
    group_digest = _parse_digest_block(body, context=f"group {name!r}")

    # Per-group `digest` overrides, global `defaults.digest` fills in the rest.
    output_type = group_digest.get("output_type") or defaults_digest.get("output_type")
    notify_channel = (
        group_digest.get("notify_channel") or defaults_digest.get("notify_channel")
    )
    prompt = group_digest.get("prompt") or defaults_digest.get("prompt")
    css = group_digest.get("css") or defaults_digest.get("css")
    include_header = group_digest.get("include_header")
    if include_header is None:
        include_header = defaults_digest.get("include_header")

    return FeedGroup(
        name=name,
        sources=sources,
        profile_file=_resolve(root, profile),
        interests_file=_resolve(root, interests),
        digest_output_type=output_type or None,
        slack_notify_channel=notify_channel or None,
        digest_prompt_file=_resolve(root, prompt),
        digest_css_file=_resolve(root, css),
        digest_include_header=None if include_header is None else bool(include_header),
    )


def _resolve(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else root / p


def _parse_sources(entries: list) -> list[Source]:
    out: list[Source] = []
    for entry in entries:
        source = _parse_one(entry)
        if source is not None:
            out.append(source)
    return out


def _parse_one(entry) -> Source | None:
    if isinstance(entry, str):
        return RssSource(url=entry, name=_default_name(entry))
    if not isinstance(entry, dict):
        log.warning("Skipping malformed feed entry: %r", entry)
        return None

    source_type = (entry.get("type") or "rss").lower()
    if source_type == "rss":
        url = entry.get("url")
        if not url:
            log.warning("Skipping RSS entry without 'url': %r", entry)
            return None
        return RssSource(url=url, name=entry.get("name") or _default_name(url))
    if source_type == "slack":
        # Imported lazily so parsing feeds.json doesn't force the Slack source
        # module (and its requests session) to load for pure-RSS users.
        from .slack import slack_source_from_config

        return slack_source_from_config(entry)

    log.warning("Unknown source type %r; skipping entry %r", source_type, entry)
    return None


def _default_name(url: str) -> str:
    return urlparse(url).hostname or url


def _fetch_rss(spec: RssSource) -> list[Item]:
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


def fetch_feed(spec: RssSource) -> list[Item]:
    """Back-compat shim — older callers imported this directly."""
    return _fetch_rss(spec)


def fetch_all(sources: list[Source]) -> Iterator[Item]:
    for source in sources:
        yield from source.fetch()
