# Record an incident

An incident is a defect or rule break found after its author declared the work done (see GLOSSARY.md). When you find
one, in your own work or another agent's (`<skill>` is this skill's directory, which holds SKILL.md):

1. Add an entry to `docs/INCIDENTS.md` in the format of [templates/INCIDENTS.md](../templates/INCIDENTS.md): what
   happened, the slice that should have caught it and why it did not, the failure class, the fix, the plug.
2. If an earlier incident has the same failure class, add this one under its Recurrences instead. A recurrence
   means the earlier plug is weak: say so. A fixed Blocker or Fix its reviewer tagged with an incident's id is one
   too, naming no review load in parentheses (else `--check` counts a miss); any other is a near miss (below).
3. If the slice that should have caught it was a reduced load, name it and the review unit, by the commit that
   carries the unit's trailer, in the Slice field (`2 Review (merged reviewer), unit 1a2b3c4d`,
   `2 Review (adversarial + conformance, large), unit 1a2b3c4d`, naming the pair's size band or Critical), or in the
   recurrence's line, and tell the user; a miss through the pair on a large or Critical unit, before the next one. Where nothing records which load reviewed it, take the one `status` would have printed for that unit (the
   clone's review log; else `python3 <skill>/scripts/calibrate.py --list-candidates <lines> <files>`, with `--rules`
   set to REVIEW.md as of that unit if it changed since: with the small band's limits, a listed Important candidate took one
   merged reviewer and any other Important or Critical unit took adversarial + conformance (three reviewers before
   0.13.0 on large and on Critical medium, large or content units); its band: listed under the medium band's limits,
   medium, else large); never write
   that it was not recorded. Its plug, best first: a test for the class; else narrow that band in REVIEW.md
   (`small: 20 lines, 2 files`), written as a `rule REVIEW.md "<line>"` plug so `--check` notices if it is loosened
   again (narrowing it further edits that plug line in the same change); else a "Failure looks like" rule. A miss
   from a second review unit through the same reduced load, until each miss has a test plug (a recurrence adds a
   test to the Plug field): for the merged reviewer turn off its band, `small: off` (a narrowing plug on that band
   still counts); for adversarial + conformance, the most `status` prints, add `cross-check: on`, never three
   reviewers. `--check` makes it a problem until then. Widening a band is never
   automatic: calibrate shows the evidence, and the user changes the line in a reviewed REVIEW.md change. The built-in
   bands change only by a guard release.
4. Otherwise choose the plug in this order: a test that fails on the class, written over its known shapes (a small
   table of inputs), not only the instance that slipped (the commonest recurrence); a check, a one-line grep or lint
   `test:` line in REVIEW.md's block with single quotes only, ending with the incident's id as a comment
   (`test: ! git grep -n 'old_api(' -- src  # I6`); a guard that fails on the class; else a "Failure looks like"
   rule. Show a new test or check failing on the commit before the fix, named in the Plug line (`(fails on 1a2b3c4)`).
   An incident stays open until its plug exists. Once it has a recurrence, it needs a working test or check plug,
   or a Plug field ending with `(no check: <reason>)`; name each new reason in your report.
5. An incident's class gets a one-line entry in REVIEW.md's "Failure looks like" list, linked to it (an `F` line of
   that class takes its id instead); a near miss's class only as "Near misses" says. Mark a line `(suite)` only when
   every incident it links has a working test or check plug and no recurrence: reviewers then flag only a variant
   its check would miss. Any recurrence voids it.
6. **Check the log:** `python3 <skill>/scripts/incidents.py` lists open incidents with their age, counts per slice
   and recurrences; `--check` exits 1 when a plugged incident's plug is gone (the hole is open again: reopen it),
   when misses from a second review unit through a reduced load leave a band of it on (step 3), or when step 4's
   recurrence rule or step 5's `(suite)` rule is broken. Write plugs as `test <path>::<function>`,
   `check "<test: line>"`, `guard <path>` or `rule REVIEW.md "<line>"` so it can check them. To make that part of
   the suite, copy the script to `.githooks/incidents.py` (`upgrade` keeps it current) and add
   `test: python3 .githooks/incidents.py --check`.

## Near misses

A near miss is a Blocker or Fix from Slice 2 that you accepted and fixed, whose reviewer tagged it `F<n>` or
`none`; never an incident. Log it in `docs/NEAR-MISSES.md` ([templates/NEAR-MISSES.md](../templates/NEAR-MISSES.md),
listed `trivial:`): one line per failure class, one dated sighting per review unit, and `rejected <date> <unit>` for
a rejected finding of a logged class. Promote it with the fix (your go-ahead request names it; no other go-ahead):

- a cheap test or one-line check pins the class: add it at the first sighting, and end the line `plugged: <plug>`;
- else a Blocker: an `F<n>` "Failure looks like" line at the first sighting;
- else a Fix: an `F<n>` line at the second sighting, in a different review unit. One Fix sighting adds no prose.

## Keep the list short

A "Failure looks like" line earns its place only when the mistake is non-obvious, has repeated or would be costly,
and is specific enough to act on. Write it as a trap with a one-clause why: traps to avoid, not maps to follow.
Edit one entry at a time; never regenerate REVIEW.md, the log or docs/NEAR-MISSES.md. `incidents.py` prints two
notes that never change its exit code:

- a one-sighting near miss older than 90 days: delete its line in your next commit, without asking;
- `prune due`: the log's `Last pruned: YYYY-MM-DD` is missing or older than 90 days. REVIEW.md lines are never
  deleted on their own: at the next push go-ahead, show the user each "Failure looks like" line with its plug kind,
  last sighting and `rejected` notes (from REVIEW.md, the log and docs/NEAR-MISSES.md). The user decides; make it
  one reviewed REVIEW.md change, then set `Last pruned:` to that day. Also after a model upgrade, if the user asks.
