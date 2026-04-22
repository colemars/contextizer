---
name: build-interests
description: Build or refine an interests JSON file that drives RSS digest relevance scoring in this repo. Trigger when the user wants to create, update, or refine their interests — e.g. "build interests from this prompt", "update my interests", "add MCP to my interests", "make a new interests file for the frontend group", "refine what topics get prioritized", or when they paste a blurb about themselves and ask to turn it into interests. Handles both the shared `data/interests.json` and per-group `data/interests_<group>.json`, and wires new per-group files into `data/feeds.json`.
---

# build-interests

Create or refine the structured interests file that `contextizer/digest/relevance.py` uses to pre-filter and score items.

## Files

| File | Role |
|---|---|
| `data/interests.json` | Shared defaults; applies to any group that doesn't override. |
| `data/interests_<group>.json` | Per-group override, referenced from `data/feeds.json`. |
| `data/user_profile.md` | Markdown context about the user (for LLM prompt, not scoring). |
| `data/feeds.json` | Group definitions; each group can set `"interests": "data/interests_<group>.json"`. |

## Schema

Every interests file has exactly these four keys:

```json
{
  "priority_topics": ["..."],
  "priority_domains": ["..."],
  "deprioritize": ["..."],
  "tools": ["..."]
}
```

Rules:
- All values are arrays of strings. No nulls, no extra keys.
- `priority_domains` must be **bare hostnames** (`arxiv.org`, not `https://arxiv.org` or `www.arxiv.org`). Extract the hostname if the user gives a URL.
- `priority_topics` and `tools` are matched as case-insensitive substrings against item titles and summaries. Short distinctive terms work better — prefer `"MCP"` over `"Model Context Protocol"`, but include both if the user uses the long form in their world.
- `deprioritize` penalizes matches; put things the user explicitly called out as noise.
- De-dupe and sort each array before writing, for stable diffs.

## Workflow

1. **Pick the target file.**
   - Shared → `data/interests.json`.
   - Specific group `<group>` → `data/interests_<group>.json`.
   - If unclear, read `data/feeds.json` to list the existing groups, then ask.

2. **Read existing state.** If the target file exists, treat the request as a **refine**, not a rewrite. Preserve prior entries unless asked to remove them. Also read `data/user_profile.md` for background context — but do NOT copy prose from it into interests.

3. **Extract or interview.**
   - If the user's message already has enough signal (e.g. "add Python, Django, SQLAlchemy to tools"), apply directly.
   - Otherwise ask a short, targeted set — not a generic onboarding. Examples:
     - "What specific projects or products should rank higher?"
     - "Any authoritative sites you want boosted?"
     - "Any topics you want actively downranked?"
     - "Which tools are part of your daily stack?"
   - One question at a time; stop as soon as you have enough.

4. **Write.** Merge with existing entries, dedupe, sort each array, indent 2, trailing newline.

5. **Wire per-group files into `feeds.json`.** If the file is `data/interests_<group>.json` and the corresponding group in `data/feeds.json` does not already have an `"interests"` field, add it. If the group doesn't exist in `feeds.json` at all, stop and tell the user — they need to define the group's feeds first.

6. **Show the diff.** Report added/removed entries per field so the user can confirm.

7. **Offer to regenerate the digest** for that group so the user can see the new scoring immediately:
   ```bash
   .venv/bin/python main.py digest --today --group <group>
   ```

## Examples

**"Add MCP and agent to my shared interests."**
→ Read `data/interests.json`, add both to `priority_topics` if absent, write, diff. No group wiring needed.

**"Build interests for a new `bio` group — bioinformatics, genomics, protein folding. Downrank crypto."**
→ Confirm `bio` group exists in `feeds.json` (or prompt the user to add its feeds first). Write `data/interests_bio.json` with:
```json
{
  "priority_topics": ["bioinformatics", "genomics", "protein folding"],
  "priority_domains": [],
  "deprioritize": ["crypto"],
  "tools": []
}
```
Add `"interests": "data/interests_bio.json"` to the `bio` group in `feeds.json`. Show diff. Offer to regenerate.

**"Here's a paragraph about me — build interests from it."**
→ Parse the paragraph for concrete nouns. Classify each as topic / tool / domain. Ask one follow-up if something's ambiguous (e.g. "you mentioned Stripe — prioritize topic or tool?"). Write, diff, offer regeneration.

## Anti-patterns

- Don't include full URLs in `priority_domains` — bare hostnames only.
- Don't put long sentences or questions in `priority_topics` — short keywords only.
- Don't overwrite existing entries the user didn't ask to change.
- Don't put narrative prose ("I work on X at Y") in interests.json — that belongs in `user_profile.md`.
- Don't wire the new file into `feeds.json` via `settings.json` or hooks. It's a data file.
