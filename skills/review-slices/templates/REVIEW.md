# Review and verification rules

How work in this repo is checked before it counts as done. The procedure is the review-slices skill
(<skill source URL or path>, version <x.y.z>); its GLOSSARY.md defines every term used here. This file holds what
is specific to this repo. Incidents and their plugs: [docs/INCIDENTS.md](docs/INCIDENTS.md).

## Review levels

The guard computes a change's level from this block: the highest level any changed path matches. Raise the level
for the planned actions listed below. Lowering any line needs the user's go-ahead.

```review-slices
test: <the full offline test command, run from the repo root>
base: main
default: simple
critical: <paths whose change contains or enables a one-way door>
important: <core logic, agent instructions, this file, docs/INCIDENTS.md, .githooks/*>
simple: <files tests read, test-only paths>
trivial: <notes and roadmap files no test reads>
```

Planned actions that make a change Critical: <for example a live cloud action, a release tag, a data deletion>.

| Level | Slice 2 review |
|---|---|
| Trivial | none |
| Simple | 1–2 adversarial reviewers |
| Important | code-review (Standards + Spec) + 1 adversarial reviewer |
| Critical | Important's three + the user's go-ahead; a review meeting only for a disputed finding, with the user's yes |

## Failure looks like

What has gone wrong here before. Reviewers check every change against this list. Each line links its incident.

- <one line per failure class> ([I1](docs/INCIDENTS.md#i1-...))

## Repo rules for reviewers

- <files reviewers must never open, commands they must never run, secrets they must never print>

## Known holes in the guard

- A review trailer proves a level was declared, not that a review ran.
- The trailer's base SHA is informational; rebases change it and the guard does not check it.
- The stamp covers the tree `git add -A` would commit; committing only some of the files means running again.
- Planned actions are not visible to the guard; raising the level for them is the author's and reviewers' job.
- The pass stamp is a plain file under `.git/review-slices/`; writing to it by hand forges a pass.
- `git push --no-verify` and `git -c core.hooksPath= push` skip the guard: the user's override only.
- The guard is on only in a clone that ran `git config core.hooksPath .githooks`.
- The guard reads the level block as committed at the push's base, so a change to it applies from the next push.
