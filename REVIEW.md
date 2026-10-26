# Review and verification rules

How work in this repo is checked before it counts as done. The procedure is this repo's own skill
([skills/review-slices](skills/review-slices/SKILL.md)); its [GLOSSARY.md](skills/review-slices/GLOSSARY.md)
defines every term used here. This file holds what is specific to this repo. Incidents and their plugs:
[docs/INCIDENTS.md](docs/INCIDENTS.md).

## Review levels

The guard computes a change's level from this block: the highest level any changed path matches.

```review-slices
test: python3 -m unittest discover -s tests -q
test: python3 skills/review-slices/scripts/incidents.py --check
secrets: gitleaks
base: main
default: simple
important: skills/review-slices/*
important: .githooks/*
important: REVIEW.md
important: docs/INCIDENTS.md
important: .github/*
important: .claude/*
important: .codex/*
important: tests/*
simple: README.md
```

Planned actions that make a change Critical: a release tag; a change to the pass stamp or review trailer
format, or to how the hook is installed, since every adopting clone depends on them.

The one exception to the three reviewers a raised level or a floor path takes (the skill's SKILL.md step 4): a
release commit whose only changed lines outside README.md swap the version for a newer one (`VERSION = "x"` and
`(skill version x)`) takes one merged reviewer, and its second round stays one merged reviewer while the fix commits
touch only README.md. It applies only as written in `git show <base>:REVIEW.md`, never as a branch edits it, and
only after the author shows that the base's copy of the release check,
`git show <base>:tests/release_check.py | python3 -I - --base <base>`, prints its `release check: OK` line and exits
0 (no output is a fail: the base has no check to run). It takes OLD
from the base guard's `VERSION` and NEW from HEAD's, and fails unless NEW is higher, each file changed outside
README.md is its base copy with only those two forms swapped (byte for byte, whitespace included), every changed
entry is `M` with its mode kept, and no file outside README.md still holds an OLD form. The merged reviewer's
adversarial part re-runs that command itself. The user's go-ahead, the pull request and green CI stay.

## Remote checks

Checks that run only in CI or another remote service, outside the suite. Read their result after the push.

- `tests / old-git` (GitHub Actions, an `ubuntu:22.04` container): the suite on git 2.34, the only run of the
  fallbacks for git before 2.36 and 2.54 and of the tests only an old git runs; no local git here is that old.

## Failure looks like

- The guard trusts input the change itself controls ([I1](docs/INCIDENTS.md#i1-the-guard-trusts-input-the-change-controls))
- The guard fails open on input it did not expect ([I2](docs/INCIDENTS.md#i2-the-guard-fails-open-on-unexpected-input))
- A push is measured across commits that are not the author's ([I3](docs/INCIDENTS.md#i3-a-push-is-measured-across-other-peoples-commits))
- A tool runs a one-way door it should only list ([I5](docs/INCIDENTS.md#i5-a-setup-tool-runs-a-one-way-door-it-should-only-list))
- Setup breaks the host repo's existing hooks or checks ([I4](docs/INCIDENTS.md#i4-setup-breaks-the-host-repos-existing-tooling))

## Repo rules for reviewers

- Tests build throwaway repos under the system temp directory; never point them at this clone.
- Never run `git push`, `git gh` or anything that changes authentication; this repo publishes the skill.
