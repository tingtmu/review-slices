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

No other skill is required. Reviewers are fresh-context agents briefed from
[references/reviewer-briefs.md](skills/review-slices/references/reviewer-briefs.md):

- [`code-review`](https://github.com/mattpocock/skills) can stand in for the built-in Standards and Spec reviewers at
  Important and Critical, if it is installed.
- Orca's [`orca-cli`](https://github.com/stablyai/orca/blob/main/skills/orca-cli/SKILL.md) and
  [`orchestration`](https://github.com/stablyai/orca/blob/main/skills/orchestration/SKILL.md) skills, with a running
  Orca app, are needed only for optional review meetings. Without them, a disputed Critical review finding goes to
  the user.

If fresh-context agent reviewers are unavailable, the procedure falls back to a read-only CLI reviewer, then
an Orca terminal if available, then asking the user. The author must not review its own work as Slice 2.
The Python guard checks pass stamps and review trailers, not whether reviewers actually ran.

## Set up a repo

Ask your agent to "set up review-slices in this repo". It copies the templates and the guard, then:

```sh
git config core.hooksPath .githooks   # once per clone, only if it has no other hooks (see SKILL.md)
python3 .githooks/review_slices.py level       # review level of your changes, and the trailer to write
python3 .githooks/review_slices.py run-suite   # the full suite, once per pushed tree; stamps a pass
```

The guard needs Python 3.8+ and git 2.31+, and nothing else.

## Versions

`0.1.0`: first release, 2026-10-23.

`0.1.1`: tests for the guard (with the known 0.1.0 holes as expected failures), this repo reviewed with its
own skill, and setup that no longer sets `core.hooksPath` over existing hooks.

`0.2.0`: the guard checks tag pushes, refuses a push that deletes REVIEW.md, treats an unreadable REVIEW.md as
critical instead of deadlocking, ignores user git settings that hid paths or trailers, counts submodule updates,
reads `a, b` as two globs, runs every `test:` line, reports a changed suite, and lints the rules (`check`). The
procedure commits before review, asks the go-ahead before pushes and one-way doors, and ships its own Standards and
Spec reviewer briefs.
