# Known holes in the guard

The guard is a hard stop for honest mistakes, not a lock against an agent set on getting past it. It catches a
missing pass stamp, a missing review trailer, a secret in a pushed commit and the like; it cannot tell that a review
really ran. Reviewers and the user cover that gap.

What that means for you:

- Do not try to get past the guard; overriding it is the user's call, never yours.
- Raise the level for planned actions yourself: the guard cannot see them.
- Run the load `status` printed; fewer is the user's call, never yours (except step 6's second round and a
  version-swap release REVIEW.md on the base branch allows).
- A pass stamp is proof only if the suite really ran, and it covers the tree `git add -A` would commit: commit
  only some of the files and run the suite again. A trailer only says a level was declared.

The full list of known holes is in the review-slices repo under `docs/known-holes.md`
(https://github.com/tingtmu/review-slices). Add a new hole there, not here.
