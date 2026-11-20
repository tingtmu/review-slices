# Upgrade

How to move the installed skill, and a repo set up with it, to a newer release. Ask the user before each step that
changes the repo; `<skill>` is this skill's directory (for a global `npx skills` install,
`~/.agents/skills/review-slices`, which `~/.claude/skills/review-slices` may link to).

## Which version is where

- The skill: `python3 <skill>/scripts/review_slices.py --version`.
- The repo's checkout: `python3 .githooks/review_slices.py --version` (a 0.1.0 guard has no `--version`: it is
  0.1.0).
- The copy that judges pushes, the base branch's: `status`'s `guard:` line. It says `this copy` where the
  checkout's copy is the same, or the base branch has none (or one too old to run `status`). Where `status`
  cannot say (a checkout or a base branch guard too old to run it), read the base branch's copy directly:
  `git show <base>:.githooks/review_slices.py | grep -m1 -o 'skill version [0-9.]*'`, where `<base>` is what `git
  config --get review-slices.base` prints, or where that prints nothing (before 0.3.0), the base branch's
  remote-tracking name, such as `origin/main`.

`setup_tools.py doctor` adds a `note:` when the repo's guard is older than the skill.

## Steps

1. **Update the skill** the way it was installed: `npx skills update review-slices -g -y` for a global `npx skills`
   install. Check its `--version` above.
2. **Refresh the repo's copies.** From the repo, on a branch (one that is not the base branch) with a clean working
   tree, first note the repo's version, the lower of `python3 .githooks/review_slices.py --version` and `status`'s
   `guard:` line (a branch may already carry a newer copy): step 3 starts from it, and `--apply` replaces the
   checkout's copy. `python3 <skill>/scripts/setup_tools.py upgrade` lists each copy in `.githooks/` it would replace;
   with the user's go-ahead run it again with `--apply`, then once more without: it must say `the repo's copies are
   this skill's`. A 0.1.0 repo also deletes `.githooks/pre-push` in this unit, once every clone has run `install` (the
   dry run and `--apply` say so; the check run does not). It refreshes `review_slices.py` (with no guard there, run
   `install` first: [Set up a repo](set-up.md)); refreshes or adds `merged_reviewer.py` and `run_suite.py`; adds
   `secret_scan.py` where REVIEW.md has `secrets:`; and refreshes `secret_scan.py`, `agent_hook.py` and `incidents.py`
   only where the repo already has them (copy `incidents.py` yourself to add it). It refuses a repo whose guard is
   newer than the skill: update the skill instead. If `--apply` stops partway, run it again before anything else: it
   rewrites only the copies that still differ, a cut-short one included, and if it cannot finish, `git restore
   .githooks/` puts back the committed copies (delete any copy it added that `git status` still shows untracked). The
   version you noted still holds, whatever the checkout's `--version` now says.
3. **Read the release notes**, which the installed skill does not carry: `CHANGELOG.md` at
   https://github.com/tingtmu/review-slices (from 0.9.2 on, the same notes as its GitHub Releases; offline, `git show
   origin/main:CHANGELOG.md` in a clone of it). Read every entry newer than the version you noted in step 2, up to the
   skill's own version. Carry into REVIEW.md, `docs/INCIDENTS.md` and `docs/NEAR-MISSES.md` only what those entries
   name; diff each against `<skill>/templates/` to see the shape. Never overwrite the repo's own rules, globs, `test:`
   lines or incidents, and never copy a template over them. Where REVIEW.md points to the installed skill's version (a
   version marker, a source or tag link), update it; a line citing what an older version did keeps its version. Leave
   any line a plug in `docs/INCIDENTS.md` quotes as it is, and where the repo has `.githooks/incidents.py`, run
   `python3 .githooks/incidents.py --check` right after editing REVIEW.md: it must end `incidents: ok`. A line in
   REVIEW.md's `review-slices` block with a key or level the base branch's guard does not know waits until the
   upgraded guard is on the base branch: the older guard cannot parse it. Add it in a later change.
4. **Check the clone** before committing, so a fix it asks for joins the unit: `python3
   <skill>/scripts/setup_tools.py doctor` must end `doctor: ok`. Most `problem:` lines name their fix (`install
   --apply` for a stale bootstrap, `install --agent-hooks --apply` for an older agent hook command, which changes
   committed settings). Every other clone that runs the guard re-runs `install --apply` only when a release's
   `Upgrading:` line says so, or its own `doctor` asks for it.
5. **Commit and review it as one unit:** the `.githooks/` copies and any edits from steps 3 and 4 together. REVIEW.md
   puts `.githooks/` at Important or higher; run `status` and follow SKILL.md (review at the load it prints, the
   trailer, `run-suite`, the user's go-ahead, push or pull request). `.githooks/` is a floor path, so the unit
   measures large: review at the load the base branch's guard prints (from 0.13.0 the pair, plus a cross-check where
   its REVIEW.md has `cross-check: on`; 0.9.0 to 0.12.x `three reviewers`); with no `review:` line, SKILL.md step 4
   gives the load. A review finding in a copied file is settled like any other (SKILL.md step 5); also report it as an
   issue at the skill's repo, which is also where a Pre-existing one is recorded. A Blocker still blocks the trailer
   as step 5 says; for any other, whether to push the copies or wait for a fixed release is the user's call. The base
   branch's old guard judges this push, and until the merge it also runs `status`, `level` and `ci` (where it has the
   command; else this copy runs and says so): on the branch, expect the old version's output and `guard: <old>, the
   base branch's copy`, and never change a trailer to match it. After the merge, fetch the base branch and re-run
   `status`: it must say `guard: <new>` (`this copy` once your checkout has the merge). To back out, revert that
   commit, after first reverting any later change that needs the newer guard (such as a new block key); `install
   --apply` from the older skill rewires a clone if `doctor` asks. After the revert lands, fetch the base branch and
   check its guard version again (`guard:`, or the direct read above).

## The `Upgrading:` line

A CHANGELOG entry carries an `Upgrading:` line only when its release needs a step beyond the five above (a
REVIEW.md change, a re-run of `install`, a new tool to have on PATH). An entry without one needs only these steps.
Do every `Upgrading:` step in the entries step 3 reads, oldest first.
