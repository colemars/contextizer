from __future__ import annotations

import logging

import requests

from ..models import Digest

log = logging.getLogger(__name__)

_API = "https://slack.com/api"
_TIMEOUT = 30


class SlackCanvasSink:
    """Create a Slack Canvas per digest and (optionally) notify a channel with the link.

    Requires a Bot User OAuth token (xoxb-...) with `canvases:write` and — if
    `notify_channel` is set — `chat:write`. The bot must be invited to the
    notify channel for the post to succeed.
    """

    def __init__(self, bot_token: str, notify_channel: str | None = None) -> None:
        if not bot_token:
            raise ValueError("SLACK_BOT_TOKEN is required for slack_canvas sink")
        self.bot_token = bot_token
        self.notify_channel = notify_channel or None
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
        )
        self._workspace_url: str | None = None
        self._team_id: str | None = None

    def write_digest(self, digest: Digest) -> None:
        title = f"Daily Digest — {digest.generated_at.strftime('%Y-%m-%d')}"
        canvas_id = self._create_canvas(title, digest.rendered_markdown)
        if canvas_id is None:
            return

        permalink = self._canvas_url(canvas_id)
        log.info("Created canvas %s%s", canvas_id, f" ({permalink})" if permalink else "")

        if self.notify_channel:
            label = f"<{permalink}|{title}>" if permalink else title
            self._post_message(self.notify_channel, f":newspaper: {label}")

    def _canvas_url(self, canvas_id: str) -> str | None:
        if self._workspace_url is None:
            self._fetch_workspace_info()
        if not self._workspace_url or not self._team_id:
            return None
        base = self._workspace_url.rstrip("/")
        return f"{base}/docs/{self._team_id}/{canvas_id}"

    def _fetch_workspace_info(self) -> None:
        try:
            resp = self.session.get(f"{_API}/auth.test", timeout=_TIMEOUT)
        except requests.RequestException as e:
            log.warning("auth.test failed: %s", e)
            return
        data = _safe_json(resp)
        if not data.get("ok"):
            log.warning("auth.test returned: %s", data.get("error") or data)
            return
        self._workspace_url = data.get("url")
        self._team_id = data.get("team_id")

    def close(self) -> None:
        self.session.close()

    # --- Slack API wrappers ---

    def _create_canvas(self, title: str, markdown: str) -> str | None:
        try:
            resp = self.session.post(
                f"{_API}/canvases.create",
                json={
                    "title": title,
                    "document_content": {"type": "markdown", "markdown": markdown},
                },
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            log.error("canvases.create request failed: %s", e)
            return None

        data = _safe_json(resp)
        if not data.get("ok"):
            log.error("canvases.create failed: %s", data.get("error") or data)
            return None
        return data.get("canvas_id")

    def _post_message(self, channel: str, text: str) -> None:
        try:
            resp = self.session.post(
                f"{_API}/chat.postMessage",
                json={
                    "channel": channel,
                    "text": text,
                    "unfurl_links": True,
                },
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            log.warning("chat.postMessage failed: %s", e)
            return
        data = _safe_json(resp)
        if not data.get("ok"):
            log.warning("chat.postMessage error: %s", data.get("error") or data)


def _safe_json(resp: requests.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {"ok": False, "error": f"non-json response: {resp.text[:200]}"}
