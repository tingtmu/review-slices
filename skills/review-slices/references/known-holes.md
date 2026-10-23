# Known holes in the guard

The guard is a hard stop for honest mistakes, not a lock against an agent set on getting past it. These holes
are known; reviewers and the user cover them.

- A review trailer proves a level was declared, not that a review ran. The agent writes its own trailer.
- The trailer's base SHA is informational; rebases change it and the guard does not check it.
- The pass stamp covers the tree `git add -A` would commit; committing only some of the files means running the
  suite again.
- The pass stamp is a plain file under `.git/review-slices/`; writing to it by hand forges a pass.
- Planned actions are not visible to the guard; raising the level for them is the author's and the reviewers' job.
- Levels come from REVIEW.md as committed where the push starts, so a change to the table applies from the next
  push.
- A change to the suite is reported, not blocked. Reviewers check it is not weaker; a weaker package script, skip
  marker or test config is invisible to the guard.
- `git push --no-verify` skips the guard: the user's override only.
- The guard runs only in a clone where it is installed.
