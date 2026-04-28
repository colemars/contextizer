"""Unit tests for LLMSummarizer failure modes — timeout and non-zero exit
must raise SummarizerError so the digest run aborts before any sink is
invoked, rather than silently publishing a degraded fallback.

Run with:
    .venv/bin/python -m unittest tests.test_summarizer -v
"""

from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from contextizer.digest.summarizer import LLMSummarizer, SummarizerError


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class LLMSummarizerFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summarizer = LLMSummarizer("claude -p", timeout=1)

    def test_timeout_raises_summarizer_error(self):
        with mock.patch(
            "contextizer.digest.summarizer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude -p", timeout=1),
        ):
            with self.assertRaises(SummarizerError) as ctx:
                self.summarizer.summarize([], "profile", "prompt")
        self.assertIn("LLM call failed", str(ctx.exception))

    def test_missing_binary_raises_summarizer_error(self):
        with mock.patch(
            "contextizer.digest.summarizer.subprocess.run",
            side_effect=FileNotFoundError(2, "no such file", "claude"),
        ):
            with self.assertRaises(SummarizerError):
                self.summarizer.summarize([], "profile", "prompt")

    def test_non_zero_exit_raises_summarizer_error_with_stderr(self):
        fake = _FakeCompleted(returncode=1, stdout="", stderr="boom: bad credentials\n")
        with mock.patch(
            "contextizer.digest.summarizer.subprocess.run", return_value=fake
        ):
            with self.assertRaises(SummarizerError) as ctx:
                self.summarizer.summarize([], "profile", "prompt")
        msg = str(ctx.exception)
        self.assertIn("exited 1", msg)
        self.assertIn("boom: bad credentials", msg)

    def test_success_returns_stdout(self):
        fake = _FakeCompleted(returncode=0, stdout="real digest body")
        with mock.patch(
            "contextizer.digest.summarizer.subprocess.run", return_value=fake
        ):
            out = self.summarizer.summarize([], "profile", "prompt")
        self.assertEqual(out, "real digest body\n")


class DigestEngineAbortsBeforeSinkTests(unittest.TestCase):
    """When the LLM summarizer fails, run_digest must propagate the error
    before write_digest/close are called on the sink — otherwise we publish
    a stub fallback to Slack as if nothing went wrong."""

    def test_summarizer_failure_skips_sink(self):
        from datetime import datetime, timezone

        from contextizer.digest import engine

        sink = mock.Mock()

        cfg = mock.Mock()
        cfg.raw_input_type = "jsonl"
        cfg.raw_input_path = "/tmp/missing.jsonl"
        cfg.digested_state_file = "/tmp/digested.json"
        cfg.filter_non_english = False
        cfg.profile_file = "/tmp/profile.md"
        cfg.interests_file = "/tmp/interests.json"
        cfg.max_items_for_digest = 25
        cfg.digest_prompt_file = "/tmp/prompt.md"
        cfg.digest_extra_instructions = ""
        cfg.digest_sections = []
        cfg.summarizer = "llm"
        cfg.llm_command = "claude -p"
        cfg.digest_include_header = False
        cfg.runners_up_count = 0

        with mock.patch.object(engine, "load_items", return_value=[]), \
             mock.patch.object(engine, "load_profile") as load_profile, \
             mock.patch.object(engine, "score_items", return_value=[]), \
             mock.patch.object(engine, "render_digest_prompt", return_value="prompt"), \
             mock.patch.object(engine, "build_summarizer") as build_sum:
            load_profile.return_value = mock.Mock(text="profile", keywords=[])
            failing = mock.Mock()
            failing.summarize.side_effect = SummarizerError("LLM call failed: timeout")
            build_sum.return_value = failing

            with self.assertRaises(SummarizerError):
                engine.run_digest(cfg, sink, since=datetime.now(timezone.utc))

        sink.write_digest.assert_not_called()
        sink.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
