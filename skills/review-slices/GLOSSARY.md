# Review slices

The vocabulary for checking an agent's work before it counts as done, and for learning from what got through
anyway. It describes how a repo is developed, not what the repo builds. A repo's own glossary may reuse one of
these words for something else only if it says so. The _Avoid_ words are other names for these concepts; in
their everyday senses (to stage a file, a pull request template, the ref a push targets) they are fine, and the
skill's description quotes the words users say.

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
Every offline check listed in the REVIEW.md of the tree being tested, such as tests, lint, type checks and builds,
run together on that tree. A change to the suite is reviewed, not blocked.
_Avoid_: test command, checks (unqualified)

**Remote check**:
A check that runs only on a remote service such as CI, outside the suite.
_Avoid_: CI-only check

**Pass stamp**:
A record, made by the suite wrapper, that the suite passed on one exact tree, the tree a pushed commit must have;
it also covers a tree that differs from it only in paths an explicit trivial glob names.
_Avoid_: test cache, green flag

**Review trailer**:
The `Review: <level> <base-sha>` line on the last commit of a review unit. It proves a level was declared, not that
a review ran.
_Avoid_: review tag, sign-off

**Guard**:
An automatic check, other than a test, that refuses work showing a failure class. The review-slices guard checks
pass stamps and review trailers before a push, and runs the secret scan where REVIEW.md asks for it.
_Avoid_: gate, blocker (Blocker is a review finding tag)

**Secret scan**:
The guard's gitleaks run over exactly the commits a push adds, on with `secrets: gitleaks`; a finding, or a scan
that could not run, refuses the push.
_Avoid_: leak check, secret lint

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

**Review load**:
The reviewers a review unit gets at its review level, computed by `status` from the level, the size band and the
glob kind of the paths that set the level. Never chosen by the agent; never recorded in the trailer. A unit's load is
the highest one `status` printed since the unit began; after rewriting history inside a unit (amend, squash,
rebase) it is the three reviewers.
_Avoid_: sub-level, subgrade, tier, light review

**Size band**:
Small, medium or large, by the weighted lines and files of every commit the branch adds to the base branch (not
only those a push adds, so a change pushed in slices is measured whole), against the standing rules' `small:` and
`medium:` lines (built-in defaults where absent). A floor path, a binary file, a submodule update, uncommitted work
or a merge with changes of its own puts a change in no band below large.
_Avoid_: size class, tier

**Glob kind**:
Whether a critical glob's files are code a reviewer can judge from a small diff (`critical code:`), or content whose
small diff can change what counts as correct, such as golden outputs, corpora, state tables or CI (`critical:`, the
default). A path is code only if every critical glob it matches is a code glob and it is no floor path.
_Avoid_: type, engine, category

**Review unit**:
The new commits one review covers: from the previous review trailer, or from what the remote already has, up to
the commit that carries the trailer.
_Avoid_: PR, batch, range

**Level note**:
A reviewer's one line that a change's level looks higher than it needs, naming the glob that set it and the level
it would give that glob. Reported to the user, never a review finding, never acted on in the same change.
_Avoid_: level finding, downgrade

**Review finding**:
One defect a reviewer reports, with file and line, tagged Blocker, Fix, Nit or Pre-existing.
_Avoid_: comment, issue, finding (unqualified)

**Adversarial reviewer**:
A reviewer with fresh context told to assume the change is wrong and to show how it fails.
_Avoid_: red team, devil's advocate

**Merged reviewer**:
One reviewer who takes the adversarial, Standards and Spec lenses in turn: the review load of an Important change
in the small band. Never at Critical, on a raised level, a floor path or a merge with changes of its own.
_Avoid_: light review, quick review

**Conformance reviewer**:
One reviewer who takes the Standards and Spec lenses in turn: both compare the change against written text. It pairs
with a dedicated adversarial reviewer.
_Avoid_: merged reviewer (that one takes all three lenses), compliance reviewer

**Escalation**:
Moving a review unit to the three reviewers on the whole unit because a reduced load's round flagged something
(SKILL.md step 5). Never the reverse.
_Avoid_: upgrade, bump

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
