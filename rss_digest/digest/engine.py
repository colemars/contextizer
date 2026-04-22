from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..config import Config
from ..models import Digest, DigestSection
from ..sinks.base import DigestSink
from .filters import filter_english
from .profile import load_profile
from .prompts import render_digest_prompt
from .relevance import score_items
from .sources import load_items
from .summarizer import build_summarizer

log = logging.getLogger(__name__)


def run_digest(cfg: Config, sink: DigestSink, since: datetime | None) -> Digest:
    items = load_items(cfg.raw_input_type, cfg.raw_input_path, since)
    log.info("Loaded %d items since %s", len(items), since)

    if cfg.filter_non_english:
        before = len(items)
        items = filter_english(items)
        log.info("Language filter: kept %d of %d items", len(items), before)

    profile = load_profile(cfg.profile_file, cfg.interests_file)
    scored = score_items(items, profile.keywords, cfg.max_items_for_digest)
    log.info("Scored %d items, keeping top %d", len(items), len(scored))

    now = datetime.now(timezone.utc)
    prompt = render_digest_prompt(cfg.digest_prompt_file, profile.text, scored, now.date())

    summarizer = build_summarizer(cfg.summarizer, cfg.llm_command)
    body = summarizer.summarize(scored, profile.text, prompt)

    header = _render_header(now, len(scored), len(items))
    rendered = header + body

    digest = Digest(
        generated_at=now,
        sections=[DigestSection(title="Digest", body=body)],
        rendered_markdown=rendered,
        item_count=len(scored),
    )
    sink.write_digest(digest)
    sink.close()
    return digest


def _render_header(now: datetime, kept: int, total: int) -> str:
    return (
        f"# Daily Digest — {now.strftime('%Y-%m-%d')}\n\n"
        f"_Generated {now.strftime('%Y-%m-%d %H:%M UTC')} · "
        f"{kept} of {total} items kept_\n\n"
    )
