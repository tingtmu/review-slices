# What the guard does not promise

The guard is a hard stop for honest mistakes, not a lock against an agent set on getting past it. It catches a
missing pass stamp, a missing review trailer, a secret in a pushed commit and the like; it cannot tell that a review
really ran, or stop a determined bypass. Reviewers and the user cover that gap.

What that means for you:

- Do not try to get past the guard. `git push --no-verify`, changing the hook's git config, an edited guard or
  hand-written pass stamps are the user's override only.
- Raise the level for planned actions yourself: the guard cannot see them.
- A pass stamp is proof only if the suite really ran; a trailer only says a level was declared.

The full list of known holes is in the review-slices repo under `docs/known-holes.md`. Add a new hole there, not here.
