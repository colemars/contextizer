"""Filetype-specific text extractors used by Slack-source attachment parsing.

Imports the heavy parser library (`pypdf`) lazily so groups not using
`parse_files` don't pay the import cost.
"""

from __future__ import annotations

import io
import logging

log = logging.getLogger(__name__)


def extract_pdf_text(data: bytes, max_chars: int) -> str | None:
    """Extract plain text from a PDF.

    Returns the (possibly truncated) extracted text, or None if extraction
    failed or the PDF appears to be image-only / encrypted (yields no useful
    text). Truncation is right-anchored with an ellipsis marker.
    """
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover — listed in requirements
        log.error("pypdf not installed — PDF parsing disabled")
        return None

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        log.warning("PDF parse failed: %s", e)
        return None

    if reader.is_encrypted:
        # pypdf can sometimes decrypt with empty password; try once.
        try:
            if reader.decrypt("") == 0:  # 0 = failed
                log.info("PDF is encrypted; skipping")
                return None
        except Exception:
            return None

    parts: list[str] = []
    total = 0
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception as e:
            log.debug("Page extraction failed: %s", e)
            continue
        text = " ".join(text.split())  # collapse whitespace
        if not text:
            continue
        parts.append(text)
        total += len(text) + 1  # space between pages
        if total >= max_chars:
            break

    body = "\n".join(parts).strip()
    if not body:
        return None  # image-only / empty PDF — caller surfaces a placeholder
    if len(body) > max_chars:
        body = body[: max_chars - 3].rstrip() + "..."
    return body
