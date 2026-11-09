# Near misses

Blocker and Fix review findings that review caught and the author accepted and fixed, whose reviewer tagged them
with an `F<n>` "Failure looks like" entry or `none`. A finding tagged with an incident's id is a Recurrence in
docs/INCIDENTS.md instead. A near miss is never an incident. Terms: the review-slices skill's GLOSSARY.md; how to
promote one: its references/incidents.md. No check reads this file, so REVIEW.md lists it `trivial:`.

- One line per failure class: its `F<n>` id once it has one, the class as a trap, then one sighting per review
  unit: the date, the short hash of the head review read, and Blocker or Fix.
- A rejected review finding of a logged class: `rejected <date> <unit>` on its line, read at pruning.
- Once a test or check pins the class: `plugged: <plug>` at the end of its line.
- A line with one sighting older than 90 days: delete it in your next commit (`incidents.py` names it).

```
- F2 <the class, as a trap> — 2026-11-09 abc1234 Blocker, 2026-11-12 def5678 Fix; rejected 2026-11-13 9abc012; plugged: <plug>
```

Lines go below.
