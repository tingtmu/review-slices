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

Dependencies depend on the review level and whether a review meeting is needed:

- [`code-review`](https://github.com/mattpocock/skills) is required by the current procedure for Important and
  Critical changes. Without it, Trivial and Simple changes can still follow the procedure, provided Simple
  changes have an independent reviewer. Important and Critical reviews need the skill installed or an explicit
  decision from the user about how to proceed; there is no automatic substitute defined for `code-review`.
- Orca's [`orca-cli`](https://github.com/stablyai/orca/blob/main/skills/orca-cli/SKILL.md) and
  [`orchestration`](https://github.com/stablyai/orca/blob/main/skills/orchestration/SKILL.md) skills are needed
  only for optional review meetings, along with a running Orca app. Without Orca, ordinary reviews at every
  level can still run using independent agent reviewers. A disputed Critical finding must go to the user if
  a review meeting is unavailable.

If fresh-context agent reviewers are unavailable, the procedure falls back to a read-only CLI reviewer, then
an Orca terminal if available, then asking the user. The author must not review its own work as Slice 2.
The Python guard needs neither dependency: it checks pass stamps and review trailers, not whether reviewers
actually ran or these tools are installed.

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
