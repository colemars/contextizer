"""Local PDF sink — renders the digest as a PDF on disk via Playwright.

Same renderer as `slack_pdf`, just writes to `<digest_output_path>/<date>.pdf`
instead of uploading to Slack. Useful for previewing the PDF locally without
posting to a channel.

Requires the `playwright` package and its Chromium binary.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..models import Digest
from .html import load_css, render_html
from .slack_pdf import _html_to_pdf

log = logging.getLogger(__name__)


class PdfSink:
    def __init__(
        self,
        out_dir: Path,
        css_file: Path,
        banner_url: str | None = None,
    ) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._css = load_css(css_file)
        self.banner_url = banner_url

    def write_digest(self, digest: Digest) -> None:
        html = render_html(digest, self._css, self.banner_url)
        try:
            pdf_bytes = _html_to_pdf(html)
        except Exception as e:
            log.error("PDF render failed: %s", e)
            return

        date_str = digest.generated_at.strftime("%Y-%m-%d")
        out = self.out_dir / f"{date_str}.pdf"
        out.write_bytes(pdf_bytes)
        log.info("Wrote PDF digest to %s", out)

    def close(self) -> None:
        pass
