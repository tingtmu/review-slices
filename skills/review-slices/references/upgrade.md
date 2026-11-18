# Upgrade

How to move the installed skill, and a repo set up with it, to a newer release. Ask the user before each step that
changes the repo; `<skill>` is this skill's directory.

## Which version is where

- The skill: `python3 <skill>/scripts/review_slices.py --version`.
- The repo's checkout: `python3 .githooks/review_slices.py --version`.
- The copy that judges pushes, the base branch's: `status`'s `guard:` line. It says `this copy` where the
  checkout's copy is the same, or the base branch has none (or one too old to run `status`).

`setup_tools.py doctor` adds a `note:` when the repo's guard is older than the skill.

## Steps

1. **Update the skill** the way it was installed: `npx skills update review-slices -g -y` for a global
   `npx skills` install. Check its `--version` above.
2. **Refresh the repo's copies.** From the repo, on a branch (one that is not the base branch), first note the repo's
   version, `python3 .githooks/review_slices.py --version`: step 3 starts from it, and `--apply` replaces that file.
   `python3 <skill>/scripts/setup_tools.py upgrade` lists each copy in `.githooks/` it would replace; with the user's
   go-ahead run it again with `--apply`. It refreshes `review_slices.py` (with no guard there, run `install` first:
   [Set up a repo](set-up.md)); refreshes or adds `merged_reviewer.py` and `run_suite.py`; adds `secret_scan.py`
   where REVIEW.md has `secrets:`; and refreshes `secret_scan.py`, `agent_hook.py` and `incidents.py` only where the
   repo already has them (copy `incidents.py` yourself to add it). It refuses a repo whose guard is newer than the
   skill: update the skill instead.
3. **Read the release notes**, which the installed skill does not carry: `CHANGELOG.md` at
   https://github.com/tingtmu/review-slices (the same notes as its GitHub Releases). Read every entry newer than the
   version you noted in step 2. Carry into REVIEW.md, `docs/INCIDENTS.md` and `docs/NEAR-MISSES.md` only what those
   entries name; diff each against `<skill>/templates/` to see the shape. Never overwrite the repo's own rules,
   globs, `test:` lines or incidents, and never copy a template over them. Where REVIEW.md names the skill's version,
   update it. A line in REVIEW.md's `review-slices` block with a key or level the base branch's guard does not know
   waits until the upgraded guard is on the base branch: the older guard cannot parse it. Add it in a later change.
4. **Commit and review it as one unit:** the `.githooks/` copies and any doc edits from step 3 together. REVIEW.md
   puts `.githooks/` at Important or higher; run `status` and follow SKILL.md (review at the load it prints, the
   trailer, `run-suite`, the user's go-ahead, push or pull request). The base branch's old guard judges this push;
   the new one judges pushes once it is on the base branch.
5. **Check the clone:** `python3 <skill>/scripts/setup_tools.py doctor` must end `doctor: ok`. Most `problem:` lines
   name their fix (`install --apply` for a stale bootstrap, `install --agent-hooks --apply` for an older agent hook
   command, which changes committed settings and goes through step 4). Every other clone that runs the guard
   re-runs `install --apply` only when a release's `Upgrading:` line says so, or its own `doctor` asks for it.

## The `Upgrading:` line

A CHANGELOG entry carries an `Upgrading:` line only when its release needs a step beyond the five above (a
REVIEW.md change, a re-run of `install`, a new tool to have on PATH). An entry without one needs only these steps.
Do every `Upgrading:` step newer than the version you noted, oldest first.
