from __future__ import annotations

import math
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..models import Item, ScoredItem
from .profile import ProfileKeywords

_RECENCY_HALF_LIFE_HOURS = 24.0
_DOMAIN_BONUS = 2.0
_POSITIVE_WEIGHT = 1.5
_NEGATIVE_PENALTY = 3.0


def score_items(items: list[Item], keywords: ProfileKeywords, limit: int) -> list[ScoredItem]:
    now = datetime.now(timezone.utc)
    positive = keywords.positive_terms
    negative = keywords.negative_terms
    domains = [d.lower() for d in keywords.priority_domains]

    scored: list[ScoredItem] = []
    for item in items:
        text = f"{item.title}\n{item.summary}".lower()
        matches: list[str] = []

        score = 0.0
        for term in positive:
            if term and term in text:
                score += _POSITIVE_WEIGHT
                matches.append(term)
        for term in negative:
            if term and term in text:
                score -= _NEGATIVE_PENALTY

        host = (urlparse(item.link).hostname or "").lower()
        for d in domains:
            if d and d in host:
                score += _DOMAIN_BONUS
                matches.append(f"domain:{d}")

        score += _recency_bonus(item, now)

        group = _group_for(matches, item)
        scored.append(ScoredItem(item=item, score=score, matched_keywords=matches, group=group))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:limit]


def _recency_bonus(item: Item, now: datetime) -> float:
    ts = item.published or item.fetched_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - ts).total_seconds() / 3600.0)
    return math.exp(-hours / _RECENCY_HALF_LIFE_HOURS)


def _group_for(matches: list[str], item: Item) -> str:
    topic_match = next((m for m in matches if not m.startswith("domain:")), None)
    if topic_match:
        return topic_match.title()
    return item.source or "General"
