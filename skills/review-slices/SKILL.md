---
name: review-slices
description: "Check an agent's work before it counts as done, Swiss-cheese style: shown output, the full suite with a pass stamp, review scaled by a computed review level (adversarial, Standards and Spec reviewers, an optional review meeting), the user's go-ahead, and incidents that plug holes. Use before commit, before push, when asked to review or verify my work, to record an incident or a slipped bug, or to set up REVIEW.md and INCIDENTS.md in a repo."
---

# Review slices

Some hosts load only the start of this file. Its last line is `End of review-slices SKILL.md.`: if you cannot
see that line, read the whole file before acting.

No single check is reliable. Stack independent slices so a defect ships only when every slice's holes line up,
and plug a hole every time something gets through. Terms are defined in this skill's [GLOSSARY.md](GLOSSARY.md);
use them exactly.

Start by reading the repo's `REVIEW.md` (its rules, level table and "failure looks like" list) and running
`python3 .githooks/review_slices.py status`, which says where the work stands and what to do next. If
`python3 .githooks/review_slices.py --version` is older than this skill's `scripts/review_slices.py --version`, tell
the user `setup_tools.py upgrade` can update it.

Read each of these in full when it applies:

- A secret found by any scan: [A secret turns up](references/secrets.md), before anything else.
- A defect or rule break found after the work was declared done: [Record an incident](references/incidents.md).
- No REVIEW.md with a ```` ```review-slices ```` block: [Set up a repo](references/set-up.md).

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
   not a claim of done. Where REVIEW.md has `secrets: gitleaks`, first run
   `gitleaks git --pre-commit --staged --redact --no-banner -v`; if it finds anything, do not commit: see
   [A secret turns up](references/secrets.md).
3. **Run `python3 .githooks/review_slices.py status`** (`level` is the same). It prints the review level of the
   work since the last trailer, the paths that set it, the trailer to write, the standing rules, the pass stamp,
   whether the hook is wired, the secret scan of the new commits (where REVIEW.md has `secrets:`), and the next
   step. A secret it finds goes to [A secret turns up](references/secrets.md) before any reviewer sees the diff. Fix errors in REVIEW.md that your change introduced; report the
   ones it says are in the standing rules to the user. Raise the level for planned actions REVIEW.md lists (for
   example a live cloud action); when unsure, go one higher. A raised level is the level the trailer records.
   Never lower it. Put its output in your report. At Important and Critical it also prints a `review:` line: the
   review load (which reviewers) and why, from the size band of everything the branch adds to the base branch (or only
   what follows a unit large on its own: `since <sha>`) and, at Critical, the glob kind of the paths that set the level; and an
   `escalate:` line when a git fact escalates the unit (step 5).
4. **Review at that level, with the load `status` printed** (briefs in
   [references/reviewer-briefs.md](references/reviewer-briefs.md)):

   | Level | Slice 2 |
   |---|---|
   | Trivial | none |
   | Simple | 1–2 adversarial reviewers |
   | Important | `review: one merged reviewer` (small band); else `adversarial + conformance`: an adversarial and a conformance reviewer, in parallel |
   | Critical | `adversarial + conformance`. Then the user's go-ahead for the one-way door, given with the review findings. A [review meeting](references/review-meeting.md) only for a disputed review finding, only if the user says yes |

   `plus a cross-check` (the base branch's REVIEW.md has `cross-check: on`) adds one cross-check reviewer to a
   unit's first pair round, raised levels and escalations from one merged reviewer included; `three reviewers` (Standards, Spec, adversarial) only where `status` prints it, unable to measure.
   The load is the least review the change needs; more is always allowed. A level you raised for a planned action
   takes the pair whatever `status` prints for the computed level. The one exception: a release whose only changes outside its release notes swap the version
   takes one merged reviewer where REVIEW.md as committed on the base branch (`git show <base>:REVIEW.md`) says so
   beside its planned actions, with the shown output it requires; wording that exists only on your branch never applies. A guard before 0.9.0, or no `review:` line:
   the three reviewers (one merged reviewer where it prints `review: merged reviewer allowed`).

   Never lower the load, merge its lenses into fewer reviewers, or swap a reviewer for a tool that does less: only
   the user can, asked before the round with the printed load. "It looks small", "it is mostly moves" and "it is
   only docs" are not reasons: the measure counted them. This holds for the first round on the whole unit; later rounds
   follow step 6, and a version-swap release follows the exception above. Before starting them, write one line in
   your message: `load: <status's review: line, or the load this step gives where it prints none>; starting: <each
   reviewer, its lenses>`.

   Reviewers read `git diff <base>..HEAD`, with `<base>` from the trailer line `status` printed. They are
   read-only, have fresh context, never a fork of this session, and use the strongest model available. Give
   them the diff command, REVIEW.md, the spec path and the level output; never tell one what not to flag or how to
   grade. If you cannot start a fresh-context reviewer, use, in order: a CLI
   reviewer in its own worktree (`claude -p`, `codex exec`), an Orca terminal, or ask the user. A subagent of
   this session loads the checkout's AGENTS.md, CLAUDE.md and `.claude/`
   settings as they are now: if `git diff --name-only <standing>..HEAD` (`<standing>` from the `standing rules:`
   line) touches any of those at any depth, or `.codex/`, use a CLI reviewer even when you can start a subagent.
   Start a CLI or terminal reviewer as the briefs say. Never act as Slice 2
   for your own work.
5. **Handle review findings.** Check each one yourself before acting on it. A Blocker, Fix or Nit is
   never an incident: the review caught it. Log a fixed Blocker or Fix in `docs/NEAR-MISSES.md`, or as a Recurrence
   where its reviewer tagged it `I<n>` ([Record an incident](references/incidents.md)). You may re-grade a finding upward only. To dispute a tag or a finding,
   reject it, citing the mitigation you found and read, or the line or output that shows the claim wrong; a comment
   that claims safety is not one. Its reviewer rules in round two (step 6; on escalation, the briefs' Later rounds);
   still disputed, a refuter in round three.
   - Blocker (any security problem is one): fix it before the trailer, unless its reviewer or refuter upholds your
     rejection.
   - Fix: fix it, or reject it with the reason in your report; it is ruled on as a Blocker is.
   - Nit: fix it only if cheap.
   - Pre-existing: record it as an incident or a roadmap item, never just a label.
   - `spec-mandated`: ask the user first; the answer settles it.
   - Level note (a reviewer's line that the level looks too high): put it in your report; the level of this change
     stays. Acting on one is a change to REVIEW.md's table of its own, reviewed, never part of the change that
     raised it.
   - **Escalation:** a fresh adversarial + conformance pair on the whole unit (`git diff <base>..HEAD`), as the
     next round. From one merged reviewer: when that round reports a Blocker; a review finding the reviewer tagged
     with a "Failure looks like" entry; that the change is too big or risky for its load; a "cannot verify from the
     diff" item your shown output does not close; or when `status` no longer prints that load. From the pair: only
     on a "too big or risky" line or a "Failure looks like" tag, once per unit (a second goes to the user); its
     Blocker or "cannot verify" item goes to an ordinary round two. From either, whenever `status` prints
     `escalate:` (the unit's weight rose, or history inside it was rewritten), or the user decides. Each is a tag, a
     list in the report or a git fact: apply it as written, never by your own reading. Never from round three.
   Fix a review finding's whole class at once, not only the line quoted. Fixes are new commits naming each
   finding's lens (`Adversarial: ...`), except a secret in unpushed commits, which is
   removed by rewriting them ([A secret turns up](references/secrets.md)).
6. **Converge.** Run `status` again before each later round. A load higher than the last round's, or an `escalate:`
   line naming a head no round reviewed yet, is escalation (step 5); before round one, round one is that pair. A unit's load is the highest `status` printed since the unit began, and the
   pair once history inside the unit was rewritten; a lower load printed later changes nothing. `status` keeps this
   itself, in the clone's review log (`held:` or `history inside the unit was rewritten` in its `review:` line), but
   a rebase onto a moved base branch moves the unit's start and starts the log over: after one, take a fresh pair on
   the whole unit yourself.
   Otherwise: one review round, then at most one second round on the new commits only (`git diff <old head>..HEAD`),
   resuming the reviewers the briefs' Later rounds names. A closing round three only if round two did not converge
   or commits followed it, Blocker only unless it is an escalation, as the briefs' Later rounds says; no round four.
   Never re-raise a review finding already settled. Still split after that: escalate to the user.
7. **Add the trailer** `status` printed to the last commit the review covered, with exactly
   `git -c trailer.ifexists=replace commit --amend --only --no-edit --trailer "Review: <level> <base-sha>"`
   (`status` prints it filled in): it keeps the message, leaves anything staged out, and replaces an earlier
   `Review:` trailer instead of adding a second. The trailer says the review ran with the load `status` printed,
   or more; less only with the user's go-ahead, step 4's version-swap exception, or a step 6 later round. Each
   trailer must cover the level of the commits since the previous one; a later commit above Trivial needs its own
   review and trailer (after round three: the trailer only, with the go-ahead given on it as unreviewed). The hook
   refuses both otherwise. Never amend new content into a commit that carries a trailer: add a commit.
8. **Run the suite once:** `python3 .githooks/review_slices.py run-suite`. It runs every `test:` line and stamps
   the working tree only when all pass and no file changed during the run. If it says the working tree is not
   HEAD's, commit what is yours and ask the user about the rest; never stash, revert or commit someone else's
   edits. The suite can be slow: use a long tool timeout or run it in the background. If it fails, the fix is a
   new commit and goes through step 6's next round; after round three, it is unreviewed.
9. **Push** only when `status` says `next: ask the user's go-ahead, then push`, and only with that go-ahead. Ask
   with a line `Door: one-way` (a one-way door, such as a push to the base branch) or `Door: two-way`, and the
   reason in a few words. The pre-push hook checks the stamp and the trailers in about a second.
   If it refuses, fix what it names. `git push --no-verify`, changing the hook's git config, an edited guard or
   bootstrap and a hand-written stamp are the user's override, never yours; using one is an incident. Where the
   repo has the agent hook, it refuses these for you.
