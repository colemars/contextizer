"""Unit tests for the Slack source — message normalization, thread folding,
reply-count id, echo-loop filtering, permalink construction, and graceful
handling of not_in_channel.

Run with:
    .venv/bin/python -m unittest tests.test_slack_source -v
"""

from __future__ import annotations

import unittest

from contextizer.collector.normalize import (
    normalize_slack_text,
    slack_message_to_item,
)
from contextizer.collector.slack import SlackChannelSource


def _resolve_user_from_map(m: dict[str, str]):
    def _resolve(uid: str) -> str:
        return m.get(uid, "")

    return _resolve


class NormalizeSlackTextTests(unittest.TestCase):
    def test_plain_text_untouched(self):
        self.assertEqual(normalize_slack_text("hello world"), "hello world")

    def test_user_mention_with_label(self):
        self.assertEqual(normalize_slack_text("hey <@U123|alice> there"), "hey @alice there")

    def test_user_mention_resolved_via_callback(self):
        resolve = _resolve_user_from_map({"U123": "alice"})
        self.assertEqual(
            normalize_slack_text("hey <@U123>", resolve_user=resolve),
            "hey @alice",
        )

    def test_user_mention_unresolved_falls_back_to_id(self):
        self.assertEqual(normalize_slack_text("hey <@U999>"), "hey @U999")

    def test_channel_reference(self):
        self.assertEqual(
            normalize_slack_text("see <#C456|general>"),
            "see #general",
        )

    def test_link_with_label(self):
        self.assertEqual(
            normalize_slack_text("<https://example.com|docs>"),
            "docs (https://example.com)",
        )

    def test_bare_link(self):
        self.assertEqual(
            normalize_slack_text("<https://example.com>"),
            "https://example.com",
        )

    def test_special_mentions(self):
        self.assertEqual(normalize_slack_text("<!here> ping"), "@here ping")
        self.assertEqual(normalize_slack_text("<!channel>"), "@channel")

    def test_subteam_mention_with_label(self):
        self.assertEqual(
            normalize_slack_text("Hey <!subteam^S0A8GKZ50J2|backend>"),
            "Hey @backend",
        )

    def test_subteam_mention_without_label_falls_back_to_id(self):
        self.assertEqual(
            normalize_slack_text("Hey <!subteam^S0A8GKZ50J2>"),
            "Hey @S0A8GKZ50J2",
        )


class SlackMessageToItemTests(unittest.TestCase):
    def _base_kwargs(self):
        return dict(
            channel_id="C9999",
            channel_display_name="Slack #eng",
            permalink="https://t.slack.com/archives/C9999/p1700000000000000",
        )

    def test_simple_message_with_no_thread(self):
        msg = {"ts": "1700000000.000000", "text": "ship it", "user": "U1"}
        item = slack_message_to_item(msg, [], **self._base_kwargs())
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.title, "ship it")
        self.assertEqual(item.summary, "ship it")
        self.assertEqual(item.source, "Slack #eng")
        self.assertEqual(item.link, "https://t.slack.com/archives/C9999/p1700000000000000")
        self.assertEqual(item.guid, "C9999:1700000000.000000")

    def test_title_is_first_line(self):
        msg = {"ts": "1.1", "text": "HEADER\n\nbody continues here"}
        item = slack_message_to_item(msg, [], **self._base_kwargs())
        assert item is not None
        self.assertEqual(item.title, "HEADER")
        self.assertIn("body continues here", item.summary)

    def test_long_title_truncated(self):
        long_line = "x" * 300
        msg = {"ts": "1.1", "text": long_line}
        item = slack_message_to_item(msg, [], **self._base_kwargs())
        assert item is not None
        self.assertTrue(item.title.endswith("..."))
        self.assertLessEqual(len(item.title), 120)

    def test_thread_replies_folded_into_summary(self):
        msg = {"ts": "100.0", "text": "Proposal: ship feature X", "reply_count": 2}
        replies = [
            {"ts": "100.0", "text": "Proposal: ship feature X", "user": "U1"},  # root dup — skipped
            {"ts": "100.1", "text": "<@U2|bob> thoughts?", "user": "U1"},
            {"ts": "100.2", "text": "lgtm", "user": "U2"},
        ]
        resolve = _resolve_user_from_map({"U1": "alice", "U2": "bob"})
        item = slack_message_to_item(
            msg, replies, resolve_user=resolve, **self._base_kwargs()
        )
        assert item is not None
        self.assertIn("Proposal: ship feature X", item.summary)
        self.assertIn("---", item.summary)
        self.assertIn("@alice: @bob thoughts?", item.summary)
        self.assertIn("@bob: lgtm", item.summary)

    def test_reply_count_in_id_so_growing_threads_re_emit(self):
        base = {"ts": "200.0", "text": "hello"}
        item_no_replies = slack_message_to_item(
            {**base, "reply_count": 0}, [], **self._base_kwargs()
        )
        item_two_replies = slack_message_to_item(
            {**base, "reply_count": 2}, [], **self._base_kwargs()
        )
        assert item_no_replies is not None and item_two_replies is not None
        self.assertNotEqual(item_no_replies.id, item_two_replies.id)

    def test_empty_message_returns_none(self):
        msg = {"ts": "1.1", "text": ""}
        self.assertIsNone(slack_message_to_item(msg, [], **self._base_kwargs()))

    def test_summary_capped(self):
        msg = {"ts": "1.1", "text": "x" * 5000}
        item = slack_message_to_item(msg, [], **self._base_kwargs())
        assert item is not None
        self.assertLessEqual(len(item.summary), 2000)
        self.assertTrue(item.summary.endswith("..."))


