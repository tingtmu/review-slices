---
name: review-slices
description: "Check an agent's work before it counts as done, Swiss-cheese style: shown output, the full suite with a pass stamp, review scaled by a computed review level (adversarial, Standards and Spec reviewers, an optional review meeting), the user's go-ahead, and incidents that plug holes. Use before commit, before push, when asked to review or verify my work, to record an incident or a slipped bug, or to set up REVIEW.md and INCIDENTS.md in a repo."
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
| 1 Offline suite | Every check REVIEW.md lists, through `run-suite`, which stamps the passing tree; remote checks (CI) after the push. | Before every push |
| 2 Review | Fresh-context reviewers, scaled by review level. | By level |
| 3 Go-ahead | The user's explicit permission. | Before every push and every one-way door |
| 4 Acceptance | The repo's host, live or user-trial checks. | Per release |

## A change, step by step

1. **Work with shown output.** Never write "done", "fixed" or "passes" without the output that shows it.
2. **Commit locally, without a trailer.** Reviewers read committed work. A local commit needs no go-ahead and is
   not a claim of done.
3. **Compute the review level.** Run `python3 .githooks/review_slices.py level`. It prints the level, the paths
   that set it, the trailer to write and any problem in REVIEW.md; fix an `error in REVIEW.md` first. Raise the
   level for planned actions REVIEW.md lists (for example a live cloud action); when unsure, go one higher. A
   raised level is the level the trailer records. Never lower it. Put its output in your report.
4. **Review at that level** (briefs in [references/reviewer-briefs.md](references/reviewer-briefs.md)):

   | Level | Slice 2 |
   |---|---|
   | Trivial | none |
   | Simple | 1–2 adversarial reviewers |
   | Important | a Standards, a Spec and an adversarial reviewer, all in parallel |
   | Critical | Important's three; then the user's go-ahead for the one-way door, given with the review findings. A [review meeting](references/review-meeting.md) only for a disputed review finding, only if the user says yes |

   Reviewers read `git diff <base>..HEAD`, with `<base>` from the trailer line `level` printed. They are
   read-only, have fresh context and use the strongest model available. Give them the diff command, REVIEW.md,
   the spec path and the level output. If you cannot start a fresh-context reviewer, use, in order: a CLI
   reviewer in a read-only sandbox (`claude -p`, `codex exec`), an Orca terminal, or ask the user. Never act as
   Slice 2 for your own work.
5. **Handle review findings.** Check each one yourself before acting on it.
   - Blocker (any security finding is one): fix it before the trailer.
   - Fix: fix it, or reject it with a written reason in your report.
   - Nit: at most three are worth raising; fix them only if cheap.
   - Pre-existing: record it as an incident or a roadmap item, never just a label.
   Fix a review finding's whole class at once, not only the line quoted. Fixes are new commits.
6. **Converge.** One review round, then at most one second round on the new commits only
   (`git diff <old head>..HEAD`), resuming the same reviewers. Never re-raise a review finding already settled.
   Still split after that: escalate to the user.
7. **Add the trailer** `level` printed, `Review: <level> <base-sha>`, to the last commit the review covered: amend
   its message only (`git commit --amend` with nothing staged), or put it on the last fix commit. It goes in the
   message's last paragraph, with any other trailer. Each trailer must cover the level of the commits since the
   previous one; a later commit above Trivial needs its own review and trailer. The hook refuses both otherwise.
   Never amend new content into a commit that carries a trailer: add a commit.
8. **Run the suite once:** `python3 .githooks/review_slices.py run-suite`. It runs every `test:` line and stamps
   the tree only when all pass and no file changed during the run. The suite can be slow: use a long tool timeout
   or run it in the background. If it fails, the fix is a new commit and goes through step 6's second round.
9. **Push** only with the user's go-ahead. The pre-push hook checks the stamp and the trailers in about a second.
   If it refuses, fix what it names. `git push --no-verify`, an empty `core.hooksPath`, an edited guard and a
   hand-written stamp are the user's override, never yours; using one is an incident.

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

Ask the user before each step; these change how the repo works. First check that this clone can take the hook:
`git config --get core.hooksPath` prints nothing (in any scope), `ls "$(git rev-parse --git-path hooks)"` shows
only `*.sample` files, and there is no `.husky/`, no `.pre-commit-config.yaml` and no `filter=lfs` in
`.gitattributes`. If any of these fails, stop and tell the user: step 3 would silently turn those hooks off,
including git-lfs's upload on push.

1. Copy [templates/REVIEW.md](templates/REVIEW.md) to the repo root and fill in its level table (one glob per
   line), its `test:` lines (one per check of the suite) and its failure list. Copy
   [templates/INCIDENTS.md](templates/INCIDENTS.md) to `docs/INCIDENTS.md`.
2. Copy `scripts/review_slices.py` to `.githooks/review_slices.py`, and write `.githooks/pre-push`:
   `#!/bin/sh` then `exec python3 "$(dirname "$0")/review_slices.py" pre-push "$@"`. Make it executable. Run
   `python3 .githooks/review_slices.py check` until it reports no error.
3. Each clone opts in with `git config core.hooksPath .githooks`, after the same check.
4. Point the repo's agent instructions (AGENTS.md or CLAUDE.md) at REVIEW.md with a plain path, not an import.

## Report

End every review with: the level output, the reviewers run and their lenses, each review finding with its tag and
what happened to it (fixed, rejected and why), the shown output for the final state, and any incident recorded.
What the guard cannot see is listed in [references/known-holes.md](references/known-holes.md).
