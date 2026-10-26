# Incidents

Defects and rule breaks in agents' work that were found after the work was declared done, and the plugs that stop
each failure class from getting through again. Terms: the review-slices skill's GLOSSARY.md. Rules: REVIEW.md.

- One entry per failure class. A later case of the same class goes under that entry's Recurrences, and says why
  the plug did not stop it.
- Status is `open` until the plug exists, then `plugged`. A fix repairs one instance; only a plug closes an entry.
- A plug is, in order of preference: `test <path>::<test function>`, `guard <path>`, `rule REVIEW.md "<line>"`.
- Link to the review finding or log that recorded the case instead of copying it.

## I1. <the failure, in a few words>

- **Date / kind / status:** <YYYY-MM-DD> · <defect or process> · <open or plugged>
- **What happened:** <one to three sentences>
- **Slice that should have caught it:** <slice; for Slice 2, which reviewers, or the reduced load, as in
  `2 Review (merged reviewer)` or `2 Review (adversarial + conformance)`>. Why it did not: <the hole>
- **Failure class:** <the general shape of the mistake>
- **Fix:** <what repaired this instance, or "not yet">
- **Plug:** <test / guard / rule, or "none yet">
- **Recurrences:** <none, or ID and date each, with why the plug missed it; name a reduced load as in the Slice
  field, and the `test <path>::<function>` added for it>
- **Record:** <links>
