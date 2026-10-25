# Known holes in the guard

The guard is a hard stop for honest mistakes, not a lock against an agent set on getting past it. These holes
are known; reviewers and the user cover them.

- A review trailer proves a level was declared, not that a review ran. The agent writes its own trailer.
- Whether one merged reviewer or three ran is invisible too: `status` only says when one may. Its measure counts
  lines and files, not what they do: a one-line change to something every adopter depends on fits, so the author
  raises the level for planned actions and the reviewer's Blocker rule backs that up.
- The trailer's base SHA is informational; rebases change it and the guard does not check it.
- The pass stamp covers the tree `git add -A` would commit; committing only some of the files means running the
  suite again.
- A pass stamp carries over to a tree that differs from a stamped one only in trivial paths, since trivial
  means no check reads them. A trivial glob that covers a file some check does read is a hole.
- The pass stamp is a plain file under `.git/review-slices/`; writing to it by hand forges a pass. The bootstrap
  beside it and the hook's git config are per clone too; editing them takes the guard out of that clone.
- Planned actions are not visible to the guard; raising the level for them is the author's and the reviewers' job.
- The standing rules, the guard and `.githooks/merged_reviewer.py` come from the base branch, so a branch's own
  edits to them apply once they are on the base branch. Paths that moved after the standing rules' commit fall back to their globs'
  defaults until then.
- A change to the suite is reported, not blocked. Reviewers check it is not weaker; a weaker package script, skip
  marker or test config is invisible to the guard.
- `git push --no-verify` skips the guard: the user's override only.
- The guard runs only in a clone where `setup_tools.py install` ran; a fresh clone or a cloud sandbox is
  unchecked until then.
- A config hook (used only where another tool owns `core.hooksPath`) runs for git 2.54+ only; an older git pushing
  from that clone runs nothing. `status` and `doctor` say when the hook is a config hook.
- The secret scan (`secrets: gitleaks`) sees only what gitleaks's rules match: a custom secret format, or one
  encoded or inside binary content, passes. gitleaks's default config also skips some paths (lockfiles,
  `node_modules/` and the like); a base branch that wants them scanned commits a full `.gitleaks.toml` that does
  not extend the default. The pushed commit's own `.gitleaksignore` can allow its findings;
  the floor puts it at important, so it is reviewed, but the author writes the trailer. A fake `gitleaks` earlier
  on PATH defeats the scan. The guard refuses a scan that read no commits, but cannot tell a partial one. The
  staged scan before a commit is a procedure step, not a hook. A clone without the hook pushes unscanned; the
  host's push protection, where it is on, is the only stop on the server.
- The agent hook reads commands the way a shell splits them, sees through common wrappers (`env`, `timeout`,
  `xargs`, `sudo`) and aliases set on the command line, and checks what it cannot read against a few plain
  patterns. A command built at run time (`eval`, a script file, an alias already in git config) gets past it; so
  does any agent tool it does not see, Codex until its hooks feature is on and the user trusts the hook, and
  Codex's `apply_patch` edits, since its hook sees shell commands only. It runs the copy committed on the
  base branch, so editing the checkout's copy changes nothing.
