from __future__ import annotations

import logging
from pathlib import Path

import requests

from ..models import Digest
from .html import load_css, render_html
from .slack_file import upload_to_channel

log = logging.getLogger(__name__)


class SlackPdfSink:
    """Render the digest as a PDF via headless Chromium (playwright) and
    upload it to Slack. Renders pixel-identical to what the HTML sink shows
    in a browser — same engine.

    Requires bot scopes `files:write` + `channels:read`, plus the bot must
    be a member of the notify channel. Also requires the `playwright`
    Python package and its Chromium binary (run `playwright install
    chromium` once after `pip install playwright`).
    """

    def __init__(
        self,
        bot_token: str,
        channel: str | None,
        css_file: Path,
        banner_url: str | None = None,
    ) -> None:
        if not bot_token:
            raise ValueError("SLACK_BOT_TOKEN is required for slack_pdf sink")
        if not channel:
            raise ValueError("SLACK_CANVAS_NOTIFY_CHANNEL is required for slack_pdf sink")
        self.bot_token = bot_token
        self.channel = channel
        self.css = load_css(css_file)
        self.banner_url = banner_url
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {bot_token}"})

    def write_digest(self, digest: Digest) -> None:
        html = render_html(digest, self.css, self.banner_url)
        try:
            pdf_bytes = _html_to_pdf(html)
        except Exception as e:
            log.error("PDF render failed: %s", e)
            return

        date_str = digest.generated_at.strftime("%Y-%m-%d")
        filename = f"digest-{date_str}.pdf"
        title = f"Daily Digest — {date_str}"
        comment = f":newspaper: *{title}* — {digest.item_count} items."

        upload_to_channel(
            self.session,
            self.channel,
            pdf_bytes,
            filename=filename,
            title=title,
            content_type="application/pdf",
            initial_comment=comment,
        )

    def close(self) -> None:
        self.session.close()


def _html_to_pdf(html: str) -> bytes:
    """Render an HTML string to a single-page tall PDF (no page breaks).

    We measure the rendered document height after layout, then emit a PDF
    whose page height matches exactly — so the whole digest is one continuous
    scroll with no mid-paragraph breaks.
    """
    from playwright.sync_api import sync_playwright

    # Pixel width for the viewport + PDF. Roughly matches the content column
    # + comfortable margins when viewed in Slack's PDF preview.
    pdf_width_px = 820

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": pdf_width_px, "height": 1200})
            # Force light mode — our CSS has a prefers-color-scheme: dark block
            # that we don't want kicking in for PDFs.
            page.emulate_media(media="screen", color_scheme="light")
            page.set_content(html, wait_until="load")
            # Measure full rendered content height after layout settles.
            height_px = int(
                page.evaluate(
                    """
                    Math.max(
                      document.body.scrollHeight,
                      document.documentElement.scrollHeight,
                      document.body.offsetHeight,
                      document.documentElement.offsetHeight
                    )
                    """
                )
            ) + 40  # trailing pad to avoid clipping the footer
            pdf = page.pdf(
                width=f"{pdf_width_px}px",
                height=f"{height_px}px",
                margin={"top": "0px", "bottom": "0px", "left": "0px", "right": "0px"},
                print_background=True,
                prefer_css_page_size=False,
            )
        finally:
            browser.close()
    return pdf
