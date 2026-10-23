# Known holes in the guard

The guard is a hard stop for honest mistakes, not a lock against an agent set on getting past it. These holes
are known; reviewers and the user cover them.

- A review trailer proves a level was declared, not that a review ran. The agent writes its own trailer.
- The trailer's base SHA is informational; rebases change it and the guard does not check it.
- The pass stamp covers the tree `git add -A` would commit; committing only some of the files means running the
  suite again.
- The pass stamp is a plain file under `.git/review-slices/`; writing to it by hand forges a pass. The bootstrap
  beside it and the hook's git config are per clone too; editing them takes the guard out of that clone.
- Planned actions are not visible to the guard; raising the level for them is the author's and the reviewers' job.
- The standing rules and the guard come from the base branch, so a branch's own edits to either apply once
  they are on the base branch. Paths that moved after the standing rules' commit fall back to their globs'
  defaults until then.
- A change to the suite is reported, not blocked. Reviewers check it is not weaker; a weaker package script, skip
  marker or test config is invisible to the guard.
- `git push --no-verify` skips the guard: the user's override only.
- The guard runs only in a clone where `setup_tools.py install` ran; a fresh clone or a cloud sandbox is
  unchecked until then.
- A config hook (used only where another tool owns `core.hooksPath`) runs for git 2.54+ only; an older git pushing
  from that clone runs nothing. `status` and `doctor` say when the hook is a config hook.
- The agent hook reads commands the way a shell splits them, and checks what it cannot read against a few plain
  patterns. A command built at run time (`eval`, a script file, an alias) gets past it; so does any agent tool it
  does not see, and Codex until its hooks feature is on.
