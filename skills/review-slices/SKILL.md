---
name: review-slices
description: "Check an agent's work before it counts as done, Swiss-cheese style: shown output, the full suite with a pass stamp, review scaled by a computed review level (adversarial, Standards and Spec reviewers, an optional review meeting), the user's go-ahead, and incidents that plug holes. Use before commit, before push, when asked to review or verify my work, to record an incident or a slipped bug, or to set up REVIEW.md and INCIDENTS.md in a repo."
---

# Review slices

No single check is reliable. Stack independent slices so a defect ships only when every slice's holes line up,
and plug a hole every time something gets through. Terms are defined in this skill's [GLOSSARY.md](GLOSSARY.md);
use them exactly.

Start by reading the repo's `REVIEW.md` (its rules, level table and "failure looks like" list) and running
`python3 .githooks/review_slices.py status`, which says where the work stands and what to do next. If the repo has
no REVIEW.md with a ```` ```review-slices ```` block, go to [Set up a repo](#set-up-a-repo). If `python3 .githooks/review_slices.py --version` is older than
this skill's `scripts/review_slices.py --version`, tell the user `setup_tools.py upgrade` can update it.

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
   [A secret turns up](#a-secret-turns-up).
3. **Run `python3 .githooks/review_slices.py status`** (`level` is the same). It prints the review level of the
   work since the last trailer, the paths that set it, the trailer to write, the standing rules, the pass stamp,
   whether the hook is wired, the secret scan of the new commits (where REVIEW.md has `secrets:`), and the next
   step. A secret it finds goes to [A secret turns up](#a-secret-turns-up) before any reviewer sees the diff. Fix errors in REVIEW.md that your change introduced; report the
   ones it says are in the standing rules to the user. Raise the level for planned actions REVIEW.md lists (for
   example a live cloud action); when unsure, go one higher. A raised level is the level the trailer records.
   Never lower it. Put its output in your report. At Important and Critical it also prints a `review:` line: the
   review load (which reviewers) and why, from the size band of everything the branch adds to the base branch and,
   at Critical, the glob kind of the paths that set the level.
4. **Review at that level, with the load `status` printed** (briefs in
   [references/reviewer-briefs.md](references/reviewer-briefs.md)):

   | Level | Slice 2 |
   |---|---|
   | Trivial | none |
   | Simple | 1–2 adversarial reviewers |
   | Important | `review: one merged reviewer` (small band); `adversarial + conformance` (medium band): an adversarial and a conformance reviewer; `three reviewers` (large): a Standards, a Spec and an adversarial reviewer. All of one round in parallel |
   | Critical | `adversarial + conformance` (small, and every path that sets the level is in `critical code:` globs alone); else the three. Then the user's go-ahead for the one-way door, given with the review findings. A [review meeting](references/review-meeting.md) only for a disputed review finding, only if the user says yes |

   The load is the least review the change needs; more is always allowed. In the adversarial + conformance pair,
   the adversarial reviewer's brief also ends with the report for a reduced load. A level you raised for a planned
   action takes the three reviewers whatever `status` prints for the computed level, and a floor path makes
   `status` print three. The one exception: a release whose only changes outside README.md swap the version takes
   one merged reviewer where REVIEW.md as committed on the base branch (`git show <base>:REVIEW.md`) says so beside
   its planned actions, with the shown output it requires; wording that exists only on your branch never applies. A guard before 0.9.0, or no `review:` line:
   the three reviewers, except one merged reviewer where `status` prints `review: merged reviewer allowed` at
   Important.

   Reviewers read `git diff <base>..HEAD`, with `<base>` from the trailer line `status` printed. They are
   read-only, have fresh context and use the strongest model available. Give them the diff command, REVIEW.md,
   the spec path and the level output. If you cannot start a fresh-context reviewer, use, in order: a CLI
   reviewer in a read-only sandbox (`claude -p`, `codex exec`), an Orca terminal, or ask the user. A subagent of
   this session (the `code-review` skill's included) loads the checkout's AGENTS.md, CLAUDE.md and `.claude/`
   settings as they are now: if `git diff --name-only <standing>..HEAD` (`<standing>` from the `standing rules:`
   line) touches any of those at any depth, or `.codex/`, use a CLI reviewer even when you can start a subagent.
   Start a CLI or terminal reviewer in a new empty directory (`mktemp -d`), never the checkout or a directory
   above it (`codex exec --skip-git-repo-check --sandbox read-only`), and have it read the repo only through git
   (`git -C <repo path> diff <base>..HEAD`, `git -C <repo path> show <standing>:<path>`), so it never loads the
   change's instruction files as its own. Never act as Slice 2 for your own work.
5. **Handle review findings.** Check each one yourself before acting on it.
   - Blocker (any security problem is one): fix it before the trailer.
   - Fix: fix it, or reject it with a written reason in your report.
   - Nit: at most three are worth raising; fix them only if cheap.
   - Pre-existing: record it as an incident or a roadmap item, never just a label.
   - Level note (a reviewer's line that the level looks too high): put it in your report; the level of this change
     stays. Acting on one is a change to REVIEW.md's table of its own, reviewed, never part of the change that
     raised it.
   - **Escalation** from a reduced load (one merged reviewer, or adversarial + conformance): the review goes to the
     three reviewers on the whole unit (`git diff <base>..HEAD`) when that round reports a Blocker; a review
     finding the reviewer tagged with a "Failure looks like" entry; that the change is too big or risky for its
     load; a "cannot verify from the diff" item your shown output does not close; when `status` no longer prints
     that load; or when history inside the unit was rewritten (amend, squash, rebase) after the round. Each is a
     tag, a list in the report or a git fact: apply it as written, never by your own reading. Never the reverse.
   Fix a review finding's whole class at once, not only the line quoted. Fixes are new commits, except a secret
   in unpushed commits, which is removed by rewriting them ([A secret turns up](#a-secret-turns-up)).
6. **Converge.** Run `status` again before a second round. If the load rose (the unit grew a band, or a floor
   path came in), that is escalation: the three reviewers on the whole unit, `git diff <base>..HEAD`. A unit's
   load is the highest `status` printed since the unit began, and the three reviewers once history inside the unit
   was rewritten; a lower load printed later changes nothing. Otherwise: one review round, then at most one second
   round on the new commits only (`git diff <old head>..HEAD`), resuming the same reviewers, so they keep their
   model and context. At Important, resume only the reviewers whose review finding was fixed or rejected (a rejected
   one sees your reason), plus the adversarial or merged reviewer always, for new breakage in the fix; resume every
   reviewer when `git diff --name-only <old head>..HEAD` lists a file no review finding cited, or a floor path. At
   Critical, resume every reviewer. Never re-raise a review finding already settled. Still split after that:
   escalate to the user.
7. **Add the trailer** `status` printed to the last commit the review covered, with exactly
   `git -c trailer.ifexists=replace commit --amend --only --no-edit --trailer "Review: <level> <base-sha>"`
   (`status` prints it filled in): it keeps the message, leaves anything staged out, and replaces an earlier
   `Review:` trailer instead of adding a second. Each trailer must cover the level of the commits since the previous one; a later commit
   above Trivial needs its own review and trailer. The hook refuses both otherwise. Never amend new content into
   a commit that carries a trailer: add a commit.
8. **Run the suite once:** `python3 .githooks/review_slices.py run-suite`. It runs every `test:` line and stamps
   the working tree only when all pass and no file changed during the run. If it says the working tree is not
   HEAD's, commit what is yours and ask the user about the rest; never stash, revert or commit someone else's
   edits. The suite can be slow: use a long tool timeout or run it in the background. If it fails, the fix is a
   new commit and goes through step 6's second round.
9. **Push** only when `status` says `next: ask the user's go-ahead, then push`, and only with that go-ahead. The pre-push hook checks the stamp and the trailers in about a second.
   If it refuses, fix what it names. `git push --no-verify`, changing the hook's git config, an edited guard or
   bootstrap and a hand-written stamp are the user's override, never yours; using one is an incident. Where the
   repo has the agent hook, it refuses these for you.
