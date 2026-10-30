# Set up a repo

Ask the user before each step; these change how the repo works. `<skill>` is this skill's directory.

1. **Find the suite.** `python3 <skill>/scripts/discover.py` lists the checks the repo already has (CI files,
   package.json, Makefile, justfile, pyproject, tox, nox, pre-commit, Cargo, go.mod, CONTRIBUTING), each marked
   local or remote with the reason, and a hint naming a security scanner when none of them runs one (add it as a
   `test:` line only if the user wants one); it runs nothing. With the user's go-ahead (it runs the repo's commands),
   `discover.py --run` on a clean tree runs each local check and prints the `test:` lines that passed, the checks
   already red (record each as an incident or a roadmap item and leave it out of the suite), the checks that
   write files (with `.gitignore` entries), and the remote checks for REVIEW.md.
2. Copy [templates/REVIEW.md](../templates/REVIEW.md) to the repo root and fill in its level table (one glob per
   line), its `test:` lines and remote checks from step 1, and its failure list. If a REVIEW.md is already there,
   keep its text and add the template's sections to it. Copy [templates/INCIDENTS.md](../templates/INCIDENTS.md) to
   `docs/INCIDENTS.md`. If the repo already has review rules (an existing REVIEW.md, CONTRIBUTING, a pull request
   template, CODEOWNERS, AGENTS.md or CLAUDE.md), list where they agree with the new rules and where they
   conflict, for the user to decide; link to them rather than copy them. CODEOWNERS paths are good candidates for
   important or critical globs.
3. **Calibrate the table** before committing it: `python3 <skill>/scripts/calibrate.py` shows how it would have
   judged the base branch's last 50 first-parent commits. Over 30% critical means people will route around it;
   over 60% trivial means most changes get no review. Tune the globs and run it again (`--rules PATH` tries a
   draft kept elsewhere). Its later sections say what a level costs and why. A glob that alone sets many high
   levels is the one to narrow first. A trailer declared above the table is a planned action, or a table too
   loose; one below it, a table stricter than the one that judged it. Small Important units that are mostly prose
   call for a narrower glob, not fewer reviewers. Its review load section shows the reviewers each unit would
   get. Tag a critical glob `critical code:` only where its files are code a reviewer can judge from a small diff;
   golden outputs, corpora, state tables and CI stay `critical:` (content, the default, which always takes three).
   `small: N lines, M files` and `medium: N lines, M files` (or `off`) set the size bands; built in: small 40 lines,
   3 files, no medium; at most 80/5 and 400/20. Where the base branch's guard is older than 0.9.0, push the upgraded
   guard first: an older guard cannot parse these lines, so pushes count every path as critical and `status`
   stops with a parse error. Run it again as reviewers' level notes build up.
4. Run `python3 <skill>/scripts/setup_tools.py install --agent-hooks`, show the user what it would change, and
   with their go-ahead run it again with `--apply`. It copies the guard, `merged_reviewer.py` and `run_suite.py` to
   `.githooks/` if missing, writes this clone's bootstrap, records the base branch, and wires pre-push with a hook file that
   runs any hook already there after the guard (pre-commit's through its `.legacy` hook). Where another tool owns
   `core.hooksPath` (Husky), it registers a git config hook instead, which only git 2.54+ runs. It never sets
   `core.hooksPath`, so git-lfs, Husky and pre-commit keep running. `--agent-hooks` adds the agent hook to `.claude/settings.json`
   and `.codex/hooks.json`, keeping what is there. Codex runs it on shell commands once its hooks feature is on and
   the user trusts the hook (a refused `git push --no-verify` checked live with Codex 0.164.0). If install reports
   a problem, tell the user.
5. Optional, with the user: add `secrets: gitleaks` to REVIEW.md's block to scan the commits every push adds,
   then run `setup_tools.py upgrade --apply`, which copies `secret_scan.py` beside the guard. Every clone that
   pushes, and CI, then needs gitleaks 8.19+ and git 2.36+. Where the base branch already has a guard older than
   0.7.0, push the upgraded guard first: an older guard cannot parse the line, so it counts every path as
   critical and scans nothing.
6. Run `python3 .githooks/review_slices.py check` until it reports no error, and `setup_tools.py doctor` until
   it reports ok. The scripts in `.githooks/` are vendored: they tell ruff, flake8, pylint, isort and mypy to skip
   them. If another check in the suite (a formatter such as black or prettier, or ruff with `preview = true`, which
   wants `# ruff: file-ignore`) still reads `.githooks/`, exclude it there in this same setup commit and say so to
   the user; it is not a weakened check.
7. Commit REVIEW.md, `docs/INCIDENTS.md`, `.githooks/` and the agent hook settings together; REVIEW.md puts them
   at Important or higher, so they are reviewed like any change. Every other clone that wants the guard runs
   `install --apply` once; teammates who do not are never blocked by it, and the agent hook does nothing for them.
8. Offer the user [templates/review-slices-ci.yml](../templates/review-slices-ci.yml) as
   `.github/workflows/review-slices.yml`: it runs `review_slices.py ci` on every pull request, so trailers are
   checked even from clones that never installed the hook.
9. Point the repo's agent instructions (AGENTS.md or CLAUDE.md) at REVIEW.md with a plain path, not an import.

When the skill is newer than the repo's guard, `setup_tools.py upgrade --apply` copies it in; commit it as a
reviewed change. What gets installed:

```
<repo>/REVIEW.md                       rules and level table               committed
<repo>/docs/INCIDENTS.md               incidents and their plugs           committed
<repo>/.githooks/review_slices.py      the guard; the base branch's copy   committed
                                       judges every push
<repo>/.githooks/agent_hook.py         blocks an agent's overrides         committed
<repo>/.githooks/merged_reviewer.py    the review load: which reviewers    committed
<repo>/.githooks/run_suite.py          run-suite: runs the suite, stamps   committed
<repo>/.githooks/secret_scan.py        the secret scan (with secrets:)     committed
<repo>/.claude/settings.json           runs the agent hook (Claude Code)   committed
<repo>/.codex/hooks.json               runs the agent hook (Codex)         committed
<repo>/.github/workflows/...           optional: `ci` on pull requests     committed
<git-common-dir>/review-slices/        per clone, never committed:
    bootstrap.py                       runs the base branch's guard on pre-push
    suite-pass                         pass stamps
    review-log                         the review load `status` printed, per review unit
<git-common-dir>/hooks/pre-push        per clone: runs the bootstrap, then any hook that was there
git config (per clone)                 review-slices.base; hook.review-slices.* only beside a foreign core.hooksPath
```
