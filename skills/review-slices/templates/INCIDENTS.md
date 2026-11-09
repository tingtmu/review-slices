# Incidents

Defects and rule breaks in agents' work that were found after the work was declared done, and the plugs that stop
each failure class from getting through again. Terms: the review-slices skill's GLOSSARY.md. Rules: REVIEW.md.

- One entry per failure class. A later case of the same class goes under that entry's Recurrences, and says why
  the plug did not stop it.
- Status is `open` until the plug exists, then `plugged`. A fix repairs one instance; only a plug closes an entry.
- A plug is, in order of preference: `test <path>::<test function>`; `check "<test: line>"`, a one-line grep or lint
  `test:` line of REVIEW.md's block, single quotes only, ending with `# <this incident's id>`; `guard <path>`;
  `rule REVIEW.md "<line>"`. A new test or check is shown failing on the commit before the fix, named in the Plug
  line. Once an entry has a recurrence, it needs a working test or check plug, or `(no check: <reason>)`.
- Link to the review finding or log that recorded the case instead of copying it.

Last pruned: <YYYY-MM-DD, the day the user last pruned REVIEW.md's "Failure looks like" list; at setup, that day>

## I1. <the failure, in a few words>

- **Date / kind / status:** <YYYY-MM-DD> · <defect or process> · <open or plugged>
- **What happened:** <one to three sentences>
- **Slice that should have caught it:** <slice; for Slice 2, which reviewers, or the reduced load and the unit's
  trailer commit, as in `2 Review (merged reviewer), unit 1a2b3c4d` or
  `2 Review (adversarial + conformance, large), unit 1a2b3c4d`>. Why it did not: <the hole>
- **Failure class:** <the general shape of the mistake>
- **Fix:** <what repaired this instance, or "not yet">
- **Plug:** <test / check / guard / rule, a new test or check with `(fails on <pre-fix commit>)`; or "none yet";
  end with `(no check: <reason>)` when it has a recurrence and no test or check>
- **Recurrences:** <none, or ID and date each, with why the plug missed it; name a reduced load and its unit as
  in the Slice field, and add its test to the Plug field. A review finding tagged with this id: its date and unit,
  no load>
- **Record:** <links>
