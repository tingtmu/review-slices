# Review slices

The vocabulary for checking an agent's work before it counts as done, and for learning from what got through
anyway. It describes how a repo is developed, not what the repo builds. A repo's own glossary may reuse one of
these words for something else only if it says so.

## Defences

**Slice**:
One independent defence a change passes through before it counts as done. Slices are numbered in time order:
0 Shown output, 1 Offline suite, 2 Review, 3 Go-ahead, 4 Acceptance.
_Avoid_: layer, stage, gate, tier

**Hole**:
A known way a slice lets a defect through.
_Avoid_: gap, weakness

**Shown output**:
The output of commands the author ran on its own change, through tool calls in the same session, with exit codes.
A claim that something works without it is not evidence.
_Avoid_: self-verification, execution evidence, "done" with no output

**Suite**:
Every offline check the standing rules list, such as tests, lint, type checks and builds, run together on one tree.
_Avoid_: test command, checks (unqualified)

**Remote check**:
A check that runs only on a remote service such as CI, outside the suite.
_Avoid_: CI-only check

**Pass stamp**:
A record, made by the suite wrapper, that the suite passed on one exact tree, the tree a pushed commit must have.
_Avoid_: test cache, green flag

**Review trailer**:
The `Review: <level> <base-sha>` line on the last commit of a review unit. It proves a level was declared, not that
a review ran.
_Avoid_: review tag, sign-off

**Guard**:
An automatic check, other than a test, that refuses work showing a failure class. The review-slices guard checks
pass stamps and review trailers before a push.
_Avoid_: gate, blocker (Blocker is a review finding tag)

**Override**:
A way past the guard that only the user may take, such as skipping the push hook. An agent taking one is an
incident.
_Avoid_: bypass, escape hatch

## Review

**Base branch**:
The branch work is measured against and merged into, usually main.
_Avoid_: trunk, target, main (when the base branch has another name)

**Standing rules**:
The repo's REVIEW.md as committed on the base branch where a change's branch left it. A change is judged by the
standing rules, never by its own edits to them.
_Avoid_: judge commit, current rules

**Review level**:
How much review a change gets: Trivial, Simple, Important or Critical. It is computed from the standing rules' table
of paths and actions, never chosen by feel.
_Avoid_: tier, risk level, priority

**Review unit**:
The new commits one review covers: from the previous review trailer, or from what the remote already has, up to
the commit that carries the trailer.
_Avoid_: PR, batch, range

**Review finding**:
One defect a reviewer reports, with file and line, tagged Blocker, Fix, Nit or Pre-existing.
_Avoid_: comment, issue, finding (unqualified)

**Adversarial reviewer**:
A reviewer with fresh context told to assume the change is wrong and to show how it fails.
_Avoid_: red team, devil's advocate

**Review meeting**:
A multi-agent decision meeting limited to disputed review findings, held only with the user's go-ahead.
_Avoid_: verifier voting, voting panel

**One-way door**:
An action or change that cannot be cleanly undone, such as deleting data, a release tag, a persisted format or a
live cloud action.
_Avoid_: irreversible change

**Go-ahead**:
The user's explicit permission for one specific action.
_Avoid_: consent, sign-off

## Learning

**Incident**:
A defect or rule break in an agent's work found after the agent declared it done: a commit with a review trailer,
a push, a report of done to the user, or a subagent's report of done to its parent. Its kind is `defect` (the work
is wrong) or `process` (a rule was broken or a loop failed).
_Avoid_: bug, finding, postmortem

**Recurrence**:
A later incident or review finding of the same failure class as an earlier incident, listed under that incident.
_Avoid_: duplicate, repeat

**Failure class**:
The general shape of a mistake, named so one fix can cover every instance, such as "a fake kinder than the real
service".
_Avoid_: category, type

**Plug**:
The durable change that closes the hole an incident went through: a test or guard (preferred), else a written
review rule.
_Avoid_: patch, lesson, fix (a fix repairs one instance; a plug stops the class)
