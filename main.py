#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import re
import shutil
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contextizer import logging_config
from contextizer.collector.feeds import FeedGroup, fetch_all, load_groups
from contextizer.collector.state import SeenStore
from contextizer.config import Config, for_group, load as load_config
from contextizer.digest.engine import run_digest
from contextizer.sinks.base import build_digest_sink, build_item_sink

log = logging.getLogger("contextizer")


def cmd_collect(cfg: Config, args: argparse.Namespace) -> int:
    groups = load_groups(cfg.feeds_file)
    targets = _select_groups(groups, args.group)

    if args.loop:
        _run_loop(cfg, targets)
    else:
        _collect_all(cfg, targets)
    return 0


def _collect_all(cfg: Config, groups: dict[str, FeedGroup]) -> int:
    total_new = 0
    for name, group in groups.items():
        log.info("=== collecting group %r (%d feeds) ===", name, len(group.feeds))
        total_new += _collect_group(cfg, group)
    return total_new


def _collect_group(cfg: Config, group: FeedGroup) -> int:
    gcfg = for_group(cfg, group.name, group.profile_file, group.interests_file)
    seen = SeenStore(gcfg.state_file)
    sink = build_item_sink(gcfg.raw_output_type, gcfg)

    new_count = 0
    total = 0
    try:
        for item in fetch_all(group.feeds):
            total += 1
            if seen.contains(item):
                continue
            sink.write_item(item)
            seen.add(item)
            new_count += 1
    finally:
        sink.close()
        seen.save()

    log.info(
        "Group %r: %d new / %d total (%d seen)", group.name, new_count, total, len(seen)
    )
    return new_count


def _run_loop(cfg: Config, groups: dict[str, FeedGroup]) -> None:
    stop = {"flag": False}

    def _handler(signum, frame):
        log.info("Received signal %s, stopping loop", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    interval = cfg.poll_interval_minutes * 60
    while not stop["flag"]:
        try:
            _collect_all(cfg, groups)
        except Exception as e:
            log.exception("Collect cycle failed: %s", e)
        log.info("Sleeping %d minutes", cfg.poll_interval_minutes)
        for _ in range(interval):
            if stop["flag"]:
                break
            time.sleep(1)


def cmd_digest(cfg: Config, args: argparse.Namespace) -> int:
    groups = load_groups(cfg.feeds_file)
    name = _require_single_group(groups, args.group)
    group = groups[name]

    gcfg = for_group(cfg, name, group.profile_file, group.interests_file)
    gcfg = _apply_input_override(gcfg, args)

    since = _parse_since(args)
    sink = build_digest_sink(gcfg.digest_output_type, gcfg)
    digest = run_digest(gcfg, sink, since)
    log.info("Digest for group %r written with %d items", name, digest.item_count)
    return 0


def _select_groups(groups: dict[str, FeedGroup], name: str | None) -> dict[str, FeedGroup]:
    if name is None:
        return groups
    if name not in groups:
        raise SystemExit(f"unknown group: {name!r} (have: {', '.join(groups)})")
    return {name: groups[name]}


def _require_single_group(groups: dict[str, FeedGroup], name: str | None) -> str:
    if name is not None:
        if name not in groups:
            raise SystemExit(f"unknown group: {name!r} (have: {', '.join(groups)})")
        return name
    if len(groups) == 1:
        return next(iter(groups))
    raise SystemExit(
        f"multiple groups defined ({', '.join(groups)}); pass --group NAME"
    )


def _apply_input_override(cfg: Config, args: argparse.Namespace) -> Config:
    if not args.input:
        return cfg
    input_path = Path(args.input)
    kind = "directory" if input_path.is_dir() else "jsonl"
    from dataclasses import replace

    return replace(cfg, raw_input_type=kind, raw_input_path=input_path)


def _parse_since(args: argparse.Namespace) -> datetime | None:
    now = datetime.now(timezone.utc)
    if args.today:
        return now - timedelta(hours=24)
    if args.since:
        delta = _parse_duration(args.since)
        if delta is None:
            raise SystemExit(f"invalid --since value: {args.since} (use e.g. 24h, 3d)")
        return now - delta
    return None


def _parse_duration(s: str) -> timedelta | None:
    m = re.fullmatch(r"\s*(\d+)\s*([hdm])\s*", s, re.IGNORECASE)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit == "h":
        return timedelta(hours=n)
    if unit == "d":
        return timedelta(days=n)
    if unit == "m":
        return timedelta(minutes=n)
    return None


def cmd_onboard(cfg: Config, args: argparse.Namespace) -> int:
    if args.print_template:
        if not cfg.onboarding_prompt_file.exists():
            print(f"onboarding template not found: {cfg.onboarding_prompt_file}", file=sys.stderr)
            return 1
        sys.stdout.write(cfg.onboarding_prompt_file.read_text(encoding="utf-8"))
        return 0

    if args.init:
        _init_profile(cfg)
        return 0

    print("specify --print-template or --init", file=sys.stderr)
    return 2


def _init_profile(cfg: Config) -> None:
    cfg.profile_file.parent.mkdir(parents=True, exist_ok=True)
    if cfg.profile_file.exists():
        print(f"profile already exists at {cfg.profile_file}; not overwriting")
    else:
        skeleton = (
            "# User Profile\n\n"
            "## Current projects\n- \n\n"
            "## Priority topics\n- \n\n"
            "## Tools I use\n- \n\n"
            "## Deprioritize\n- \n\n"
            "## Surface daily\n- \n"
        )
        cfg.profile_file.write_text(skeleton, encoding="utf-8")
        print(f"wrote skeleton profile to {cfg.profile_file}")

    target = cfg.profile_file.parent / cfg.onboarding_prompt_file.name
    if cfg.onboarding_prompt_file.exists() and not target.exists():
        shutil.copyfile(cfg.onboarding_prompt_file, target)
        print(f"copied onboarding prompt to {target}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="contextizer", description="Collect RSS items and digest them.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("collect", help="Fetch feeds and write new items to the configured sink.")
    pc.add_argument("--once", action="store_true", help="Run a single cycle (default).")
    pc.add_argument("--loop", action="store_true", help="Poll on POLL_INTERVAL_MINUTES forever.")
    pc.add_argument("--group", help="Collect a single group (default: all groups).")

    pd = sub.add_parser("digest", help="Generate a digest from collected items.")
    pd.add_argument("--today", action="store_true", help="Digest the last 24 hours.")
    pd.add_argument("--since", help="Lookback window, e.g. 48h, 3d, 90m.")
    pd.add_argument("--input", help="Override raw input path (file=jsonl, dir=directory).")
    pd.add_argument("--group", help="Group to digest (required if multiple groups are defined).")

    po = sub.add_parser("onboard", help="Profile/onboarding helpers.")
    po.add_argument("--print-template", action="store_true", help="Print the onboarding prompt.")
    po.add_argument("--init", action="store_true", help="Write a skeleton profile to data/.")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = load_config(Path(__file__).parent)
    logging_config.configure(cfg.log_level)

    if args.cmd == "collect":
        return cmd_collect(cfg, args)
    if args.cmd == "digest":
        return cmd_digest(cfg, args)
    if args.cmd == "onboard":
        return cmd_onboard(cfg, args)
    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
