# Review slices

The vocabulary for checking an agent's work before it counts as done, and for learning from what got through
anyway. It describes how a repo is developed, not what the repo builds; a repo's own glossary may reuse none of
these words for other things without saying so.

## Defences

**Slice**:
One independent defence a change passes through before it counts as done. Slices are numbered in time order:
0 Shown output, 1 Offline tests, 2 Review, 3 Go-ahead, 4 Acceptance.
_Avoid_: layer, stage, gate, tier

**Hole**:
A known way a slice lets a defect through.
_Avoid_: gap, weakness

**Shown output**:
The output of commands the author ran on its own change, through tool calls in the same session, with exit codes.
A claim that something works without it is not evidence.
_Avoid_: self-verification, execution evidence, "done" with no output

**Pass stamp**:
A record, made by the suite wrapper, that the full test suite passed on one exact committed tree.
_Avoid_: test cache, green flag

**Review trailer**:
The `Review: <level> <base-sha>` line on the last commit a review covered. It proves a level was declared, not
that a review ran.
_Avoid_: review tag, sign-off

## Review

**Review level**:
How much review a change gets: Trivial, Simple, Important or Critical, computed from the repo's REVIEW.md table of
paths and actions, never chosen by feel.
_Avoid_: tier, risk level, priority

**Review unit**:
The commits one review covers, from a base commit to the head the review saw.
_Avoid_: PR, batch

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
A defect or rule break in an agent's work found after the agent declared it done: committed, pushed, reported done
to the user, or reported done by a subagent to its parent. Its kind is `defect` (the work is wrong) or `process`
(a rule was broken or a loop failed).
_Avoid_: bug, finding, postmortem

**Recurrence**:
A later incident or finding of the same failure class as an earlier incident, listed under that incident.
_Avoid_: duplicate, repeat

**Failure class**:
The general shape of a mistake, named so one fix can cover every instance, such as "a fake kinder than the real
service".
_Avoid_: category, type

**Plug**:
The durable change that closes the hole an incident went through: a test or guard (preferred), else a written
review rule.
_Avoid_: patch, lesson, fix (a fix repairs one instance; a plug stops the class)
