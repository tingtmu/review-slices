# A secret turns up

When the secret scan (`status`, the pre-push hook, `ci`) or the staged scan of step 2 finds a secret:

1. Never write the value anywhere: not in your report, INCIDENTS.md, a commit message or a reviewer brief. Cite
   the rule, file, line and fingerprint the scan printed. Found by the staged scan, it is in no commit yet: move
   the value out (an environment variable or a secret manager), `git add` the files, and scan again.
2. Whether it is a real secret or a false positive is the user's call. For a false positive the user, never the
   agent, adds the full fingerprint (`<commit>:<file>:<rule>:<line>`) to `.gitleaksignore` and commits it, with
   the reason as a `#` comment on the line above (a trailing comment breaks the match). Only fingerprints that
   name a commit count, and a rewrite of that commit changes its fingerprint. `gitleaks:allow` markers count
   for nothing.
3. **Not pushed yet**: after `git fetch`, `git for-each-ref --contains <sha> refs/remotes` prints nothing. (A
   branch pushed without `-u` still counts among `status`'s new commits, so this check decides; if it prints a
   ref, go to step 4.) Move the value out, then rewrite the new commits so no commit holds it:
   - First stop and ask the user if the new commits include a merge, the working tree has edits that are not
     yours, or another branch, tag or stash holds the commit (`git for-each-ref --contains <sha> refs/heads
     refs/tags`, `git stash list`).
   - Otherwise `git reset --soft <parent of the oldest new commit>`, remove the value, `git add` the files, run
     step 2's staged scan, commit again, and redo steps 3 to 8: the old trailers went with the old commits.
   - Never `git reset --hard`, a backup branch, `push --all` or `--mirror`.
   - Tell the user. If the value is real, rotating it is the user's call: you and any reviewer have seen it.
4. **Already pushed:** tell the user first. Rotating or revoking the value is the fix, and the user's action.
   Remove the value with an ordinary commit; once the user has dealt with it, they add its fingerprint to
   `.gitleaksignore` so later pushes and the pull request pass. Rewriting published history needs a force-push,
   a one-way door: only with the user's go-ahead, and it does not unpublish (forks, pull request refs, caches,
   CI logs). Record an incident.
5. A secret already in the base branch's history that this change did not add is Pre-existing (step 5).
