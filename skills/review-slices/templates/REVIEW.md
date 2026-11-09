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
# test: bandit -r <package> -q   (optional: a security scanner; gosec for Go, semgrep with local rules elsewhere)
base: main
default: simple
critical: <a path whose change contains or enables a one-way door>
# critical code: <critical code a reviewer can judge from a small diff>   (optional; see below)
important: <core logic>
important: <agent instructions, such as AGENTS.md>
simple: <files tests read, test-only paths>
trivial: <notes and roadmap files no check reads>
trivial: docs/NEAR-MISSES.md
# secrets: gitleaks   (optional: scan the commits every push adds; needs gitleaks 8.19+ and git 2.36+)
# small: 40 lines, 3 files     (optional size bands of the review load; or off)
# medium: 200 lines, 10 files
# cross-check: on     (optional: a cross-check reviewer on every pair unit; needs a 0.13.0+ guard on the base branch)
# copy-credit: <spec or doc globs>   (optional: text a file move copies there counts no lines; 0.14.0+ guard)
```

Planned actions that make a change Critical: <for example a live cloud action, a release tag, a data deletion>.

`status` prints the review load (which reviewers) at Important and Critical, from the size band of everything a
branch adds to the base branch, or since its last unit large on its own that got the ceiling load (`small:` and `medium:`; built in: small 40 lines, 3 files, no medium; at most 80/5
and 400/20) and the glob kind. The most it prints is the adversarial and conformance pair. A `critical:` glob is
content, such as golden outputs, corpora, state tables or CI; a `critical code:` glob is code a reviewer can judge
from a small diff. A content or floor path coming into a unit makes `status` print `escalate:`. `cross-check: on` adds a cross-check reviewer to every pair unit (`incidents.py --check` asks for
it after misses through the pair). In a commit that moves a file under the `copy-credit:` globs, text already there counts no
lines. Loosening a band, naming copy-credit globs or tagging a glob as code is a reviewed change to this file.

| Level | Slice 2 review |
|---|---|
| Trivial | none |
| Simple | 1–2 adversarial reviewers |
| Important | small: one merged reviewer; medium and large: an adversarial and a conformance reviewer |
| Critical | an adversarial and a conformance reviewer. Then the user's go-ahead for the one-way door; a review meeting only for a disputed review finding, with the user's yes |

The load `status` prints is binding: fewer reviewers, or lenses merged into fewer, only with the user's go-ahead
asked before the round (except later rounds, as the skill's step 6 says, and a version-swap release this file
allows on the base branch).

## Remote checks

Checks that run only in CI or another remote service, outside the suite. Read their result after the push.

- <check name, where it runs, and why it cannot run locally>

## Failure looks like

What has gone wrong here before, or would hurt most. Reviewers check every change against this list and name the
entry a review finding falls under by its id. Each line has one: F1, F2, ... until an incident records its class,
then that incident's, linked. A line ends with `(suite)` only when every incident it links has a working test or
check plug and no recurrence (`incidents.py --check` holds this): the suite ran green on it, so reviewers flag only
a variant its check would miss.

A line earns its place only when the mistake is non-obvious, has repeated or would be costly, and is specific
enough to act on. Write it as a trap with a one-clause why: traps to avoid, not maps to follow. Edit one line at a
time; never regenerate this file. Lines are deleted only when the user prunes the list (the review-slices skill's
references/incidents.md).

- <one line per failure class, e.g. `F1. A new route skips the token check`, or, once incident I1 records it,
  `A new route skips the token check ([I1](docs/INCIDENTS.md#i1-...))`; delete this line if there is none yet>

## Repo rules for reviewers

- <files reviewers must never open, commands they must never run, secrets they must never print>

The guard's known holes: the review-slices skill's `references/known-holes.md`.
