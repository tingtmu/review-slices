# Known holes in the guard

The guard is a hard stop for honest mistakes, not a lock against an agent set on getting past it. These holes
are known; reviewers and the user cover them.

- A review trailer proves a level was declared, not that a review ran. The agent writes its own trailer.
- Whether one merged reviewer or three ran is invisible too: `status` only says when one may. Its review log
  (`.git/review-slices/review-log`) holds a unit at the highest load printed, but it is a per-clone file: deleting
  it, another clone or worktree branch copied from this one, or a rebase that moves the unit's start drops the
  hold. A branch deleted and made again under the same name from the same base commit reads as rewritten: three.
  Its measure counts lines and files, not what they do: a one-line change to something every adopter depends on
  fits, so the author raises the level for planned actions and the reviewer's Blocker rule backs that up. A file
  moved unchanged counts as one file and no lines, so content moved from a lower-level path into a `critical code:`
  glob can take the adversarial and conformance pair on a diff that shows none of it; reviewers read the moved file
  whole.
- The measure starts over after a unit large on its own that the review log shows went to three reviewers, so the
  slices before and after it are never measured together: about one band of lightly reviewed work per stretch. Any
  unit over the line limit buys that restart, filler or not: a deleted file, a file moved with a one-character edit
  (it counts in full) or one very long line reads as little as a pure move; reviewers see them. The restart needs this
  branch's log line, so another clone, a deleted log or a rebase measures the branch whole again (three); a forged
  log line restarts only a unit that is large on its own anyway.
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
- The hooks run Python isolated and without site (`-I -S`), so a module written beside them or a `.pth` file in a
  virtualenv never runs. They still find `python3` and `git` on PATH: a shim written into a directory already on
  it gets past them, as a fake `gitleaks` does the scan. So does a push whose command line sets `PATH` or git's
  own variables (`GIT_CONFIG_*`, `GIT_DIR`, `HOME`), which choose the git, config and hooks it runs: the agent hook
  reads `-c` settings, not the environment. Commands the agent runs itself (`python3 .githooks/review_slices.py status` or
  `run-suite`) put `.githooks/` first on the import path: a stdlib-named file there, untracked, could fake a pass
  stamp. `run-suite`'s stamp is the agent's word, as above.
