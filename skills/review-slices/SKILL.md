---
name: review-slices
description: "Check an agent's work before it counts as done, Swiss-cheese style: shown output, the full suite with a pass stamp, review scaled by a computed review level (adversarial reviewers, code-review, an optional review meeting), the user's go-ahead, and incidents that plug holes. Use before commit, before push, when asked to review or verify my work, to record an incident or a slipped bug, or to set up REVIEW.md and INCIDENTS.md in a repo."
---

# Review slices

No single check is reliable. Stack independent slices so a defect ships only when every slice's holes line up,
and plug a hole every time something gets through. Terms are defined in this skill's [GLOSSARY.md](GLOSSARY.md);
use them exactly.

Start by reading the repo's `REVIEW.md` (its rules, level table and "failure looks like" list). If the repo has
none, go to [Set up a repo](#set-up-a-repo).

## The slices

| Slice | What | When |
|---|---|---|
| 0 Shown output | Run what you changed: the tests you touched, the command, `--help`, every command you wrote into docs, skills or runbooks. Show the command, exit code and output from tool calls in this session. | Always |
| 1 Offline tests | The full suite through `run-suite`, which stamps the passing tree; CI after the push. | Before every push |
| 2 Review | Fresh-context reviewers, scaled by review level. | By level |
| 3 Go-ahead | The user's explicit permission. | Before every one-way door, push and commit to the main branch |
| 4 Acceptance | The repo's host, live or user-trial checks. | Per release |

## A change, step by step

1. **Work with shown output.** Never write "done", "fixed" or "passes" without the output that shows it.
2. **Compute the review level.** Run `python3 .githooks/review_slices.py level` (base: the upstream or remote
   branch, else the merge-base with the main branch; rules: REVIEW.md as committed at that base). It prints the
   level, the paths that set it, and the trailer to write. Raise it for planned actions REVIEW.md lists (for
   example a live cloud action); when unsure, go one higher. Never lower it. Put its output in your report.
3. **Review at that level** (briefs in [references/reviewer-briefs.md](references/reviewer-briefs.md)):

   | Level | Slice 2 |
   |---|---|
   | Trivial | none |
   | Simple | 1–2 adversarial reviewers |
   | Important | the `code-review` skill (Standards + Spec) and 1 adversarial reviewer, all in parallel |
   | Critical | Important's three, then the user's go-ahead; a review meeting only for a disputed finding, only if the user says yes |

   Reviewers are read-only, have fresh context and use the strongest model available. Give them the diff
   command, REVIEW.md, the spec path and the level output. If you cannot start a fresh-context reviewer, use, in
   order: a CLI reviewer in a read-only sandbox (`claude -p`, `codex exec`), an Orca terminal, or ask the user.
   Never act as Slice 2 for your own work.
4. **Handle review findings.** Check each one yourself before acting on it.
   - Blocker (any security finding is one): fix it before committing.
   - Fix: fix it, or reject it with a written reason in your report.
   - Nit: at most three are worth raising; fix them only if cheap.
   - Pre-existing: record it as an incident or a roadmap item, never just a label.
   Fix a finding's whole class at once, not only the line quoted.
5. **Converge.** One review round, then at most one second round on the new diff only, resuming the same
   reviewers. Never re-raise a finding already settled. Still split after that: escalate to the user.
6. **Commit** with the trailer `level` printed: `Review: <level> <base-sha>`, on the last commit the review
   covered, in the message's last paragraph together with any other trailer. Each trailer must cover the level
   of the paths changed since the previous one; a later commit above Trivial needs its own review and trailer.
   The hook refuses both otherwise.
7. **Run the suite once:** `python3 .githooks/review_slices.py run-suite`. It stamps the tree only on a pass with
   no file changed during the run. The suite can be slow: use a long tool timeout or run it in the background.
8. **Push** only with the user's go-ahead. The pre-push hook checks the stamp and the trailer in about a second.
   If it refuses, fix what it names. `git push --no-verify`, an empty `core.hooksPath` and a hand-written stamp
   are the user's override, never yours; using one is an incident.

## Review meeting

A decision meeting limited to disputed review findings at Critical level. It needs the `orca-cli` and
`orchestration` skills and terminals the user opens. Never start one on your own. Propose it to the user first:

```
Review meeting proposal
Disputed finding(s): <ID, one line each, with both positions>
Why it is critical:   <the one-way door at stake>
Members and lenses:   <for example 2 Claude + 3 Codex; correctness, security, devil's advocate>
Rounds:               2 (a third only for a split or a blocking objection)
Cost:                 about <N> agent sessions, <minutes>
Folder:               .agents/<topic>-<date>/
Go ahead? (yes / no / change)
```

## Record an incident

An incident is a defect or rule break found after its author declared the work done (see GLOSSARY.md). When you
find one, in your own work or another agent's:

1. Add an entry to `docs/INCIDENTS.md` in the format of [templates/INCIDENTS.md](templates/INCIDENTS.md): what
   happened, the slice that should have caught it and why it did not, the failure class, the fix, the plug.
2. If an earlier incident has the same failure class, add this one under its Recurrences instead. A recurrence
   means the earlier plug is weak: say so.
3. Choose the plug in this order: a test or guard that fails on the class; else a rule in REVIEW.md's "Failure
   looks like" list. An incident stays open until its plug exists.
4. A new failure class gets a one-line entry in REVIEW.md's "Failure looks like" list, linked to the incident.

## Set up a repo

Ask the user before each step; these change how the repo works.

1. Copy [templates/REVIEW.md](templates/REVIEW.md) to the repo root and fill in its level table, test command and
   failure list. Copy [templates/INCIDENTS.md](templates/INCIDENTS.md) to `docs/INCIDENTS.md`.
2. Copy `scripts/review_slices.py` to `.githooks/review_slices.py`, and write `.githooks/pre-push`:
   `#!/bin/sh` then `exec python3 "$(dirname "$0")/review_slices.py" pre-push "$@"`. Make it executable.
3. Each clone opts in with `git config core.hooksPath .githooks`.
4. Point the repo's agent instructions (AGENTS.md or CLAUDE.md) at REVIEW.md with a plain path, not an import.

## Report

End every review with: the level output, the reviewers run and their lenses, each finding with its tag and what
happened to it (fixed, rejected and why), the shown output for the final state, and any incident recorded.
