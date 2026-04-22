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
    from .markdown import MarkdownSink
    from .slack import SlackSink
    from .stdout import StdoutSink

    kind = kind.lower()
    if kind == "markdown":
        return MarkdownSink(cfg.digest_output_path)
    if kind == "stdout":
        return StdoutSink()
    if kind == "slack":
        if not cfg.slack_webhook_url:
            raise ValueError("SLACK_WEBHOOK_URL must be set to use slack sink")
        return SlackSink(cfg.slack_webhook_url)
    raise ValueError(f"Unknown digest sink type: {kind}")
