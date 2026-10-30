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
band (after a unit that is over every band's line limit on its own and that the clone's review log shows went to
three reviewers, it measures only what follows that unit, so later small fixes get the lighter load again): small (built in: at most 40 weighted lines and 3 files), medium (none built in) or large. A file moved
unchanged counts as one file and no lines. Uncommitted work, an unfetched base branch, a floor path, a merge with
changes of its own, a submodule update or a binary or Git LFS file added, edited or deleted make it large. Important
takes one merged reviewer when small, an adversarial and a conformance (Standards and Spec) reviewer when medium, and
the three otherwise. Critical takes the adversarial and conformance pair only when small and every path that sets the
level is in a `critical code:` glob; plain `critical:` globs are content (golden outputs, corpora, CI) and always
take three. REVIEW.md's `small:` and `medium:` lines set the bands, up to 80/5 and 400/20; the standing rules' lines
count, never a branch's own. A level the author raised for a planned action, which `status` cannot see, takes three
(except a version-swap release where the base branch's REVIEW.md says so), and `status BASE` takes three. The
measure, `.githooks/merged_reviewer.py`, is copied by `install`, added by `upgrade`, and loaded from the base branch
like the guard; without it there, `status` says three reviewers. Each load `status` prints for committed work goes
into the clone's review log, `<git-common-dir>/review-slices/review-log`, by branch and review unit: a unit keeps the
highest load printed since it began (`held:`), and takes three once a commit a load was printed at leaves the
branch's history (amend, squash, rebase); a logged three on a unit large on its own also lets the measure start
after that unit. `calibrate.py`'s logged loads section reads it to show the loads units really got.

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
`.gitleaksignore` fingerprints that name a commit apply, and a missing or failed scan refuses the push. The skill's
"A secret turns up" ([references/secrets.md](skills/review-slices/references/secrets.md)) says how to remove one. The CI template installs a pinned, checksum-verified gitleaks.

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

Release notes are in [CHANGELOG.md](CHANGELOG.md). Each release is tagged `vX.Y.Z`; from 0.9.2 on, each
also has a GitHub Release with the same notes.
