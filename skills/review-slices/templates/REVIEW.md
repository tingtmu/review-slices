# Review and verification rules

How work in this repo is checked before it counts as done. The procedure is the review-slices skill
(https://github.com/tingtmu/review-slices, version <the version `review_slices.py --version` prints>); its
GLOSSARY.md defines every term used here. This file holds what
is specific to this repo. Incidents and their plugs: [docs/INCIDENTS.md](docs/INCIDENTS.md).

## Review levels

The guard computes a change's level from this block: the highest level any changed path matches. REVIEW.md and
`.githooks/*` are always at least Important, whatever the block says. Write one glob per line; `*` also matches
`/`. Raise the level for the planned actions listed below. Lowering any line needs the user's go-ahead. Delete a
level's line if no path belongs there yet.

```review-slices
test: <one offline check, run from the repo root; repeat the line for each check, all are required>
base: main
default: simple
critical: <a path whose change contains or enables a one-way door>
important: <core logic>
important: <agent instructions, such as AGENTS.md>
simple: <files tests read, test-only paths>
trivial: <notes and roadmap files no check reads>
# secrets: gitleaks   (optional: scan the commits every push adds; needs gitleaks 8.19+ and git 2.36+)
```

Planned actions that make a change Critical: <for example a live cloud action, a release tag, a data deletion>.

| Level | Slice 2 review |
|---|---|
| Trivial | none |
| Simple | 1–2 adversarial reviewers |
| Important | a Standards, a Spec and an adversarial reviewer |
| Critical | Important's three + the user's go-ahead for the one-way door; a review meeting only for a disputed review finding, with the user's yes |

## Remote checks

Checks that run only in CI or another remote service, outside the suite. Read their result after the push.

- <check name, where it runs, and why it cannot run locally>

## Failure looks like

What has gone wrong here before. Reviewers check every change against this list. Each line links its incident.

- <one line per failure class, linked to its incident, e.g. ([I1](docs/INCIDENTS.md#i1-...)); delete this line
  until the first incident>

## Repo rules for reviewers

- <files reviewers must never open, commands they must never run, secrets they must never print>

What the guard cannot see: the review-slices skill's `references/known-holes.md`.
