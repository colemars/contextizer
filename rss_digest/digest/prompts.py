from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..models import ScoredItem

_FALLBACK_PROMPT = """You are generating a personalized daily digest for the user.

Today is {{date}}.

User profile:
---
{{profile}}
---

Candidate items (already pre-filtered for relevance, JSON):
{{items_json}}

Instructions:
- Put the most-relevant items first. For each item, include a one-line "why this matters".
- Group related items under topic headings.
- Skip items that don't meaningfully match the profile.
- Keep the total under ~800 words. Markdown only.
- Include the source and link for every item cited.
"""


def render_digest_prompt(
    template_file: Path,
    profile_text: str,
    items: list[ScoredItem],
    today: date,
) -> str:
    template = template_file.read_text(encoding="utf-8") if template_file.exists() else _FALLBACK_PROMPT
    items_payload = [
        {
            "title": s.item.title,
            "link": s.item.link,
            "source": s.item.source,
            "published": s.item.published.isoformat() if s.item.published else None,
            "summary": s.item.summary,
            "score": round(s.score, 3),
            "matched": s.matched_keywords,
            "group": s.group,
        }
        for s in items
    ]
    return (
        template.replace("{{profile}}", profile_text.strip() or "(no profile provided)")
        .replace("{{items_json}}", json.dumps(items_payload, ensure_ascii=False, indent=2))
        .replace("{{date}}", today.isoformat())
    )
