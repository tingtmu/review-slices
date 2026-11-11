# Known holes in the guard

The guard is a hard stop for honest mistakes, not a lock against an agent set on getting past it. These holes
are known; reviewers and the user cover them.

- A review trailer proves a level was declared, not that a review ran. The agent writes its own trailer.
- Which load ran (one merged reviewer, the pair, or three) is invisible too: `status` only says when one may, and an agent that
  runs fewer reviewers than it printed is caught only by the user (issue #26). Its review log
  (`.git/review-slices/review-log`) holds a unit at the highest load printed, but it is a per-clone file: deleting
  it, another clone or worktree branch copied from this one, or a rebase that moves the unit's start drops the
  hold. A branch deleted and made again under the same name from the same base commit reads as rewritten: the pair, with an `escalate:` line.
  Its measure counts lines and files, not what they do: a one-line change to something every adopter depends on
  fits, so the author raises the level for planned actions and the reviewer's Blocker rule backs that up. A file
  moved unchanged counts as one file and no lines, so content moved from a lower-level path into a `critical code:`
  glob can take the adversarial and conformance pair on a diff that shows none of it; reviewers read the moved file
  whole. Copy credit (`copy-credit:`) matches text, not context: in a commit that moves a file under its globs, a
  common line, text copied into a new place, or a live requirement deleted while an archive still holds its text
  counts no lines, and a file under its globs counts lines, never a file, so new text spread over many files
  there is held by the line limit alone (owner, 2026-11-06). It lowers the band only (one merged reviewer instead of the pair, never no review), and the
  globs the base branch names bound it.
- The measure starts over after a unit large on its own that the review log shows got the ceiling load (the pair;
  three reviewers before 0.13.0), so the slices before and after it are never measured together: about one band of
  lightly reviewed work per stretch. Any unit over the line limit buys that restart, filler or not: a deleted file, a
  file moved with a one-character edit (it counts in full) or one very long line reads as little as a pure move;
  reviewers see them. A pair logged at a medium head also restarts once the line limit is tightened under it. The
  restart needs this branch's log line, so another clone, a deleted log or a rebase measures the branch whole again (the pair); a forged
  log line restarts only a unit that is large on its own anyway.
- The pair is the most `status` prints (0.13.0), on large and Critical changes too; one reviewer fewer than before
  was never benched there, and the owner accepted that risk. A miss through it on a large or Critical unit goes to
  the user before the next one (`incidents.py` counts them); two units' untested misses through it ask for
  `cross-check: on`, never three reviewers. The guard prints the cross-check but cannot see whether it ran or which
  runner (another model family, or the same one), as it cannot see how many reviewers ran; the report names it.
- A CLI reviewer (the cross-check, a fallback, a refuter) runs the change's code, tests included, in its own
  worktree with writes held there: the same reach a pair subagent has in the checkout. Restoring the instruction
  and config files to `<standing>` keeps the change from steering it; a path outside the list in
  reviewer-briefs.md (a tool's own rules file) is not restored, and the brief's rules are the only guard there.
  The repo's `.git` stays read-only to it (Codex's sandbox; Claude's `denyWrite` on the git common dir), tested
  with `git -C` commits from a main checkout and from a linked worktree.
- The `escalate:` line compares the unit's weight with what this clone's review log holds for it, so another clone,
  a deleted log or a rebase onto a moved base branch shows no rise; step 6 then asks for a fresh pair by hand. Whether
  a round already reviewed the head it names is the agent's `git merge-base` check, not the guard's.
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
  Codex's `apply_patch` edits, since its hook sees shell commands only. It follows a `cd`, `pushd` or `git -C` to
  judge an amend or a write where it runs, and judges both places where the `cd` may be skipped or fail; one it
  cannot work out (a variable, `-`, a command's output) refuses an amend that could add content, but a write after
  it is judged only by the names of the guarded layout (`review-slices` in a git dir, `hooks/pre-push`, a bare
  stamp, bootstrap or hook name), so `rm -rf hooks` or `rm -rf .` there passes. It
  does not follow `env -C`, `sudo -D`, `CDPATH` or a `cd` inside a shell function. It runs the copy committed on the
  base branch, so editing the checkout's copy changes nothing.
- The hooks run Python isolated and without site (`-I -S`), so a module written beside them or a `.pth` file in a
  virtualenv never runs. They still find `python3` and `git` on PATH: a shim written into a directory already on
  it gets past them, as a fake `gitleaks` does the scan. So does a push whose command line sets `PATH` or git's
  own variables (`GIT_CONFIG_*`, `GIT_DIR`, `HOME`), which choose the git, config and hooks it runs: the agent hook
  reads `-c` settings, not the environment. Commands the agent runs itself (`python3 .githooks/review_slices.py status` or
  `run-suite`) put `.githooks/` first on the import path: a stdlib-named file there, untracked, could fake a pass
  stamp. `run-suite`'s stamp is the agent's word, as above.
- `incidents.py` checks that a plug exists and is shaped right, not that it tests the class. A `test` plug may
  name a `.py` function that is not a test, or a test in a file no `test:` line collects (seqslab's suite runs
  only `cd engine && uv run pytest`), and a `check` plug may name a `test:` line that runs the whole suite
  once that line is tagged `# I<n>` (only `.md`, `.txt` and `.rst` test paths are refused). Any of these counts as
  a working plug for the recurrence rule and the `(suite)` marker. The plug sits in a reviewed change to the
  incident log or REVIEW.md, and reviewers read it there (owner, 2026-11-09).
- Reviewers cannot see the chat. A user decision the author cites counts only where it quotes the user's own words
  on that item, and a rejection resting on one goes to the user (I7); consent claimed only in chat, or a quote
  taken out of its context or made up, is caught by the user alone.
