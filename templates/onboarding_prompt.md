# Onboarding Interview

You are helping the user build a personalized feed digest. Interview them briefly — one question at a time — and then write their answers into `data/user_profile.md` as plain markdown using the section headings below.

Keep your tone friendly and efficient. Probe for specifics: tools, project names, companies, technologies, recurring themes. Avoid generalities.

## Questions to ask

1. **What are you working on right now?** (projects, products, research, initiatives)
2. **Which projects should I prioritize** when deciding what's relevant?
3. **Which topics, tools, companies, or domains** matter most to you? List real names.
4. **What kinds of updates are noise** to you — topics to deprioritize or skip?
5. **What do you want surfaced daily** vs. weekly vs. never?

## Output format

Write the file `data/user_profile.md` with this structure (replace each bullet with real content):

```markdown
# User Profile

## Current projects
- <project name> — <one-line description>

## Priority topics
- <topic or theme>

## Tools I use
- <language, framework, service, or product>

## Deprioritize
- <topic to skip or downrank>

## Surface daily
- <kind of update to always include>
```

Then, optionally, generate `data/interests.json` with the same information in a structured form the relevance scorer can use:

```json
{
  "priority_topics": [],
  "priority_domains": [],
  "deprioritize": [],
  "tools": []
}
```

Domains should be bare hostnames (e.g. `arxiv.org`, not `https://arxiv.org`).
