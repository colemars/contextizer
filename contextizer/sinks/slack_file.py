from __future__ import annotations

import logging
from pathlib import Path

import requests

from ..models import Digest
from .html import load_css, render_html

log = logging.getLogger(__name__)

_API = "https://slack.com/api"
_TIMEOUT = 30


class SlackFileSink:
    """Render the digest as a self-contained HTML file and upload it to Slack.

    Requires bot scopes `files:write` + `channels:read`. The bot must be a
    member of the notify channel.
    """

    def __init__(
        self,
        bot_token: str,
        channel: str | None,
        css_file: Path,
        banner_url: str | None = None,
    ) -> None:
        if not bot_token:
            raise ValueError("SLACK_BOT_TOKEN is required for slack_file sink")
        if not channel:
            raise ValueError("SLACK_CANVAS_NOTIFY_CHANNEL is required for slack_file sink")
        self.bot_token = bot_token
        self.channel = channel
        self.css = load_css(css_file)
        self.banner_url = banner_url
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {bot_token}"})

    def write_digest(self, digest: Digest) -> None:
        html = render_html(digest, self.css, self.banner_url)
        payload = html.encode("utf-8")
        date_str = digest.generated_at.strftime("%Y-%m-%d")
        filename = f"digest-{date_str}.html"
        title = f"Daily Digest — {date_str}"
        comment = f":newspaper: *{title}* — {digest.item_count} items."
        upload_to_channel(
            self.session,
            self.channel,
            payload,
            filename=filename,
            title=title,
            content_type="text/html; charset=utf-8",
            initial_comment=comment,
        )

    def close(self) -> None:
        self.session.close()


# --- shared helpers used by slack_file + slack_pdf ---


def upload_to_channel(
    session: requests.Session,
    channel: str,
    payload: bytes,
    *,
    filename: str,
    title: str,
    content_type: str,
    initial_comment: str,
) -> None:
    """Three-step files.upload_v2 flow, including channel name-to-id resolution
    and the sharing step. Logs errors but doesn't raise."""
    upload = _get_upload_url(session, filename, len(payload))
    if upload is None:
        return
    upload_url, file_id = upload
    if not _put_bytes(upload_url, payload, content_type):
        return
    channel_id = resolve_channel_id(session, channel)
    if channel_id is None:
        log.error("Could not resolve channel id for %s; file uploaded but not shared", channel)
        return
    _complete_upload(session, file_id, title, channel_id, channel, initial_comment)


def resolve_channel_id(session: requests.Session, channel: str) -> str | None:
    """Accept a literal channel id (C..., G..., D...) or a #channel-name."""
    if channel.startswith(("C", "G", "D")) and " " not in channel and not channel.startswith("#"):
        return channel
    name = channel.lstrip("#")
    cursor: str | None = None
    for _ in range(10):
        params = {"limit": "1000", "types": "public_channel"}
        if cursor:
            params["cursor"] = cursor
        try:
            resp = session.get(f"{_API}/conversations.list", params=params, timeout=_TIMEOUT)
        except requests.RequestException as e:
            log.error("conversations.list failed: %s", e)
            return None
        data = _safe_json(resp)
        if not data.get("ok"):
            log.error("conversations.list error: %s", data.get("error") or data)
            return None
        for conv in data.get("channels", []):
            if conv.get("name") == name:
                return conv.get("id")
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break
    log.error("Channel not found: %s", channel)
    return None


def _get_upload_url(session: requests.Session, filename: str, size: int) -> tuple[str, str] | None:
    try:
        resp = session.get(
            f"{_API}/files.getUploadURLExternal",
            params={"filename": filename, "length": size},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        log.error("files.getUploadURLExternal request failed: %s", e)
        return None
    data = _safe_json(resp)
    if not data.get("ok"):
        log.error("files.getUploadURLExternal failed: %s", data.get("error") or data)
        return None
    return data["upload_url"], data["file_id"]


def _put_bytes(upload_url: str, payload: bytes, content_type: str) -> bool:
    try:
        resp = requests.post(
            upload_url,
            data=payload,
            headers={"Content-Type": content_type},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        log.error("Upload PUT failed: %s", e)
        return False
    if not resp.ok:
        log.error("Upload PUT returned %s: %s", resp.status_code, resp.text[:200])
        return False
    return True


def _complete_upload(
    session: requests.Session,
    file_id: str,
    title: str,
    channel_id: str,
    channel_label: str,
    initial_comment: str,
) -> None:
    try:
        resp = session.post(
            f"{_API}/files.completeUploadExternal",
            json={
                "files": [{"id": file_id, "title": title}],
                "channel_id": channel_id,
                "initial_comment": initial_comment,
            },
            timeout=_TIMEOUT,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
    except requests.RequestException as e:
        log.error("files.completeUploadExternal failed: %s", e)
        return
    data = _safe_json(resp)
    if not data.get("ok"):
        log.error("files.completeUploadExternal error: %s", data.get("error") or data)
        return
    files = data.get("files") or []
    permalink = files[0].get("permalink") if files else None
    log.info("Shared %s to %s%s", title, channel_label, f" ({permalink})" if permalink else "")


def _safe_json(resp: requests.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {"ok": False, "error": f"non-json response: {resp.text[:200]}"}
