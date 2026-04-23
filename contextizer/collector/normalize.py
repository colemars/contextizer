from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable

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


# --- Slack helpers ---

_SLACK_USER_RE = re.compile(r"<@([UW][A-Z0-9]+)(?:\|([^>]+))?>")
_SLACK_CHANNEL_RE = re.compile(r"<#([CG][A-Z0-9]+)(?:\|([^>]+))?>")
_SLACK_LINK_RE = re.compile(r"<(https?://[^|>]+)(?:\|([^>]+))?>")
_SLACK_SUBTEAM_RE = re.compile(r"<!subteam\^([A-Z0-9]+)(?:\|([^>]+))?>")
_SLACK_SPECIAL_RE = re.compile(r"<!(here|channel|everyone)>")
_SUMMARY_CAP = 2000


def normalize_slack_text(
    text: str,
    resolve_user: Callable[[str], str] | None = None,
) -> str:
    """Strip Slack's mrkdwn decorations so LLM prompts see plain text.

    - `<@U123|alice>` -> `@alice`; `<@U123>` -> `@<resolved>` (or @U123 if unresolved)
    - `<#C123|general>` -> `#general`
    - `<https://x|label>` -> `label (https://x)`; bare `<https://x>` -> `https://x`
    - `<!here>` / `<!channel>` -> `@here` / `@channel`
    """
    if not text:
        return ""

    def _user(m: re.Match) -> str:
        label = m.group(2)
        if label:
            return f"@{label}"
        uid = m.group(1)
        if resolve_user is not None:
            resolved = resolve_user(uid)
            if resolved:
                return f"@{resolved}"
        return f"@{uid}"

    def _channel(m: re.Match) -> str:
        label = m.group(2) or m.group(1)
        return f"#{label}"

    def _link(m: re.Match) -> str:
        url, label = m.group(1), m.group(2)
        if label and label != url:
            return f"{label} ({url})"
        return url

    def _subteam(m: re.Match) -> str:
        label = m.group(2)
        return f"@{label}" if label else f"@{m.group(1)}"

    out = _SLACK_USER_RE.sub(_user, text)
    out = _SLACK_CHANNEL_RE.sub(_channel, out)
    out = _SLACK_LINK_RE.sub(_link, out)
    out = _SLACK_SUBTEAM_RE.sub(_subteam, out)
    out = _SLACK_SPECIAL_RE.sub(lambda m: f"@{m.group(1)}", out)
    return out


def _slack_title(normalized_text: str, fallback: str) -> str:
    for line in normalized_text.splitlines():
        line = line.strip()
        if line:
            return line[:117] + "..." if len(line) > 120 else line
    return fallback


def slack_message_to_item(
    msg: dict,
    thread_replies: list[dict],
    *,
    channel_id: str,
    channel_display_name: str,
    permalink: str,
    resolve_user: Callable[[str], str] | None = None,
) -> Item | None:
    """Convert a Slack `conversations.history` message (plus optional thread
    replies) into an Item. Returns None if the message has no usable content.
    """
    ts = msg.get("ts")
    if not ts:
        return None

    raw_text = msg.get("text") or ""
    body = normalize_slack_text(raw_text, resolve_user)

    reply_count = int(msg.get("reply_count") or 0)
    summary_parts = [body] if body else []

    if thread_replies:
        lines: list[str] = []
        for reply in thread_replies:
            if reply.get("ts") == ts:
                continue  # root already captured above
            reply_text = normalize_slack_text(reply.get("text") or "", resolve_user)
            if not reply_text:
                continue
            author = reply.get("user") or "unknown"
            if resolve_user is not None:
                resolved = resolve_user(author)
                if resolved:
                    author = resolved
            lines.append(f"@{author}: {reply_text}")
        if lines:
            summary_parts.append("---")
            summary_parts.extend(lines)

    summary = "\n".join(summary_parts)
    if len(summary) > _SUMMARY_CAP:
        summary = summary[: _SUMMARY_CAP - 3] + "..."

    title = _slack_title(body, fallback=f"Slack message {ts}")
    basis = f"slack::{channel_id}::{ts}::r{reply_count}"
    item_id = hashlib.sha1(basis.encode("utf-8")).hexdigest()
    published = _slack_ts_to_dt(ts)

    if not body and not thread_replies:
        # Nothing meaningful to digest.
        return None

    return Item(
        id=item_id,
        title=title,
        link=permalink,
        source=channel_display_name,
        published=published,
        summary=summary,
        guid=f"{channel_id}:{ts}",
        fetched_at=datetime.now(timezone.utc),
    )


def _slack_ts_to_dt(ts: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None
