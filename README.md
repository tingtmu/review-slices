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

Ask your agent to "set up review-slices in this repo". It fills in the templates, then runs the skill's
`scripts/setup_tools.py install` (a dry run you approve, then `--apply`):

```sh
python3 .githooks/review_slices.py status      # the review level, the trailer to write, and the next step
python3 .githooks/review_slices.py run-suite   # every check in the suite, once per pushed tree; stamps a pass
python3 <skill>/scripts/setup_tools.py doctor  # is this clone's hook wired, and is the setup sound
```

`install` never sets `core.hooksPath`: on git 2.54+ it registers a config hook beside git-lfs, Husky or
pre-commit, and on older git it chains any pre-push hook already there. Each clone keeps a small bootstrap that
runs the guard committed on the base branch, so an edited copy never judges its own push and a fix to the guard
reaches every clone by push. Only clones that run `install` are checked; nobody else is blocked.

The guard needs Python 3.8+ and git 2.32+, and nothing else.

## Versions

`0.1.0`: first release, 2026-10-23.

`0.1.1`: tests for the guard (with the known 0.1.0 holes as expected failures), this repo reviewed with its
own skill, and setup that no longer sets `core.hooksPath` over existing hooks.

`0.2.0`: the guard checks tag pushes, refuses a push that deletes REVIEW.md, treats an unreadable REVIEW.md as
critical instead of deadlocking, ignores user git settings that hid paths or trailers, counts submodule updates,
reads `a, b` as two globs, runs every `test:` line, reports a changed suite, and lints the rules (`check`). The
procedure commits before review, asks the go-ahead before pushes and one-way doors, and ships its own Standards and
Spec reviewer briefs.

`0.3.0`: `setup_tools.py install`, `upgrade` and `doctor`; a per-clone bootstrap that runs the base branch's guard;
`status`, which names the standing rules, the pass stamp, the hook and the next step; pushes to any ref, not only
branches and tags, are checked; `run-suite` says when the stamped tree is not HEAD's; git 2.32+.
