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
    extra_instructions: str | None = None,
    sections: list[dict] | None = None,
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
    addendum = _build_addendum(sections, extra_instructions)
    return (
        template.replace("{{profile}}", profile_text.strip() or "(no profile provided)")
        .replace("{{items_json}}", json.dumps(items_payload, ensure_ascii=False, indent=2))
        .replace("{{date}}", today.isoformat())
        .replace("{{extra_instructions}}", addendum)
    )


def _build_addendum(sections: list[dict] | None, instructions: str | None) -> str:
    parts: list[str] = []
    sec = _sections_block(sections)
    if sec:
        parts.append(sec)
    if instructions:
        body = instructions.strip()
        if body:
            parts.append(f"## Additional guidance for this group\n\n{body}")
    return "\n\n".join(parts)


_PLACEMENT_DESCRIPTIONS = {
    "after_tldr": "immediately after the TL;DR, before topic paragraphs",
    "topic": "as one of the topic paragraphs (counts toward the topic-paragraph floor)",
    "after_topics": "after topic paragraphs, before the pipeline-appended \"Also in today's feed\" list",
}


def _sections_block(sections: list[dict] | None) -> str:
    if not sections:
        return ""

    # Group by placement so the LLM sees ordering semantics clearly.
    by_placement: dict[str, list[dict]] = {"after_tldr": [], "topic": [], "after_topics": []}
    for s in sections:
        placement = (s.get("placement") or "after_topics").lower()
        if placement not in by_placement:
            placement = "after_topics"
        by_placement[placement].append(s)

    lines: list[str] = ["## Required priority sections", ""]
    lines.append(
        "Each section below is a structural requirement. When at least `min` "
        "items in the feed match its criteria, the section is **mandatory** "
        "and must appear with its specified shape. Items that qualify for a "
        "priority section MUST NOT also appear in topic paragraphs or in any "
        "other priority section. Skip a section entirely if fewer than its "
        "`min` items qualify."
    )
    lines.append("")
    lines.append(
        "Order in the document: TL;DR → after_tldr sections (in array order) → "
        "topic paragraphs interleaved with topic sections → after_topics sections "
        "(in array order) → pipeline-appended \"Also in today's feed\"."
    )
    lines.append("")

    for placement_key in ("after_tldr", "topic", "after_topics"):
        for s in by_placement[placement_key]:
            name = s.get("name") or "(unnamed section)"
            placement_text = _PLACEMENT_DESCRIPTIONS[placement_key]
            when = s.get("when") or "(no criteria specified — skip if unclear)"
            shape = s.get("shape") or "paragraph, prose, cite items inline as `[Title](link)`"
            mn = int(s.get("min", 1))
            mx = int(s.get("max", 5))
            lines.extend([
                f"### {name}",
                f"- **Placement**: {placement_text}",
                f"- **When**: {when}",
                f"- **Shape**: {shape}",
                f"- **Items**: {mn}–{mx}; skip section entirely if fewer than {mn} qualifying items exist today",
                "",
            ])

    return "\n".join(lines).rstrip() + "\n"
