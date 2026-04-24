"""Slack channel as a source of Items.

Parallels the RSS source: emits one Item per top-level channel message, with
thread replies folded into the Item's summary. Reuses the SLACK_BOT_TOKEN
already used by the Slack sinks.

Required scopes: channels:history, channels:read, users:read, plus groups:*
if you point it at private channels.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from ..models import Item
from .normalize import slack_message_to_item

log = logging.getLogger(__name__)

_API = "https://slack.com/api"
_TIMEOUT = 30
_PACING_SECONDS = 1.0
_MAX_RETRIES = 3
_DEFAULT_LOOKBACK_HOURS = 24


def slack_source_from_config(entry: dict) -> "SlackChannelSource | None":
    """Build a SlackChannelSource from a feeds.json entry.

    Token comes from SLACK_BOT_TOKEN at construction time. If absent, returns
    None and logs a warning so the RSS path still runs.
    """
    channel = entry.get("channel")
    if not channel:
        log.warning("Slack source entry missing 'channel': %r", entry)
        return None

    token = os.environ.get("SLACK_BOT_TOKEN") or None
    if not token:
        log.warning(
            "Slack source %r configured but SLACK_BOT_TOKEN is not set; skipping.",
            channel,
        )
        return None

    name = entry.get("name")  # may be None; resolved from Slack at fetch time
    include_threads = entry.get("include_threads", True)
    lookback_hours = float(entry.get("lookback_hours", _DEFAULT_LOOKBACK_HOURS))

    filters = entry.get("filters") or {}
    if not isinstance(filters, dict):
        log.warning("Slack source %r has non-object `filters`; ignoring", channel)
        filters = {}

    parse_files_cfg = entry.get("parse_files")
    if parse_files_cfg is True:
        parse_files_cfg = {"enabled": True}
    elif parse_files_cfg in (False, None):
        parse_files_cfg = {}
    elif not isinstance(parse_files_cfg, dict):
        log.warning("Slack source %r has malformed `parse_files`; ignoring", channel)
        parse_files_cfg = {}

    return SlackChannelSource(
        name=name or f"Slack {channel}",
        channel_ref=channel,
        token=token,
        include_threads=bool(include_threads),
        lookback_seconds=int(lookback_hours * 3600),
        include_humans=bool(filters.get("include_humans", True)),
        include_bots=bool(filters.get("include_bots", False)),
        min_chars=int(filters.get("min_chars", 0)),
        include_pattern=filters.get("include_pattern") or None,
        parse_files=bool(parse_files_cfg.get("enabled", False)),
        max_file_mb=float(parse_files_cfg.get("max_file_mb", 5)),
        max_files_per_msg=int(parse_files_cfg.get("max_files_per_msg", 3)),
        max_pdf_text_chars=int(parse_files_cfg.get("max_text_chars", 4000)),
        _name_explicit=name is not None,
    )


@dataclass
class SlackChannelSource:
    name: str
    channel_ref: str  # "C0123..." or "#channel-name" as authored in feeds.json
    token: str
    include_threads: bool = True
    lookback_seconds: int = _DEFAULT_LOOKBACK_HOURS * 3600

    # Per-source content filters. All applied AFTER the top-level / bot-echo
    # checks; a message must pass every configured filter to become an Item.
    include_humans: bool = True       # if False, drop messages authored by humans
    include_bots: bool = False        # if True, keep bot messages (subtype=bot_message or bot_id set)
    min_chars: int = 0                # drop messages whose raw text is shorter
    include_pattern: str | None = None  # optional regex; message text must match

    # PDF attachment parsing. When enabled, downloads PDFs attached to messages
    # via `url_private`, extracts text with pypdf, folds it into the Item summary.
    parse_files: bool = False
    max_file_mb: float = 5.0
    max_files_per_msg: int = 3
    max_pdf_text_chars: int = 4000

    # Flipped to True when the user supplied `name` in feeds.json; signals we
    # should NOT overwrite it with a "Slack #channel-name" derived default.
    _name_explicit: bool = False

    # Resolved lazily on first fetch and cached on the instance.
    _session: requests.Session | None = field(default=None, repr=False)
    _channel_id: str | None = field(default=None, repr=False)
    _channel_display: str | None = field(default=None, repr=False)
    _team_domain: str | None = field(default=None, repr=False)
    _bot_user_id: str | None = field(default=None, repr=False)
    _user_cache: dict[str, str] = field(default_factory=dict, repr=False)
    _last_call_at: float = field(default=0.0, repr=False)
    _compiled_pattern: re.Pattern | None = field(default=None, repr=False)

    def fetch(self) -> list[Item]:
        try:
            if not self._ensure_ready():
                return []
            return self._collect_messages()
        except Exception as e:
            log.exception("SlackChannelSource %r failed: %s", self.channel_ref, e)
            return []

    # --- setup ---

    def _ensure_ready(self) -> bool:
        if self._session is None:
            self._session = requests.Session()
            # NOTE: Do NOT set Content-Type at the session level — Slack's GET
            # endpoints (conversations.history etc.) silently return empty
            # payloads when the request carries a `Content-Type: application/
            # json` header. It's set per-POST below instead.
            self._session.headers.update({"Authorization": f"Bearer {self.token}"})
        if self._team_domain is None or self._bot_user_id is None:
            auth = self._api("auth.test", http="post", json={})
            if not auth.get("ok"):
                log.warning(
                    "Slack auth.test failed for source %r: %s",
                    self.channel_ref,
                    auth.get("error") or auth,
                )
                return False
            url = auth.get("url") or ""
            # e.g. "https://myteam.slack.com/"
            self._team_domain = url.removeprefix("https://").split(".", 1)[0] or None
            self._bot_user_id = auth.get("user_id")

        if self._channel_id is None:
            if self.channel_ref.startswith("#"):
                # Name lookup requires iterating conversations.list; rather than
                # introduce that extra scope dependency and paging, require IDs
                # in feeds.json and tell the operator how to get them.
                log.error(
                    "Slack channel %r must be an ID (Cxxxx/Gxxxx), not a #name. "
                    "Right-click the channel in Slack → Copy link to get the ID.",
                    self.channel_ref,
                )
                return False
            self._channel_id = self.channel_ref
            info = self._api(
                "conversations.info",
                params={"channel": self._channel_id},
            )
            if not info.get("ok"):
                err = info.get("error") or info
                log.error(
                    "conversations.info failed for %s: %s", self._channel_id, err
                )
                return False
            ch = info.get("channel") or {}
            chan_name = ch.get("name")
            if self._name_explicit or not chan_name:
                self._channel_display = self.name
            else:
                self._channel_display = f"Slack #{chan_name}"
                self.name = self._channel_display

        return True

    # --- collection ---

    def _collect_messages(self) -> list[Item]:
        assert self._channel_id is not None
        oldest = str(time.time() - self.lookback_seconds)
        messages = self._history(self._channel_id, oldest)
        if not messages:
            return []

        items: list[Item] = []
        for msg in messages:
            if not self._is_top_level(msg):
                continue
            if self._is_bot_echo(msg):
                continue
            if not self._passes_filters(msg):
                continue

            thread_replies: list[dict] = []
            if self.include_threads and int(msg.get("reply_count") or 0) > 0:
                thread_replies = self._replies(self._channel_id, msg["ts"])

            attachments_text: list[dict] = []
            if self.parse_files:
                attachments_text = self._extract_pdf_attachments(msg)

            permalink = self._permalink(msg["ts"])
            item = slack_message_to_item(
                msg,
                thread_replies,
                channel_id=self._channel_id,
                channel_display_name=self._channel_display or self._channel_id,
                permalink=permalink,
                resolve_user=self._resolve_user,
                attachments_text=attachments_text,
            )
            if item is not None:
                items.append(item)

        log.info(
            "Fetched %d items from Slack channel %s",
            len(items),
            self._channel_display or self._channel_id,
        )
        return items

    def _is_top_level(self, msg: dict) -> bool:
        thread_ts = msg.get("thread_ts")
        if thread_ts and thread_ts != msg.get("ts"):
            return False  # it's a reply inside someone else's thread
        subtype = msg.get("subtype")
        skip = {"channel_join", "channel_leave", "channel_topic", "channel_purpose"}
        if not self.include_bots:
            skip.add("bot_message")
        if subtype in skip:
            return False
        return True

    def _is_bot_echo(self, msg: dict) -> bool:
        return bool(self._bot_user_id) and msg.get("user") == self._bot_user_id

    def _is_bot(self, msg: dict) -> bool:
        # Modern Slack apps post without the `bot_message` subtype but always
        # set `bot_id`; treat both as bots.
        return bool(msg.get("bot_id")) or msg.get("subtype") == "bot_message"

    def _passes_filters(self, msg: dict) -> bool:
        is_bot = self._is_bot(msg)
        if is_bot and not self.include_bots:
            return False
        if (not is_bot) and not self.include_humans:
            return False

        text = msg.get("text") or ""
        if self.min_chars and len(text) < self.min_chars:
            return False
        if self.include_pattern:
            if self._compiled_pattern is None:
                try:
                    self._compiled_pattern = re.compile(self.include_pattern)
                except re.error as e:
                    log.warning(
                        "Bad include_pattern %r for channel %s: %s; skipping filter",
                        self.include_pattern,
                        self._channel_id,
                        e,
                    )
                    self.include_pattern = None
                    return True
            if not self._compiled_pattern.search(text):
                return False
        return True

    # --- Slack API wrappers ---

    def _history(self, channel_id: str, oldest: str) -> list[dict]:
        out: list[dict] = []
        cursor: str | None = None
        joined = False
        while True:
            params = {"channel": channel_id, "oldest": oldest, "limit": "200"}
            if cursor:
                params["cursor"] = cursor
            data = self._api("conversations.history", params=params)
            if not data.get("ok"):
                err = data.get("error") or data
                if err == "not_in_channel" and not joined and self._try_join(channel_id):
                    joined = True
                    continue  # retry with same cursor (None on first iteration)
                if err == "not_in_channel":
                    log.error(
                        "Bot is not a member of Slack channel %s and could not "
                        "auto-join (needs `channels:join` scope, or channel is "
                        "private). Invite it manually with `/invite @your-bot`.",
                        channel_id,
                    )
                else:
                    log.warning("conversations.history failed for %s: %s", channel_id, err)
                return out
            out.extend(data.get("messages") or [])
            meta = data.get("response_metadata") or {}
            cursor = meta.get("next_cursor") or None
            if not cursor:
                break
        return out

    def _try_join(self, channel_id: str) -> bool:
        """Attempt conversations.join for a public channel. Returns True on
        success. Private channels (group DMs, private channels) cannot be
        joined this way — the bot still has to be invited manually.
        """
        data = self._api(
            "conversations.join", http="post", json={"channel": channel_id}
        )
        if data.get("ok"):
            log.info("Auto-joined Slack channel %s", channel_id)
            return True
        log.warning(
            "conversations.join failed for %s: %s",
            channel_id,
            data.get("error") or data,
        )
        return False

    def _replies(self, channel_id: str, root_ts: str) -> list[dict]:
        data = self._api(
            "conversations.replies",
            params={"channel": channel_id, "ts": root_ts, "limit": "200"},
        )
        if not data.get("ok"):
            log.warning(
                "conversations.replies failed for %s/%s: %s",
                channel_id,
                root_ts,
                data.get("error") or data,
            )
            return []
        return data.get("messages") or []

    def _resolve_user(self, user_id: str) -> str:
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        data = self._api("users.info", params={"user": user_id})
        name = ""
        if data.get("ok"):
            user = data.get("user") or {}
            profile = user.get("profile") or {}
            name = (
                profile.get("display_name_normalized")
                or profile.get("display_name")
                or profile.get("real_name_normalized")
                or profile.get("real_name")
                or user.get("name")
                or ""
            )
        self._user_cache[user_id] = name
        return name

    def _permalink(self, ts: str) -> str:
        if not self._team_domain or not self._channel_id:
            return ""
        ts_compact = ts.replace(".", "")
        return (
            f"https://{self._team_domain}.slack.com/archives/"
            f"{self._channel_id}/p{ts_compact}"
        )

    # --- HTTP plumbing ---

    def _api(
        self,
        api_method: str,
        *,
        http: str = "get",
        params: dict | None = None,
        json: dict | None = None,
    ) -> dict:
        assert self._session is not None
        url = f"{_API}/{api_method}"

        backoff = 1.0
        for attempt in range(1, _MAX_RETRIES + 1):
            self._pace()
            try:
                if http == "post":
                    resp = self._session.post(
                        url,
                        json=json,
                        timeout=_TIMEOUT,
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    )
                else:
                    resp = self._session.get(url, params=params, timeout=_TIMEOUT)
            except requests.RequestException as e:
                log.warning("Slack %s failed (attempt %d): %s", api_method, attempt, e)
                if attempt == _MAX_RETRIES:
                    return {"ok": False, "error": str(e)}
                time.sleep(backoff)
                backoff *= 2
                continue

            self._last_call_at = time.monotonic()
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", backoff))
                log.warning("Slack %s 429, sleeping %.1fs", api_method, retry_after)
                time.sleep(retry_after)
                backoff *= 2
                continue

            try:
                return resp.json()
            except ValueError:
                return {"ok": False, "error": f"non-json response: {resp.text[:200]}"}

        return {"ok": False, "error": "max retries exhausted"}

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < _PACING_SECONDS:
            time.sleep(_PACING_SECONDS - elapsed)

    # --- file (PDF) attachment handling ---

    def _extract_pdf_attachments(self, msg: dict) -> list[dict]:
        """For each PDF attached to `msg`, download it and extract text.

        Returns a list of `{"name": str, "text": str}` dicts (may be empty).
        Per-source caps (`max_files_per_msg`, `max_file_mb`, `max_pdf_text_chars`)
        and graceful failure on network / parse errors are applied here so the
        normalize layer just consumes ready-to-render strings.
        """
        files = msg.get("files") or []
        if not files:
            return []

        max_bytes = int(self.max_file_mb * 1024 * 1024)
        out: list[dict] = []
        processed = 0

        for f in files:
            if processed >= self.max_files_per_msg:
                break
            ftype = (f.get("filetype") or "").lower()
            mimetype = (f.get("mimetype") or "").lower()
            if ftype != "pdf" and "pdf" not in mimetype:
                continue
            if f.get("mode") == "tombstone":
                continue
            url = f.get("url_private")
            if not url:
                continue  # external-storage / no direct download

            size = int(f.get("size") or 0)
            if size and size > max_bytes:
                log.info(
                    "Skipping PDF %r in %s (%.1f MB > %.1f MB cap)",
                    f.get("name"), self._channel_id, size / 1024 / 1024, self.max_file_mb,
                )
                continue

            data = self._download_file(url, max_bytes)
            if data is None:
                continue

            from .file_parsers import extract_pdf_text

            text = extract_pdf_text(data, max_chars=self.max_pdf_text_chars)
            if text is None:
                # Could be encrypted, image-only, or malformed — surface a placeholder
                # so the LLM doesn't think the message has hidden content.
                text = "[image-only or unreadable PDF — text extraction skipped]"
            out.append({"name": f.get("name") or "attachment.pdf", "text": text})
            processed += 1

        return out

    def _download_file(self, url: str, max_bytes: int) -> bytes | None:
        """Stream a Slack-hosted file to memory with a hard byte cap. Uses the
        same authed session as the API calls. Returns None on any failure.
        """
        assert self._session is not None
        try:
            self._pace()
            with self._session.get(url, timeout=_TIMEOUT, stream=True) as resp:
                self._last_call_at = time.monotonic()
                if resp.status_code != 200:
                    log.warning(
                        "Slack file download %s returned %s",
                        url[:80], resp.status_code,
                    )
                    return None
                buf = bytearray()
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        log.info("Aborting download — file exceeds %d bytes", max_bytes)
                        return None
                return bytes(buf)
        except requests.RequestException as e:
            log.warning("Slack file download failed: %s", e)
            return None