10. **Read the CI result** after the push, for every remote check REVIEW.md lists: on GitHub
    `gh run list --commit <sha>`, then `gh run watch <run-id> --exit-status`; elsewhere the repo's own command.
    Red: rerun it once (`gh run rerun <run-id> --failed`). Still red: the work is not done. Fix it from step 1, and
    record an incident of failure class "the local suite differs from CI"; its plug is the missing check, added to
    the suite as a `test:` line or listed under REVIEW.md's "Remote checks". If you cannot read CI (no `gh`, another
    host), say so in your report and ask the user to check it; never report done over a result nobody read.

## Report

End every review with: the level output, the load `status` printed beside the reviewers that ran and their lenses
(a cross-check's runner named; a reduction the user allowed, step 4's version-swap exception or a step 6 later round named as such; any other
is a rule break: [record an incident](references/incidents.md)), each review finding with its tag, what happened to it (fixed, rejected and
why, with any refuter's ruling) and, for a Blocker or Fix, a line on how you verified it, any Blocker found in round
three, each commit after round three as unreviewed, each `spec-mandated` one and the user's answer,
any level notes, the shown output for the final state, the Door line (step 9), and any incident recorded.
Never a secret's value.
The guard's known holes: [references/known-holes.md](references/known-holes.md).

End of review-slices SKILL.md.
