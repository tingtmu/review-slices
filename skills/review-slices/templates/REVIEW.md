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
# critical code: <critical code a reviewer can judge from a small diff>   (optional; see below)
important: <core logic>
important: <agent instructions, such as AGENTS.md>
simple: <files tests read, test-only paths>
trivial: <notes and roadmap files no check reads>
# secrets: gitleaks   (optional: scan the commits every push adds; needs gitleaks 8.19+ and git 2.36+)
# small: 40 lines, 3 files     (optional size bands of the review load; or off)
# medium: 200 lines, 10 files
```

Planned actions that make a change Critical: <for example a live cloud action, a release tag, a data deletion>.

`status` prints the review load (which reviewers) at Important and Critical, from the size band of everything a
branch adds to the base branch (`small:` and `medium:`; built in: small 40 lines, 3 files, no medium; at most 80/5
and 400/20) and the glob kind. A `critical:` glob is content, such as golden outputs, corpora, state tables or CI,
and always takes three reviewers; a `critical code:` glob is code a reviewer can judge from a small diff. Loosening a
band or tagging a glob as code is a reviewed change to this file.

| Level | Slice 2 review |
|---|---|
| Trivial | none |
| Simple | 1–2 adversarial reviewers |
| Important | small: one merged reviewer; medium: an adversarial and a conformance reviewer; large: a Standards, a Spec and an adversarial reviewer |
| Critical | small and only in `critical code:` globs: an adversarial and a conformance reviewer; else the three. Then the user's go-ahead for the one-way door; a review meeting only for a disputed review finding, with the user's yes |

## Remote checks

Checks that run only in CI or another remote service, outside the suite. Read their result after the push.

- <check name, where it runs, and why it cannot run locally>

## Failure looks like

What has gone wrong here before. Reviewers check every change against this list. Each line links its incident.

- <one line per failure class, linked to its incident, e.g. ([I1](docs/INCIDENTS.md#i1-...)); delete this line
  until the first incident>

## Repo rules for reviewers

- <files reviewers must never open, commands they must never run, secrets they must never print>

The guard's known holes: the review-slices skill's `references/known-holes.md`.