class SlackChannelSourceFilteringTests(unittest.TestCase):
    """Exercise the small amount of policy logic that doesn't need HTTP."""

    def _source(self) -> SlackChannelSource:
        src = SlackChannelSource(
            name="Slack C1",
            channel_ref="C1",
            token="xoxb-fake",
        )
        # Simulate that _ensure_ready already populated the bot user id.
        src._bot_user_id = "UBOT"
        return src

    def test_top_level_accepts_standalone_message(self):
        src = self._source()
        self.assertTrue(src._is_top_level({"ts": "1.0", "text": "hi"}))

    def test_top_level_accepts_thread_root(self):
        src = self._source()
        # Thread root has thread_ts == ts.
        self.assertTrue(
            src._is_top_level({"ts": "1.0", "thread_ts": "1.0", "text": "hi", "reply_count": 3})
        )

    def test_top_level_rejects_thread_reply(self):
        src = self._source()
        self.assertFalse(
            src._is_top_level({"ts": "1.1", "thread_ts": "1.0", "text": "reply"})
        )

    def test_top_level_rejects_system_subtypes(self):
        src = self._source()
        for subtype in ("channel_join", "channel_leave", "bot_message", "channel_topic"):
            self.assertFalse(
                src._is_top_level({"ts": "1.0", "subtype": subtype}),
                f"{subtype} should be filtered",
            )

    def test_bot_echo_filter(self):
        src = self._source()
        self.assertTrue(src._is_bot_echo({"user": "UBOT"}))
        self.assertFalse(src._is_bot_echo({"user": "UHUMAN"}))

    def test_permalink_construction(self):
        src = self._source()
        src._team_domain = "myteam"
        src._channel_id = "C1"
        self.assertEqual(
            src._permalink("1700000000.000123"),
            "https://myteam.slack.com/archives/C1/p1700000000000123",
        )

    def test_permalink_empty_when_unconfigured(self):
        src = self._source()
        self.assertEqual(src._permalink("1.0"), "")


class SlackChannelSourceFilterTests(unittest.TestCase):
    """Per-source content filters: include_humans / include_bots /
    min_chars / include_pattern."""

    def _src(self, **overrides) -> SlackChannelSource:
        src = SlackChannelSource(
            name="Slack C1", channel_ref="C1", token="xoxb-fake", **overrides
        )
        src._bot_user_id = "UBOT_SELF"
        return src

    def test_default_excludes_bots(self):
        src = self._src()
        self.assertFalse(src._passes_filters({"bot_id": "B1", "text": "deploy"}))

    def test_include_bots_keeps_modern_app_bots(self):
        src = self._src(include_bots=True)
        self.assertTrue(src._passes_filters({"bot_id": "B1", "text": "deploy"}))

    def test_include_bots_also_keeps_bot_message_subtype(self):
        src = self._src(include_bots=True)
        self.assertTrue(
            src._passes_filters({"subtype": "bot_message", "text": "hook"})
        )

    def test_exclude_humans_drops_user_messages(self):
        src = self._src(include_humans=False, include_bots=True)
        self.assertFalse(src._passes_filters({"user": "U1", "text": "-> stg"}))
        self.assertTrue(src._passes_filters({"bot_id": "B1", "text": "release"}))

    def test_min_chars_threshold(self):
        src = self._src(min_chars=50)
        self.assertFalse(src._passes_filters({"user": "U1", "text": "short"}))
        self.assertTrue(
            src._passes_filters({"user": "U1", "text": "x" * 60})
        )

    def test_include_pattern_matches_substring(self):
        src = self._src(
            include_humans=False, include_bots=True, include_pattern="Release Notes"
        )
        self.assertTrue(
            src._passes_filters(
                {"bot_id": "B1", "text": "Release Notes for 1.2.3\nFixes..."}
            )
        )
        self.assertFalse(
            src._passes_filters({"bot_id": "B1", "text": "Deployed 1.2.3"})
        )

    def test_bad_include_pattern_disabled_not_crash(self):
        src = self._src(include_pattern="[unclosed")
        # Invalid regex gets logged and cleared; message passes.
        self.assertTrue(src._passes_filters({"user": "U1", "text": "anything"}))
        self.assertIsNone(src.include_pattern)


class SlackSourceConfigParsingTests(unittest.TestCase):
    """slack_source_from_config should gracefully degrade when
    SLACK_BOT_TOKEN is absent so the RSS path still runs."""

    def test_missing_token_returns_none(self):
        import os

        from contextizer.collector.slack import slack_source_from_config

        prior = os.environ.pop("SLACK_BOT_TOKEN", None)
        try:
            result = slack_source_from_config({"type": "slack", "channel": "C1"})
            self.assertIsNone(result)
        finally:
            if prior is not None:
                os.environ["SLACK_BOT_TOKEN"] = prior

    def test_missing_channel_returns_none(self):
        import os

        from contextizer.collector.slack import slack_source_from_config

        os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"
        try:
            self.assertIsNone(slack_source_from_config({"type": "slack"}))
        finally:
            os.environ.pop("SLACK_BOT_TOKEN", None)

    def test_builds_when_token_and_channel_present(self):
        import os

        from contextizer.collector.slack import slack_source_from_config

        os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"
        try:
            src = slack_source_from_config(
                {"type": "slack", "channel": "C1", "name": "Slack eng-announce"}
            )
            self.assertIsNotNone(src)
            assert src is not None
            self.assertEqual(src.channel_ref, "C1")
            self.assertEqual(src.name, "Slack eng-announce")
            self.assertTrue(src._name_explicit)
        finally:
            os.environ.pop("SLACK_BOT_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
