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
                                               # (it carries over to changes of explicitly trivial paths only)
python3 <skill>/scripts/setup_tools.py doctor  # is this clone's hook wired, and is the setup sound
```

`install` never sets `core.hooksPath`: it writes a pre-push hook file that every git runs and chains any hook
already there (git-lfs, pre-commit), or beside Husky registers a git config hook. Each clone keeps a small
bootstrap that runs the guard committed on the base branch, so an edited copy never judges its own push and a fix
to the guard reaches every clone by push. Only clones that run `install` are checked; nobody else is blocked.

Before writing REVIEW.md, `discover.py` lists the checks the repo already has (CI files, package scripts, Makefile
and more), marked local or remote, and `--run` tries the local ones on a clean tree. `calibrate.py` shows how a draft
level table would have judged the base branch's last 50 commits and, by review unit, which globs set the levels,
what each level costs in size, which small important units one merged reviewer could take, and the review load
each unit would get under the draft's size bands and glob kinds.
`incidents.py [--check]` reports docs/INCIDENTS.md and checks that every plug still exists. All three run from the
skill's `scripts/`; `incidents.py` can also be copied into `.githooks/` to run in a repo's suite, and `upgrade`
keeps it current.

At important and critical, `status` prints the review load: which reviewers the change needs. It measures every
commit the branch adds to the base branch, so a change pushed in slices is measured whole, and puts it in a size
band: small (built in: at most 40 weighted lines and 3 files), medium (none built in) or large. Uncommitted work, an
unfetched base branch, a floor path, a merge with changes of its own, a submodule update or a binary or Git LFS file
make it large. Important takes one merged reviewer when small, an adversarial and a conformance (Standards and Spec)
reviewer when medium, and the three otherwise. Critical takes the adversarial and conformance pair only when small
and every path that sets the level is in a `critical code:` glob; plain `critical:` globs are content (golden
outputs, corpora, CI) and always take three. REVIEW.md's `small:` and `medium:` lines set the bands, up to 80/5
and 400/20; the standing rules' lines count, never a branch's own. A level the author raised for a planned action,
which `status` cannot see, takes three (except a version-swap release where the base branch's REVIEW.md says so),
and `status BASE` takes three. The measure, `.githooks/merged_reviewer.py`,
is copied by `install`, added by `upgrade`, and loaded from the base branch like the guard; without it there,
`status` says three reviewers.

`install --agent-hooks` also adds a PreToolUse hook for Claude Code (`.claude/settings.json`) and Codex
(`.codex/hooks.json`, shell commands only, once its hooks feature is on and the user trusts the hook; a refused
`git push --no-verify` checked live with Codex 0.164.0) that refuses an agent's overrides: `--no-verify`, rewiring
the hook, writing pass stamps, amending content into reviewed work. For checks no clone can skip, copy
`templates/review-slices-ci.yml` to `.github/workflows/`: it runs `review_slices.py ci` on every pull request.

### Secret scanning

The procedure commits before review, so a secret can land in a local commit; a later fix commit would still
publish it. With `secrets: gitleaks` in REVIEW.md's block, `status`, the pre-push hook and `ci` scan exactly the
commits a push adds with [gitleaks](https://github.com/gitleaks/gitleaks) 8.19+ (and git 2.36+, to read merge
commits). The scanner, `.githooks/secret_scan.py`, and its `.gitleaks.toml` come from the base branch like the
guard. Settings, attributes and `gitleaks:allow` markers cannot hide a line, only the pushed commit's committed
`.gitleaksignore` fingerprints that name a commit apply, and a missing or failed scan refuses the push. SKILL.md's
"A secret turns up" says how to remove one. The CI template installs a pinned, checksum-verified gitleaks.

To also stop a secret before it is committed, a hook of your own in `.git/hooks/pre-commit` (setup never installs
one) can run the staged scan:

```sh
#!/bin/sh
exec gitleaks git --pre-commit --staged --redact --no-banner -v
```

On GitHub, turn on push protection where your plan has it: it is free for public repositories and part of the
paid GitHub Secret Protection for private ones. It is the only check on the server.

The guard needs Python 3.8+ and git 2.32+, and nothing else. On GitHub, reading CI after a push (SKILL.md
step 10) needs GitHub CLI 2.40.0+, for `gh run list --commit`; step 10's other `gh` commands work from 2.6.0.

## Versions

`0.1.0`: first release, 2026-10-23.

`0.1.1` to `0.5.0` were milestones on the way to `0.6.0`, the release after `0.1.0`; none was released alone.

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

`0.4.0`: a push is judged by its new commits only (those neither the target ref nor the base branch has), so
merging the base branch no longer asks for its commits to be reviewed, and a merge counts only where it differs from git's own merge
(`--remerge-diff`). `ci BASE HEAD` for pull requests, with a workflow template. An agent hook for Claude Code and
Codex. `install` writes a hook file by default, since a config hook is invisible to older git. The last `Review:`
trailer counts, and the printed amend command replaces an earlier one.

`0.5.0`: `discover.py` finds a repo's existing checks and tries them on a clean tree; `calibrate.py` shows how a
level table would have judged recent history.

`0.6.0`: `incidents.py` reports the incident log and checks that every plug still exists; the procedure reads CI
after the push; `upgrade` refreshes every script a repo keeps in `.githooks/`. A pass stamp carries over to a tree that differs
only in paths an explicit `trivial:` glob names, and the stamp line records each check's time. A fork prefers its
`upstream` base branch when that repo has review rules.

`0.7.0`: `secrets: gitleaks` scans the commits every push adds for secrets (in `status`, pre-push and `ci`),
`.gitleaks*` files are always at least important, and SKILL.md says what to do when a secret turns up.

`0.7.1`: `install` makes a remote other than origin the base branch only when it has review rules (a fork whose
base branch tracked such a remote kept running the checkout's own guard), no longer counts a REVIEW.md that only
mentions the rules block in prose, and says why it chose the base. A clean secret scan reads "gitleaks found none
in N commit(s) scanned" in pre-push, `ci` and `status`, which labels it once.

`0.8.0`: at important, `status` says whether one merged reviewer may take a small push (at most 40 weighted lines
and 3 files) or why it needs three; the measure is a new vendored `.githooks/merged_reviewer.py`, loaded from the
base branch like the guard, which `upgrade` adds. Reviewers add a level note when a level looks higher than the
change needs and read REVIEW.md and the agent instruction files as committed at the standing rules' commit; a
change to those files, `.claude/` or `.codex/` gets a CLI reviewer started in an empty directory. `calibrate.py`
adds, by review unit, which globs set the levels, declared vs computed levels, size by level, an estimate of
whitespace- or comment-only units, and the merged-reviewer candidates (`--list-candidates LINES FILES`); in a
partial clone it runs only the first section and fetches nothing. The vendored copies no longer trip ruff's PGH004
under `--select ALL`. The agent hook is checked live with Codex 0.164.0, which shows it shell commands only, so
`apply_patch` edits are a known hole.

`0.9.0`: `status` prints the review load at important and critical: which reviewers a change needs, from the size
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

`0.9.1`: every Python the hooks start runs isolated and without site (`python3 -I -S`): the agent hook, the pre-push
hook file and config hook, the bootstrap and the guard's hand-off. Before, a stdlib-named file the agent wrote in
the working directory (`json.py`) or beside the bootstrap, or a `.pth` file in a virtualenv on PATH, could stand in
for the hook's imports, so the agent hook allowed `git push --no-verify` or the pre-push hook passed. `doctor` names
a hook or an agent hook command an older install wrote; `install --agent-hooks --apply` rewrites both, and the
`.claude` and `.codex` settings it writes are committed changes. A push whose command line sets `PATH` or git's own
variables, a `python3` or `git` shim on PATH, and a stdlib-named file in `.githooks/` when the agent runs the guard
itself are listed as known holes.
