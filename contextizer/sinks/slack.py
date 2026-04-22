from __future__ import annotations

import logging
import re
import time

import requests

from ..models import Digest, Item

log = logging.getLogger(__name__)

_SLACK_MAX_BLOCK_CHARS = 3000
_SLACK_MAX_PAYLOAD_CHARS = 35000
_PACING_SECONDS = 1.0
_MAX_RETRIES = 3

# Convert GitHub-flavored markdown → Slack's `mrkdwn`.
#   [text](url)  -> <url|text>
#   **bold**     -> *bold*
#   ## Heading   -> *Heading*
# Italic *x* is left alone because it collides with bold; _x_ is already
# Slack-native.
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_MD_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _to_slack_mrkdwn(md: str) -> str:
    s = _MD_LINK.sub(r"<\2|\1>", md)
    s = _MD_BOLD.sub(r"*\1*", s)
    s = _MD_HEADING.sub(r"*\1*", s)
    return s


class SlackSink:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url
        self._last_post_at: float = 0.0

    def write_item(self, item: Item) -> None:
        date_str = item.published.strftime("%Y-%m-%d") if item.published else ""
        lines = [f"*<{item.link}|{item.title}>*", f"_{item.source}_"]
        if date_str:
            lines[-1] += f" · {date_str}"
        if item.summary:
            snippet = item.summary.strip()
            if len(snippet) > 500:
                snippet = snippet[:497] + "..."
            lines.append(snippet)
        self._post({"text": "\n".join(lines)})

    def write_digest(self, digest: Digest) -> None:
        body = _to_slack_mrkdwn(digest.rendered_markdown)
        if len(body) <= _SLACK_MAX_PAYLOAD_CHARS:
            self._post({"text": body, "mrkdwn": True, "unfurl_links": False, "unfurl_media": False})
            return
        for chunk in _chunk(body, _SLACK_MAX_PAYLOAD_CHARS):
            self._post({"text": chunk, "mrkdwn": True, "unfurl_links": False, "unfurl_media": False})

    def close(self) -> None:
        pass

    def _post(self, payload: dict) -> None:
        elapsed = time.monotonic() - self._last_post_at
        if elapsed < _PACING_SECONDS:
            time.sleep(_PACING_SECONDS - elapsed)

        backoff = 1.0
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = requests.post(self.webhook_url, json=payload, timeout=15)
            except requests.RequestException as e:
                log.warning("Slack POST failed (attempt %d): %s", attempt, e)
                if attempt == _MAX_RETRIES:
                    return
                time.sleep(backoff)
                backoff *= 2
                continue

            self._last_post_at = time.monotonic()
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", backoff))
                log.warning("Slack 429, sleeping %.1fs", retry_after)
                time.sleep(retry_after)
                backoff *= 2
                continue
            if resp.ok:
                return
            log.warning("Slack POST returned %s: %s", resp.status_code, resp.text[:200])
            return


def _chunk(s: str, size: int) -> list[str]:
    return [s[i : i + size] for i in range(0, len(s), size)]
