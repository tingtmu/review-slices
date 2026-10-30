# Record an incident

An incident is a defect or rule break found after its author declared the work done (see GLOSSARY.md). When you find
one, in your own work or another agent's (`<skill>` is this skill's directory, which holds SKILL.md):

1. Add an entry to `docs/INCIDENTS.md` in the format of [templates/INCIDENTS.md](../templates/INCIDENTS.md): what
   happened, the slice that should have caught it and why it did not, the failure class, the fix, the plug.
2. If an earlier incident has the same failure class, add this one under its Recurrences instead. A recurrence
   means the earlier plug is weak: say so.
3. If the slice that should have caught it was a reduced load, name it in the Slice field
   (`2 Review (merged reviewer)`, `2 Review (adversarial + conformance)`), or in the recurrence's line, and tell the
   user. Where nothing records which load reviewed it, take the one `status` would have printed for that unit (the
   clone's review log; else `python3 <skill>/scripts/calibrate.py --list-candidates <lines> <files>` with the small
   band's limits, which lists by sha the Important units that take one merged reviewer, or the medium band's for
   adversarial + conformance, with `--rules` set to REVIEW.md as of that unit if it changed since); never write that
   it was not recorded. Its plug, best first: a test for the class; else narrow that band in REVIEW.md
   (`small: 20 lines, 2 files`), written as a `rule REVIEW.md "<line>"` plug so `--check` notices if it is loosened
   again (narrowing it further edits that plug line in the same change); else a "Failure looks like" rule. A second
   miss through the same reduced load: turn off every band that gives that load until each miss has a test plug (a
   recurrence adds a test to the Plug field): `small: off` for the merged reviewer; `medium: off` for adversarial +
   conformance, and `small: off` too while REVIEW.md has a `critical code:` line (or tag those globs `critical:`); a
   narrowing plug on that band still counts. `--check` makes it a problem until then. Widening a band is never
   automatic: calibrate shows the evidence, and the user changes the line in a reviewed REVIEW.md change. The built-in
   bands change only by a guard release.
4. Otherwise choose the plug in this order: a test or guard that fails on the class; else a rule in REVIEW.md's
   "Failure looks like" list. An incident stays open until its plug exists.
5. A new failure class gets a one-line entry in REVIEW.md's "Failure looks like" list, linked to the incident.
6. **Check the log:** `python3 <skill>/scripts/incidents.py` lists open incidents with their age, counts per slice
   and recurrences; `--check` exits 1 when a plugged incident's plug is gone (the hole is open again: reopen it),
   or when a second miss through a reduced load leaves a band of it on (step 3).
   Write plugs as `test <path>::<function>`, `guard <path>` or `rule REVIEW.md "<line>"` so it can check them. To
   make that part of the suite, copy the script to `.githooks/incidents.py` (`upgrade` keeps it current) and add
   `test: python3 .githooks/incidents.py --check`.
