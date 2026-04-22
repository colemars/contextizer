from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    feeds_file: Path
    state_file: Path
    raw_output_type: str
    raw_output_path: Path
    digest_output_type: str
    digest_output_path: Path
    raw_input_type: str
    raw_input_path: Path
    profile_file: Path
    interests_file: Path
    poll_interval_minutes: int
    slack_webhook_url: str | None
    summarizer: str
    llm_command: str | None
    digest_prompt_file: Path
    onboarding_prompt_file: Path
    log_level: str
    max_items_for_digest: int
    filter_non_english: bool
    slack_bot_token: str | None
    slack_canvas_notify_channel: str | None
    digest_css_file: Path
    digest_banner_url: str | None
    runners_up_count: int


def load(project_root: Path | None = None) -> Config:
    root = project_root or Path.cwd()
    load_dotenv(root / ".env")

    raw_out_type = os.environ.get("RAW_OUTPUT_TYPE", "jsonl")
    raw_out_path = os.environ.get("RAW_OUTPUT_PATH", "data/raw/{group}.jsonl")

    return Config(
        feeds_file=_path(root, "FEEDS_FILE", "data/feeds.json"),
        state_file=_path(root, "STATE_FILE", "data/seen_items/{group}.json"),
        raw_output_type=raw_out_type,
        raw_output_path=_path(root, "RAW_OUTPUT_PATH", raw_out_path),
        digest_output_type=os.environ.get("DIGEST_OUTPUT_TYPE", "markdown"),
        digest_output_path=_path(root, "DIGEST_OUTPUT_PATH", "data/digests/{group}"),
        raw_input_type=os.environ.get("RAW_INPUT_TYPE", raw_out_type),
        raw_input_path=_path(root, "RAW_INPUT_PATH", raw_out_path),
        profile_file=_path(root, "PROFILE_FILE", "data/user_profile.md"),
        interests_file=_path(root, "INTERESTS_FILE", "data/interests.json"),
        poll_interval_minutes=int(os.environ.get("POLL_INTERVAL_MINUTES", "30")),
        slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL") or None,
        summarizer=os.environ.get("SUMMARIZER", "stub"),
        llm_command=os.environ.get("LLM_COMMAND") or None,
        digest_prompt_file=_path(root, "DIGEST_PROMPT_FILE", "templates/digest_prompt.md"),
        onboarding_prompt_file=_path(root, "ONBOARDING_PROMPT_FILE", "templates/onboarding_prompt.md"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        max_items_for_digest=int(os.environ.get("MAX_ITEMS_FOR_DIGEST", "40")),
        filter_non_english=_bool(os.environ.get("FILTER_NON_ENGLISH"), default=True),
        slack_bot_token=os.environ.get("SLACK_BOT_TOKEN") or None,
        slack_canvas_notify_channel=os.environ.get("SLACK_CANVAS_NOTIFY_CHANNEL") or None,
        digest_css_file=_path(root, "DIGEST_CSS_FILE", "templates/digest.css"),
        digest_banner_url=os.environ.get("DIGEST_BANNER_URL") or None,
        runners_up_count=int(os.environ.get("RUNNERS_UP_COUNT", "12")),
    )


def _bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path(root: Path, env_key: str, default: str) -> Path:
    raw = os.environ.get(env_key, default)
    p = Path(raw)
    return p if p.is_absolute() else root / p


def for_group(
    cfg: Config,
    group: str,
    profile_override: Path | None = None,
    interests_override: Path | None = None,
) -> Config:
    """Return a Config with `{group}` substituted in templated paths."""
    return replace(
        cfg,
        state_file=_sub(cfg.state_file, group),
        raw_output_path=_sub(cfg.raw_output_path, group),
        raw_input_path=_sub(cfg.raw_input_path, group),
        digest_output_path=_sub(cfg.digest_output_path, group),
        profile_file=profile_override or cfg.profile_file,
        interests_file=interests_override or cfg.interests_file,
    )


def _sub(p: Path, group: str) -> Path:
    s = str(p)
    return Path(s.replace("{group}", group)) if "{group}" in s else p
