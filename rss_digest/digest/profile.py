from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class ProfileKeywords:
    priority_topics: list[str] = field(default_factory=list)
    priority_domains: list[str] = field(default_factory=list)
    deprioritize: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)

    @property
    def positive_terms(self) -> list[str]:
        return [t.lower() for t in (self.priority_topics + self.tools)]

    @property
    def negative_terms(self) -> list[str]:
        return [t.lower() for t in self.deprioritize]


@dataclass
class Profile:
    text: str
    keywords: ProfileKeywords


def load_profile(profile_file: Path, interests_file: Path) -> Profile:
    text = profile_file.read_text(encoding="utf-8") if profile_file.exists() else ""
    if not text:
        log.warning("Profile file not found or empty: %s", profile_file)

    keywords = ProfileKeywords()
    if interests_file.exists():
        try:
            data = json.loads(interests_file.read_text(encoding="utf-8"))
            keywords = ProfileKeywords(
                priority_topics=list(data.get("priority_topics", [])),
                priority_domains=list(data.get("priority_domains", [])),
                deprioritize=list(data.get("deprioritize", [])),
                tools=list(data.get("tools", [])),
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not load interests file %s: %s", interests_file, e)

    return Profile(text=text, keywords=keywords)