10. **Read the CI result** after the push, for every remote check REVIEW.md lists: on GitHub
    `gh run list --commit <sha>`, then `gh run watch <run-id> --exit-status`; elsewhere the repo's own command.
    Red: rerun it once (`gh run rerun <run-id> --failed`). Still red: the work is not done. Fix it from step 1, and
    record an incident of failure class "the local suite differs from CI"; its plug is the missing check, added to
    the suite as a `test:` line or listed under REVIEW.md's "Remote checks". If you cannot read CI (no `gh`, another
    host), say so in your report and ask the user to check it; never report done over a result nobody read.

## A secret turns up

When the secret scan (`status`, the pre-push hook, `ci`) or the staged scan of step 2 finds a secret:

1. Never write the value anywhere: not in your report, INCIDENTS.md, a commit message or a reviewer brief. Cite
   the rule, file, line and fingerprint the scan printed. Found by the staged scan, it is in no commit yet: move
   the value out (an environment variable or a secret manager), `git add` the files, and scan again.
2. Whether it is a real secret or a false positive is the user's call. For a false positive the user, never the
   agent, adds the full fingerprint (`<commit>:<file>:<rule>:<line>`) to `.gitleaksignore` and commits it, with
   the reason as a `#` comment on the line above (a trailing comment breaks the match). Only fingerprints that
   name a commit count, and a rewrite of that commit changes its fingerprint. `gitleaks:allow` markers count
   for nothing.
