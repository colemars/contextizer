# Contributing

Thanks for considering a contribution. contextizer is small on purpose — this guide
should be enough to get you productive quickly.

## Setup

```bash
script/setup     # venv + deps + starter .env + starter profile
script/test      # smoke tests: byte-compile, imports, CLI help, feeds.json parse
```

`script/setup` is idempotent, so re-run it any time. After pulling new changes:

```bash
script/update    # re-sync dependencies
```

Requires Python 3.11+.

## Running tests

```bash
script/test
```

CI runs the same script against Python 3.11 and 3.12 on push and PR.

## Adding a new source

Sources are where Items come from — RSS feeds today, Slack channels today,
GitHub notifications / Linear / whatever tomorrow. The shape is narrow on
purpose: any object with a `name: str` and a `fetch() -> list[Item]` method
satisfies the `Source` protocol in [contextizer/collector/feeds.py](contextizer/collector/feeds.py).

1. Add your implementation at `contextizer/collector/<your_source>.py`. The
   `RssSource` dataclass at the top of [feeds.py](contextizer/collector/feeds.py)
   and `SlackChannelSource` in [slack.py](contextizer/collector/slack.py) are the
   reference patterns — the latter also shows how to paginate, rate-limit, and
   degrade gracefully on missing credentials.

2. Add a `<type>_source_from_config(entry: dict) -> Source | None` factory in
   the same module. Return `None` with a clear `log.warning` if required
   env/config is missing — don't crash the whole collect cycle.

3. Wire it into the `_parse_one` dispatch in
   [contextizer/collector/feeds.py](contextizer/collector/feeds.py) by adding
   a branch for your `type` value, imported lazily so pure-RSS users don't
   pay for modules they don't need.

4. If the source needs new env config, add it to `contextizer/config.py` and
   document it in `.env.example` + the "Sources beyond RSS" section of the
   README.

5. Add unit tests under `tests/` covering normalization edge cases and any
   graceful-degrade paths. Mock HTTP — don't hit live APIs in CI.

## Adding a new sink

Sinks are the pluggable delivery layer — everything from local files to Slack
canvases is a sink. Adding one is usually a single new file plus two lines
elsewhere.

1. Add your implementation at `contextizer/sinks/<your_sink>.py`. It should
   match either the `ItemSink` or `DigestSink` protocol in
   [contextizer/sinks/base.py](contextizer/sinks/base.py):

   ```python
   class DigestSink(Protocol):
       def write_digest(self, digest: Digest) -> None: ...
       def close(self) -> None: ...
   ```

2. Register it in the `build_item_sink` or `build_digest_sink` factory in
   the same `base.py`. Raise a clear error if required config is missing.

3. If the sink needs new config, add it to `contextizer/config.py` and
   document the env var in `.env.example`.

4. Add the sink module name to `script/test`'s import check
   (the block that does `from contextizer.sinks import ...`).

5. Open a PR. Keep the sink focused — one destination, no branching on
   output format inside the sink.

## Style

- No new runtime dependencies unless the feature fundamentally needs one.
- Prefer functions and dataclasses over classes with state.
- Error messages should tell the user what to do (`"SLACK_BOT_TOKEN must be
  set to use slack_canvas sink"`), not just what went wrong.

## Reporting bugs / ideas

Open an issue with a minimal repro — the feed URL, the sink type, the relevant
`.env` values, and the log output. Redact tokens.
