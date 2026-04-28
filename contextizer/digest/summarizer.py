from __future__ import annotations

import logging
import shlex
import subprocess
from collections import defaultdict
from typing import Protocol

from ..models import ScoredItem

log = logging.getLogger(__name__)


class SummarizerError(RuntimeError):
    """Raised when the LLM summarizer cannot produce a digest body."""


class Summarizer(Protocol):
    def summarize(self, items: list[ScoredItem], profile_text: str, prompt: str) -> str: ...


class StubSummarizer:
    """No-LLM summarizer: groups scored items into a readable markdown digest."""

    def summarize(self, items: list[ScoredItem], profile_text: str, prompt: str) -> str:
        if not items:
            return "_No items matched your profile today._\n"

        groups: dict[str, list[ScoredItem]] = defaultdict(list)
        for s in items:
            groups[s.group].append(s)

        ordered_groups = sorted(
            groups.items(),
            key=lambda kv: max(s.score for s in kv[1]),
            reverse=True,
        )

        parts: list[str] = []
        for group, group_items in ordered_groups:
            parts.append(f"## {group}\n")
            for s in group_items:
                item = s.item
                date_str = item.published.strftime("%Y-%m-%d") if item.published else ""
                meta = item.source + (f" · {date_str}" if date_str else "")
                parts.append(f"- [{item.title}]({item.link}) — _{meta}_")
                if item.summary:
                    snippet = item.summary.strip()
                    if len(snippet) > 240:
                        snippet = snippet[:237] + "..."
                    parts.append(f"  - {snippet}")
                why = _why_it_matters(s)
                if why:
                    parts.append(f"  - **Why it may matter:** {why}")
                parts.append("")
            parts.append("")

        return "\n".join(parts).rstrip() + "\n"


class LLMSummarizer:
    """Pipes the rendered prompt to a local CLI (e.g. `claude -p`, `llm`, `ollama run <model>`)."""

    def __init__(self, command: str, timeout: int = 600) -> None:
        if not command:
            raise ValueError("LLM_COMMAND must be set for LLMSummarizer")
        self.command = command
        self.timeout = timeout

    def summarize(self, items: list[ScoredItem], profile_text: str, prompt: str) -> str:
        argv = shlex.split(self.command)
        log.info("Invoking LLM: %s", argv)
        try:
            result = subprocess.run(
                argv,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            log.error("LLM call failed: %s", e)
            raise SummarizerError(f"LLM call failed: {e}") from e

        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-500:]
            log.error("LLM exited %d: %s", result.returncode, stderr_tail)
            raise SummarizerError(
                f"LLM exited {result.returncode}: {stderr_tail}"
            )

        return result.stdout.strip() + "\n"


def build_summarizer(kind: str, llm_command: str | None, timeout: int = 600) -> Summarizer:
    kind = kind.lower()
    if kind == "stub":
        return StubSummarizer()
    if kind == "llm":
        if not llm_command:
            raise ValueError("LLM_COMMAND must be set when SUMMARIZER=llm")
        return LLMSummarizer(llm_command, timeout=timeout)
    raise ValueError(f"Unknown summarizer: {kind}")


def _why_it_matters(s: ScoredItem) -> str:
    topic_matches = [m for m in s.matched_keywords if not m.startswith("domain:")]
    domain_matches = [m[len("domain:") :] for m in s.matched_keywords if m.startswith("domain:")]
    reasons: list[str] = []
    if topic_matches:
        reasons.append("matches " + ", ".join(f"`{m}`" for m in topic_matches[:3]))
    if domain_matches:
        reasons.append("from priority source " + ", ".join(domain_matches[:2]))
    return "; ".join(reasons)