3. **Not pushed yet**: after `git fetch`, `git for-each-ref --contains <sha> refs/remotes` prints nothing. (A
   branch pushed without `-u` still counts among `status`'s new commits, so this check decides; if it prints a
   ref, go to step 4.) Move the value out, then rewrite the new commits so no commit holds it:
   - First stop and ask the user if the new commits include a merge, the working tree has edits that are not
     yours, or another branch, tag or stash holds the commit (`git for-each-ref --contains <sha> refs/heads
     refs/tags`, `git stash list`).
   - Otherwise `git reset --soft <parent of the oldest new commit>`, remove the value, `git add` the files, run
     step 2's staged scan, commit again, and redo steps 3 to 8: the old trailers went with the old commits.
   - Never `git reset --hard`, a backup branch, `push --all` or `--mirror`.
   - Tell the user. If the value is real, rotating it is the user's call: you and any reviewer have seen it.
4. **Already pushed:** tell the user first. Rotating or revoking the value is the fix, and the user's action.
   Remove the value with an ordinary commit; once the user has dealt with it, they add its fingerprint to
   `.gitleaksignore` so later pushes and the pull request pass. Rewriting published history needs a force-push,
   a one-way door: only with the user's go-ahead, and it does not unpublish (forks, pull request refs, caches,
   CI logs). Record an incident.
5. A secret already in the base branch's history that this change did not add is Pre-existing (step 5).

## Record an incident

An incident is a defect or rule break found after its author declared the work done (see GLOSSARY.md). When you
find one, in your own work or another agent's:

1. Add an entry to `docs/INCIDENTS.md` in the format of [templates/INCIDENTS.md](templates/INCIDENTS.md): what
   happened, the slice that should have caught it and why it did not, the failure class, the fix, the plug.
2. If an earlier incident has the same failure class, add this one under its Recurrences instead. A recurrence
   means the earlier plug is weak: say so.
