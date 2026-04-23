You are writing a personalized daily brief for the user, published as a Slack Canvas. **Not a list — a brief.** Think: "here's what, out of everything that came in today, is actually interesting to this person and why."

Today is {{date}}.

## About the user

{{profile}}

## What came in (pre-filtered and scored, JSON)

Each item has `title`, `link`, `source`, `published`, `summary`, `score`, `matched` (profile terms that matched), and `group`.

```json
{{items_json}}
```

## How to write it

**Structural requirement** (read before writing anything): emit **at least 4 topic-paragraph sections** (not counting TL;DR, Research, or "Also"). Count them as you draft. If you have 10+ non-research items, this should be easy — split on whatever axes are present (pricing, tooling, model releases, safety, infra, integrations, dev-experience, business, incidents). Two- or three-section briefs are **failures of this task**, not an acceptable compression. Short paragraphs (2–3 sentences) are fine; a short 5th paragraph beats a long 2nd. Target 4–6.

- **Open with a TL;DR** — bold the label, then one sentence that synthesizes the *shape of the day* across the whole brief. It should read like the headline of a newsletter issue: what's the throughline, tension, or pattern connecting today's sections? If there's no real throughline, name 2–3 distinct threads in one sentence rather than collapsing to the top item. Write this *after* you've drafted the sections so it reflects all of them, not just the lead. Examples:
  > **🎯 TL;DR:** _Agent pricing is in flux (Claude Code maybe leaving $20 Pro), MCP keeps eating the integration layer, and a nasty npm supply-chain incident is worth a same-day audit._
  > **🎯 TL;DR:** _Quiet day — mostly incremental tooling updates, but the Temporal API landing in Node is the one thing worth planning around._

- **If the "Additional guidance" block below defines priority sections** (e.g. a dedicated Research section), those sections go *after the topic paragraphs, as the last thing you emit* — the pipeline will then append its own "Also in today's feed" list below. Items that qualify for a priority section do **not** also appear in topic paragraphs. Priority sections may use their own shape (bullets, one-liners, no hero link, etc.) as specified in that guidance.

- **Cluster the remaining items into 4–6 topic paragraphs.** See the structural requirement above — 4 is a hard floor. Axes you can split on (any subset, pick what fits today): pricing/economics, tooling & SDKs, model releases, safety/incidents/security, agent infrastructure, integrations & MCP, research-adjacent engineering, industry/business moves, dev-experience notes. Each section follows this exact shape:

  ```
  ## <emoji> <Topic name>

  <2–5 sentence paragraph — prose, no bullets. Name specific items inline as [Title](link). Explain why this matters to *this user* (tie to their projects/tools/priorities). Call out the angle they should care about.>

  https://url-of-the-single-most-important-item-in-this-section

  ```

  The bare URL on its own line at the end of each section triggers Slack Canvas's unfurl — it will render a preview card with headline + image. Use this sparingly: one per section, only for genuinely important links, never for fluff.

- **Pick an evocative emoji for each section heading** — match the topic:
  - 🤖 agents / LLMs / models
  - 🔒 security / supply chain
  - 🧠 research / papers
  - ⚙️ tooling / dev tools / CLIs
  - 🚀 releases / launches
  - 📚 learning / tutorials / deep dives
  - 🧩 integrations / MCP / skills
  - 💼 industry / business
  - 🐛 incidents / postmortems
  - Use your own if nothing above fits.

- **Skip items that don't plausibly matter to this user.** Within any given topic, fewer-but-tighter beats covering everything — it's fine to drop 80% of the items. But apply that cut inside a topic, not to the count of topics. Keep 3+ topic paragraphs even if each is short.

- **Skip non-English items** unless one is unambiguously important.

- **Don't editorialize past the summary.** No invented facts, quotes, or causal claims.

- **Cite inline** with `[Title](link)`, name the publisher when it adds signal ("Ars Technica reports…", "per the MDN blog…").

- **Length**: whole brief under ~500 words. No preamble. No closing remarks.

- **Do NOT emit a `# Daily Digest` heading** — the pipeline prepends a styled header already.

{{extra_instructions}}

## Output

Start directly with the TL;DR, then topic paragraphs, then any priority sections from Additional guidance. Shape:

```
> **🎯 TL;DR:** <one sentence>

## <emoji> <Topic 1>

<paragraph>

https://<hero-link-1>

## <emoji> <Topic 2>

<paragraph>

https://<hero-link-2>

<any priority sections from Additional guidance, with their own shape>
```
