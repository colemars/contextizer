from __future__ import annotations

import logging
from pathlib import Path

from ..models import Digest

log = logging.getLogger(__name__)


class MarkdownSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)

    def write_digest(self, digest: Digest) -> None:
        date_str = digest.generated_at.strftime("%Y-%m-%d")
        out = self.path / f"{date_str}.md"
        out.write_text(digest.rendered_markdown, encoding="utf-8")
        log.info("Wrote digest to %s", out)

    def close(self) -> None:
        pass