3. If the slice that should have caught it was a reduced load, name it in the Slice field
   (`2 Review (merged reviewer)`, `2 Review (adversarial + conformance)`) and tell the user. Its plug, best first:
   a test for the class; else narrow that band in REVIEW.md (`small: 20 lines, 2 files`), written as a
   `rule REVIEW.md "<line>"` plug so `--check` notices if it is loosened again (narrowing it further edits that plug
   line in the same change); else a "Failure looks like" rule. A second incident through the same reduced load:
   set that band to `off` until a test plug exists. Widening a band is never automatic: calibrate shows the
   evidence, and the user changes the line in a reviewed REVIEW.md change. The built-in bands change only by a
   guard release.
4. Otherwise choose the plug in this order: a test or guard that fails on the class; else a rule in REVIEW.md's
   "Failure looks like" list. An incident stays open until its plug exists.
5. A new failure class gets a one-line entry in REVIEW.md's "Failure looks like" list, linked to the incident.
6. **Check the log:** `python3 <skill>/scripts/incidents.py` lists open incidents with their age, counts per slice
   and recurrences; `--check` exits 1 when a plugged incident's plug is gone (the hole is open again: reopen it).
   Write plugs as `test <path>::<function>`, `guard <path>` or `rule REVIEW.md "<line>"` so it can check them. To
   make that part of the suite, copy the script to `.githooks/incidents.py` (`upgrade` keeps it current) and add
   `test: python3 .githooks/incidents.py --check`.

## Set up a repo

Ask the user before each step; these change how the repo works. `<skill>` is this skill's directory.

1. **Find the suite.** `python3 <skill>/scripts/discover.py` lists the checks the repo already has (CI files,
   package.json, Makefile, justfile, pyproject, tox, nox, pre-commit, Cargo, go.mod, CONTRIBUTING), each marked
   local or remote with the reason; it runs nothing. With the user's go-ahead (it runs the repo's commands),
   `discover.py --run` on a clean tree runs each local check and prints the `test:` lines that passed, the checks
   already red (record each as an incident or a roadmap item and leave it out of the suite), the checks that
   write files (with `.gitignore` entries), and the remote checks for REVIEW.md.
2. Copy [templates/REVIEW.md](templates/REVIEW.md) to the repo root and fill in its level table (one glob per
   line), its `test:` lines and remote checks from step 1, and its failure list. If a REVIEW.md is already there,
   keep its text and add the template's sections to it. Copy [templates/INCIDENTS.md](templates/INCIDENTS.md) to
   `docs/INCIDENTS.md`. If the repo already has review rules (an existing REVIEW.md, CONTRIBUTING, a pull request
   template, CODEOWNERS, AGENTS.md or CLAUDE.md), list where they agree with the new rules and where they
   conflict, for the user to decide; link to them rather than copy them. CODEOWNERS paths are good candidates for
   important or critical globs.
3. **Calibrate the table** before committing it: `python3 <skill>/scripts/calibrate.py` shows how it would have
   judged the base branch's last 50 first-parent commits. Over 30% critical means people will route around it;
   over 60% trivial means most changes get no review. Tune the globs and run it again (`--rules PATH` tries a
   draft kept elsewhere). Its later sections say what a level costs and why. A glob that alone sets many high
   levels is the one to narrow first. A trailer declared above the table is a planned action, or a table too
   loose; one below it, a table stricter than the one that judged it. Small Important units that are mostly prose
   call for a narrower glob, not fewer reviewers. Its review load section shows the reviewers each unit would
   get. Tag a critical glob `critical code:` only where its files are code a reviewer can judge from a small diff;
   golden outputs, corpora, state tables and CI stay `critical:` (content, the default, which always takes three).
   `small: N lines, M files` and `medium: N lines, M files` (or `off`) set the size bands; built in: small 40 lines,
   3 files, no medium; at most 80/5 and 400/20. Where the base branch's guard is older than 0.9.0, push the upgraded
   guard first: an older guard cannot parse these lines, so pushes count every path as critical and `status`
   stops with a parse error. Run it again as reviewers' level notes build up.
