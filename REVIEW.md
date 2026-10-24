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

## Failure looks like

- The guard trusts input the change itself controls ([I1](docs/INCIDENTS.md#i1-the-guard-trusts-input-the-change-controls))
- The guard fails open on input it did not expect ([I2](docs/INCIDENTS.md#i2-the-guard-fails-open-on-unexpected-input))
- A push is measured across commits that are not the author's ([I3](docs/INCIDENTS.md#i3-a-push-is-measured-across-other-peoples-commits))
- A tool runs a one-way door it should only list ([I5](docs/INCIDENTS.md#i5-a-setup-tool-runs-a-one-way-door-it-should-only-list))
- Setup breaks the host repo's existing hooks or checks ([I4](docs/INCIDENTS.md#i4-setup-breaks-the-host-repos-existing-tooling))

## Repo rules for reviewers

- Tests build throwaway repos under the system temp directory; never point them at this clone.
- Never run `git push`, `git gh` or anything that changes authentication; this repo publishes the skill.
