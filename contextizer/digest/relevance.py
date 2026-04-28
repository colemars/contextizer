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
_MAX_PER_SOURCE_RATIO = 0.20

# Sources sharing a publisher counted as one bucket for the per-source cap —
# otherwise multi-feed publishers (arXiv cs.AI/cs.CL/cs.LG, HN Front/AI/Security)
# silently dominate the digest.
_SOURCE_BUCKET_PREFIXES = ("arXiv ", "HN ")


def score_items(
    items: list[Item],
    keywords: ProfileKeywords,
    limit: int,
    max_per_source_ratio: float = _MAX_PER_SOURCE_RATIO,
) -> list[ScoredItem]:
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
    return _cap_per_source(scored, limit, max_per_source_ratio)


def _cap_per_source(
    scored: list[ScoredItem], limit: int, max_per_source_ratio: float
) -> list[ScoredItem]:
    if limit <= 0 or max_per_source_ratio <= 0 or not scored:
        return scored[:limit]
    per_source_cap = max(1, math.ceil(limit * max_per_source_ratio))
    kept: list[ScoredItem] = []
    counts: dict[str, int] = {}
    for s in scored:
        if len(kept) >= limit:
            break
        bucket = _source_bucket(s.item.source or "")
        if counts.get(bucket, 0) >= per_source_cap:
            continue
        kept.append(s)
        counts[bucket] = counts.get(bucket, 0) + 1
    return kept


def _source_bucket(source: str) -> str:
    for prefix in _SOURCE_BUCKET_PREFIXES:
        if source.startswith(prefix):
            return prefix.rstrip()
    return source


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