4. Run `python3 <skill>/scripts/setup_tools.py install --agent-hooks`, show the user what it would change, and
   with their go-ahead run it again with `--apply`. It copies the guard, `merged_reviewer.py` and `run_suite.py` to
   `.githooks/` if missing, writes this clone's bootstrap, records the base branch, and wires pre-push with a hook file that
   runs any hook already there after the guard (pre-commit's through its `.legacy` hook). Where another tool owns
   `core.hooksPath` (Husky), it registers a git config hook instead, which only git 2.54+ runs. It never sets
   `core.hooksPath`, so git-lfs, Husky and pre-commit keep running. `--agent-hooks` adds the agent hook to `.claude/settings.json`
   and `.codex/hooks.json`, keeping what is there. Codex runs it on shell commands once its hooks feature is on and
   the user trusts the hook (a refused `git push --no-verify` checked live with Codex 0.164.0). If install reports
   a problem, tell the user.
5. Optional, with the user: add `secrets: gitleaks` to REVIEW.md's block to scan the commits every push adds,
   then run `setup_tools.py upgrade --apply`, which copies `secret_scan.py` beside the guard. Every clone that
   pushes, and CI, then needs gitleaks 8.19+ and git 2.36+. Where the base branch already has a guard older than
   0.7.0, push the upgraded guard first: an older guard cannot parse the line, so it counts every path as
   critical and scans nothing.
6. Run `python3 .githooks/review_slices.py check` until it reports no error, and `setup_tools.py doctor` until
   it reports ok. The scripts in `.githooks/` are vendored: they tell ruff, flake8, pylint, isort and mypy to skip
   them. If another check in the suite (a formatter such as black or prettier, or ruff with `preview = true`, which
   wants `# ruff: file-ignore`) still reads `.githooks/`, exclude it there in this same setup commit and say so to
   the user; it is not a weakened check.
7. Commit REVIEW.md, `docs/INCIDENTS.md`, `.githooks/` and the agent hook settings together; REVIEW.md puts them
   at Important or higher, so they are reviewed like any change. Every other clone that wants the guard runs
   `install --apply` once; teammates who do not are never blocked by it, and the agent hook does nothing for them.
8. Offer the user [templates/review-slices-ci.yml](templates/review-slices-ci.yml) as
   `.github/workflows/review-slices.yml`: it runs `review_slices.py ci` on every pull request, so trailers are
   checked even from clones that never installed the hook.
9. Point the repo's agent instructions (AGENTS.md or CLAUDE.md) at REVIEW.md with a plain path, not an import.

When the skill is newer than the repo's guard, `setup_tools.py upgrade --apply` copies it in; commit it as a
reviewed change. What gets installed:

```
<repo>/REVIEW.md                       rules and level table               committed
<repo>/docs/INCIDENTS.md               incidents and their plugs           committed
<repo>/.githooks/review_slices.py      the guard; the base branch's copy   committed
                                       judges every push
<repo>/.githooks/agent_hook.py         blocks an agent's overrides         committed
<repo>/.githooks/merged_reviewer.py    the review load: which reviewers    committed
<repo>/.githooks/run_suite.py          run-suite: runs the suite, stamps   committed
<repo>/.githooks/secret_scan.py        the secret scan (with secrets:)     committed
<repo>/.claude/settings.json           runs the agent hook (Claude Code)   committed
<repo>/.codex/hooks.json               runs the agent hook (Codex)         committed
<repo>/.github/workflows/...           optional: `ci` on pull requests     committed
<git-common-dir>/review-slices/        per clone, never committed:
    bootstrap.py                       runs the base branch's guard on pre-push
    suite-pass                         pass stamps
<git-common-dir>/hooks/pre-push        per clone: runs the bootstrap, then any hook that was there
git config (per clone)                 review-slices.base; hook.review-slices.* only beside a foreign core.hooksPath
```

## Report

End every review with: the level output, the reviewers run and their lenses, each review finding with its tag and
what happened to it (fixed, rejected and why), any level notes, the shown output for the final state, and any
incident recorded.
Never a secret's value.
What the guard cannot see is listed in [references/known-holes.md](references/known-holes.md).
