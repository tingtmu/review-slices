# Changelog

Each release of the review-slices skill, newest first. Each is tagged `vX.Y.Z`; from 0.9.2 on, each also has a
GitHub Release with the same notes.

## 0.10.0 (2026-10-30)

The agent hook follows `cd`, `pushd` and `git -C` through a command before it judges an amend or a write
([#16](https://github.com/tingtmu/review-slices/issues/16)): before, `cd <reviewed repo> && git commit -a --amend`
passed. Where the shell may or may not have moved (a pipeline, `||`, a `cd` that may fail, one later in a `&&` list or
in a `then`, `do` or `case` arm), both places are judged; a `cd` it cannot work out refuses an amend that could add
content, and a write after one is judged by the guarded layout's names. Found on the way: commands after a shell keyword
(`if`, `then`, `do`, `{`, `!`), after operators shlex runs together (`;(`, `&&(`) or around a quoted word made only of
operator characters went unread, so `if true; then git push --no-verify; fi` passed (an I2 recurrence).
`docs/known-holes.md` names `CDPATH`, `env -C` and a `cd` inside a shell function. `discover` drops setup only from the
start of a chain, so `pip install ruff && ruff check notesvc` keeps its check
([#20](https://github.com/tingtmu/review-slices/issues/20)), and prints one SAST hint (bandit, gosec or semgrep) when
nothing names a security scanner; the REVIEW.md template gets a commented `test:` example, and `doctor` lists the agent
hook. Some hosts load only the start of a long skill (Codex 8,000 bytes, Claude Code 5,000 tokens after compaction), so
SKILL.md moves "A secret turns up", "Record an incident" and "Set up a repo" verbatim to `references/secrets.md`,
`incidents.md` and `set-up.md`, says near its top how to tell it was cut short, and puts Report after step 10; a test
keeps it under 14,000 bytes and checks every relative link. Recording an incident always names the load that missed, and
a review finding is never an incident ([#23](https://github.com/tingtmu/review-slices/issues/23)); Set up a repo lists
every file install copies and what to do when calibrate finds fewer than 20 commits
([#24](https://github.com/tingtmu/review-slices/issues/24)). `status` names the open unit's new files that match no glob
when `default:` is below important ([#17](https://github.com/tingtmu/review-slices/issues/17)); the level is unchanged.
A reduced load's report tags each finding with a "Failure looks like" entry's id (I1, F1), its quoted text, or `none`
([#18](https://github.com/tingtmu/review-slices/issues/18)): the template gives entries F ids, and the conformance
reviewer gets the author's shown output. A miss names the review unit it went through (`2 Review (merged reviewer), unit
1a2b3c4d`), and misses naming one unit count once toward turning a band off
([#21](https://github.com/tingtmu/review-slices/issues/21)); a miss naming no unit counts alone. Step 9's go-ahead
request and the Report carry a `Door: one-way` or `Door: two-way` line, and GLOSSARY's "One-way door" gives examples.

## 0.9.5 (2026-10-29)

The `next:` line now asks for the pre-commitment line itself
([#26](https://github.com/tingtmu/review-slices/issues/26)): before starting the first round's reviewers, the agent
writes in its message `load: <the review: line>; starting: <each reviewer, its lenses>` (`<this load>` at Simple,
where `status` prints no `review:` line). The trailer command stays last on the line. In the 0.9.4 canary every
agent read SKILL.md step 4's request for that line, but Sonnet wrote it in none of four runs and Haiku in three; the
`next:` line is where the agent decides. SKILL.md keeps its sentence, since an adopter's vendored guard may be older
and not ask.

## 0.9.4 (2026-10-29)

The review load `status` prints is binding where the agent decides ([#26](https://github.com/tingtmu/review-slices/issues/26)):
an adopter's agent ran two reviewers where `status` printed three, without asking. The `next:` line now counts the
first round's separate reviewers (`3 separate reviewers (Standards, Spec, adversarial), each its own fresh agent`),
says that fewer, or lenses combined into fewer reviewers, take the user's go-ahead asked first (or step 4's
exceptions), scopes itself to the first round on the whole unit, and puts the trailer after the reviewers report; a
reduced load reads as the least, never enough. A large change's `why` names the widest band that is on (`over every
band (widest on: small, 40 lines, 3 files)`), or that every band is off. SKILL.md steps 4 and 7 and its Report, the
conformance brief, templates/REVIEW.md and the known holes say the same; before starting reviewers the agent writes
one `load: ...; starting: ...` line. Separately, after a unit large on its own that the review log shows went to
three reviewers, the review load's measure starts over, so later small fixes on a long branch get the lighter load
again instead of three reviewers for good; small slices never restart, so a change pushed in slices is still
measured whole.

## 0.9.3 (2026-10-27)

The review load's measure counts a file moved unchanged (an exact rename) as one file and no lines, and `status`'s
`review:` line names how many it found (`; 4 exact rename(s) counted as 0 lines`). Before, every move counted as all
its lines deleted and added, in two files, so an archive of a few moved files (an OpenSpec `/opsx:archive`) landed in
the large band and took three reviewers ([#13](https://github.com/tingtmu/review-slices/issues/13)). Only git's
exact pass pairs a move (`--find-renames=100%`, whatever `diff.renameLimit` says): a move with any edit, even two
lines swapped, still counts in full. The level still takes both paths, a binary file added, edited or deleted still
makes a change large, and `calibrate.py` sizes units the same way while still finding a moved submodule.
`docs/known-holes.md` notes that unchanged content moved into a `critical code:` glob can take the adversarial and
conformance pair on a diff that shows none of it.

## 0.9.2 (2026-10-27)

`status` keeps a review log in the clone (`<git-common-dir>/review-slices/review-log`) of each load it prints for
committed work, by branch and review unit: a unit keeps the highest load printed since it began (`held:`), and takes
three reviewers once a commit a load was printed at leaves the branch's history within the unit (amend, squash,
rebase), so stepping a branch back no longer lightens its review; a rebase onto a moved base branch starts the log
over, a known hole. The hold lives in `.githooks/merged_reviewer.py` and applies once the base branch has it.
`calibrate.py` adds a logged loads section, and GLOSSARY.md adds Review log and Miss. `incidents.py --check` makes it
a problem when two misses go through one reduced load, one of their incidents has no working test plug, and REVIEW.md
still leaves that load's band on (`small: off` for the merged reviewer; `medium: off` for the pair, and `small: off`
too while a `critical code:` line remains); each miss needs its own test in the Plug field, and a recurrence names
its load as the Slice field does. The guard's known holes move to this repo's `docs/known-holes.md`; the skill keeps
a short note for agents that links the full list here. The CI template uses `actions/checkout@v7`. Release notes move
from README.md to this file. The version-swap check REVIEW.md names is a script, `tests/release_check.py`, and lets a
release change CHANGELOG.md as well as README.md.

## 0.9.1 (2026-10-26)

Every Python the hooks start runs isolated and without site (`python3 -I -S`): the agent hook, the pre-push
hook file and config hook, the bootstrap and the guard's hand-off. Before, a stdlib-named file the agent wrote in
the working directory (`json.py`) or beside the bootstrap, or a `.pth` file in a virtualenv on PATH, could stand in
for the hook's imports, so the agent hook allowed `git push --no-verify` or the pre-push hook passed. `doctor` names
a hook or an agent hook command an older install wrote; `install --agent-hooks --apply` rewrites both, and the
`.claude` and `.codex` settings it writes are committed changes. A push whose command line sets `PATH` or git's own
variables, a `python3` or `git` shim on PATH, and a stdlib-named file in `.githooks/` when the agent runs the guard
itself are listed as known holes.

## 0.9.0 (2026-10-26)

`status` prints the review load at important and critical: which reviewers a change needs, from the size
band of every commit the branch adds to the base branch and, at critical, the glob kind of the paths that set the
level. Important takes one merged reviewer when small, an adversarial and a conformance (Standards and Spec)
reviewer when medium, and three otherwise; critical takes the adversarial and conformance pair only when small and
in `critical code:` globs alone. REVIEW.md may say `small:` and `medium:` (up to 80 lines, 5 files and 400 lines, 20
files) and `critical code:`; the default bands are 0.8.0's (small 40 lines, 3 files, no medium), but the whole
branch is measured now, not only the push, so a branch pushed in slices is measured whole. The base branch needs the
0.9.0 guard before these lines are added. A release that only swaps the version takes one merged reviewer where the
base branch's REVIEW.md says so, with the shown checks it names. `calibrate.py` adds a review load section. SKILL.md
adds escalation from a reduced load, leaner second rounds and an incident loop that narrows or switches off a band;
the reviewer briefs add a conformance reviewer and a structured report for reduced loads; `incidents.py` counts
misses per reduced load and checks a band plug against REVIEW.md's block. `run-suite` moves into a vendored
`.githooks/run_suite.py`, which `install` copies and `upgrade` adds; the stamp format is unchanged.

## 0.8.0 (2026-10-25)

At important, `status` says whether one merged reviewer may take a small push (at most 40 weighted lines
and 3 files) or why it needs three; the measure is a new vendored `.githooks/merged_reviewer.py`, loaded from the
base branch like the guard, which `upgrade` adds. Reviewers add a level note when a level looks higher than the
change needs and read REVIEW.md and the agent instruction files as committed at the standing rules' commit; a
change to those files, `.claude/` or `.codex/` gets a CLI reviewer started in an empty directory. `calibrate.py`
adds, by review unit, which globs set the levels, declared vs computed levels, size by level, an estimate of
whitespace- or comment-only units, and the merged-reviewer candidates (`--list-candidates LINES FILES`); in a
partial clone it runs only the first section and fetches nothing. The vendored copies no longer trip ruff's PGH004
under `--select ALL`. The agent hook is checked live with Codex 0.164.0, which shows it shell commands only, so
`apply_patch` edits are a known hole.

## 0.7.1 (2026-10-24)

`install` makes a remote other than origin the base branch only when it has review rules (a fork whose
base branch tracked such a remote kept running the checkout's own guard), no longer counts a REVIEW.md that only
mentions the rules block in prose, and says why it chose the base. A clean secret scan reads "gitleaks found none
in N commit(s) scanned" in pre-push, `ci` and `status`, which labels it once.

## 0.7.0 (2026-10-24)

`secrets: gitleaks` scans the commits every push adds for secrets (in `status`, pre-push and `ci`),
`.gitleaks*` files are always at least important, and SKILL.md says what to do when a secret turns up.

## 0.6.0 (2026-10-24)

`incidents.py` reports the incident log and checks that every plug still exists; the procedure reads CI
after the push; `upgrade` refreshes every script a repo keeps in `.githooks/`. A pass stamp carries over to a tree that differs
only in paths an explicit `trivial:` glob names, and the stamp line records each check's time. A fork prefers its
`upstream` base branch when that repo has review rules.

## 0.1.1 to 0.5.0

`0.1.1` to `0.5.0` were milestones on the way to `0.6.0`, the release after `0.1.0`; none was released alone.

### 0.5.0

`discover.py` finds a repo's existing checks and tries them on a clean tree; `calibrate.py` shows how a
level table would have judged recent history.

### 0.4.0

A push is judged by its new commits only (those neither the target ref nor the base branch has), so
merging the base branch no longer asks for its commits to be reviewed, and a merge counts only where it differs from git's own merge
(`--remerge-diff`). `ci BASE HEAD` for pull requests, with a workflow template. An agent hook for Claude Code and
Codex. `install` writes a hook file by default, since a config hook is invisible to older git. The last `Review:`
trailer counts, and the printed amend command replaces an earlier one.

### 0.3.0

`setup_tools.py install`, `upgrade` and `doctor`; a per-clone bootstrap that runs the base branch's guard;
`status`, which names the standing rules, the pass stamp, the hook and the next step; pushes to any ref, not only
branches and tags, are checked; `run-suite` says when the stamped tree is not HEAD's; git 2.32+.

### 0.2.0

The guard checks tag pushes, refuses a push that deletes REVIEW.md, treats an unreadable REVIEW.md as
critical instead of deadlocking, ignores user git settings that hid paths or trailers, counts submodule updates,
reads `a, b` as two globs, runs every `test:` line, reports a changed suite, and lints the rules (`check`). The
procedure commits before review, asks the go-ahead before pushes and one-way doors, and ships its own Standards and
Spec reviewer briefs.

### 0.1.1

Tests for the guard (with the known 0.1.0 holes as expected failures), this repo reviewed with its
own skill, and setup that no longer sets `core.hooksPath` over existing hooks.

## 0.1.0 (2026-10-23)

First release.
