from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config import Config
from ..models import Digest, Item


@runtime_checkable
class ItemSink(Protocol):
    def write_item(self, item: Item) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class DigestSink(Protocol):
    def write_digest(self, digest: Digest) -> None: ...
    def close(self) -> None: ...


def build_item_sink(kind: str, cfg: Config) -> ItemSink:
    from .directory import DirectorySink
    from .jsonl import JsonlSink
    from .slack import SlackSink
    from .stdout import StdoutSink

    kind = kind.lower()
    if kind == "jsonl":
        return JsonlSink(cfg.raw_output_path)
    if kind == "directory":
        return DirectorySink(cfg.raw_output_path)
    if kind == "stdout":
        return StdoutSink()
    if kind == "slack":
        if not cfg.slack_webhook_url:
            raise ValueError("SLACK_WEBHOOK_URL must be set to use slack sink")
        return SlackSink(cfg.slack_webhook_url)
    raise ValueError(f"Unknown item sink type: {kind}")


def build_digest_sink(kind: str, cfg: Config) -> DigestSink:
    from .html import HtmlSink
    from .markdown import MarkdownSink
    from .slack import SlackSink
    from .slack_canvas import SlackCanvasSink
    from .slack_file import SlackFileSink
    from .stdout import StdoutSink

    kind = kind.lower()
    if kind == "markdown":
        return MarkdownSink(cfg.digest_output_path)
    if kind == "html":
        return HtmlSink(cfg.digest_output_path, cfg.digest_css_file, cfg.digest_banner_url)
    if kind == "pdf":
        from .pdf import PdfSink
        return PdfSink(cfg.digest_output_path, cfg.digest_css_file, cfg.digest_banner_url)
    if kind == "stdout":
        return StdoutSink()
    if kind == "slack":
        if not cfg.slack_webhook_url:
            raise ValueError("SLACK_WEBHOOK_URL must be set to use slack sink")
        return SlackSink(cfg.slack_webhook_url)
    if kind == "slack_canvas":
        if not cfg.slack_bot_token:
            raise ValueError("SLACK_BOT_TOKEN must be set to use slack_canvas sink")
        return SlackCanvasSink(cfg.slack_bot_token, cfg.slack_canvas_notify_channel)
    if kind == "slack_file":
        if not cfg.slack_bot_token:
            raise ValueError("SLACK_BOT_TOKEN must be set to use slack_file sink")
        return SlackFileSink(
            cfg.slack_bot_token,
            cfg.slack_canvas_notify_channel,
            cfg.digest_css_file,
            cfg.digest_banner_url,
        )
    if kind == "slack_pdf":
        from .slack_pdf import SlackPdfSink
        if not cfg.slack_bot_token:
            raise ValueError("SLACK_BOT_TOKEN must be set to use slack_pdf sink")
        return SlackPdfSink(
            cfg.slack_bot_token,
            cfg.slack_canvas_notify_channel,
            cfg.digest_css_file,
            cfg.digest_banner_url,
        )
    raise ValueError(f"Unknown digest sink type: {kind}")
