# Humanize PPT source

This directory is a packaged mirror of the Humanize PPT skill for the Carl Skills collection.

## Source of truth

- Canonical repo: https://github.com/LearnPrompt/humanize-ppt
- Collection repo: https://github.com/LearnPrompt/carl-skills
- Sync mode: packaged-mirror
- Agent installable from collection: true

## Mirrored version

- Source commit: `bc172e0ade41ed66c9d3de022cc805c2f17830bc`
- Source summary: `bc172e0 2026-05-15T17:20:53+08:00 Hide unstable demos and add skill share showcase`
- Mirrored on: 2026-05-16

## Sync rule

`LearnPrompt/humanize-ppt` remains the canonical repo for demo, issues, releases, and public presentation.

`LearnPrompt/carl-skills` keeps a copy of `SKILL.md` so the collection is directly installable by Hermes Agent:

```bash
hermes skills install https://raw.githubusercontent.com/LearnPrompt/carl-skills/main/skills/content/humanize-ppt/SKILL.md --yes
```

When Humanize PPT changes in a meaningful way, update this mirror by copying the canonical `SKILL.md` and refreshing `registry.json`.
