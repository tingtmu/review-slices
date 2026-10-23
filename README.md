# review-slices

An agent skill for checking an agent's work before it counts as done, built on the Swiss cheese model: several
imperfect slices (shown output, the full suite with a pass stamp, review scaled by a computed review level, the
user's go-ahead, acceptance), and an incident log whose plugs harden the slices each time something gets through.

Works with Claude Code and Codex. The skill is in [skills/review-slices/](skills/review-slices/SKILL.md); its terms
are in [GLOSSARY.md](skills/review-slices/GLOSSARY.md).

## Install

```sh
npx skills add tingtmu/review-slices -g -a claude-code codex
```

Optional dependencies: [`code-review`](https://github.com/mattpocock/skills) (Important and Critical levels) and the
Orca `orca-cli` and `orchestration` skills (review meetings only).

## Set up a repo

Ask your agent to "set up review-slices in this repo". It copies the templates and the guard, then:

```sh
git config core.hooksPath .githooks   # once per clone: the pre-push guard
python3 .githooks/review_slices.py level       # review level of your changes, and the trailer to write
python3 .githooks/review_slices.py run-suite   # the full suite, once per pushed tree; stamps a pass
```

The guard needs Python 3.8+ and git 2.31+, and nothing else.

## Versions

`0.1.0`: first release, 2026-10-23.
