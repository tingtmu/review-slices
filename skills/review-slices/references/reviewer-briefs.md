# Reviewer briefs

Copy a brief into each reviewer's prompt and fill the angle brackets. A reviewer knows only what the brief gives
it, so give it paths to read, not your conclusions. Launch all reviewers of one round in a single message so
they run in parallel. `<base>` is the commit in the trailer line `level` prints; the change is committed, so
`git diff <base>..HEAD` shows all of it.

## Rules every brief carries

```
You are read-only: do not edit, stage, commit or push anything.
Never print secret-shaped strings (tokens, signatures, passwords, keys): report their file and line only.
<the repo's extra restrictions from REVIEW.md, for example files a live session must never open>
Each review finding: file:line, a tag (Blocker / Fix / Nit / Pre-existing), the evidence, and the exact change.
Any security problem is a Blocker. Raise at most three Nits. Under <N> words (600 is a good default).
```

## Adversarial reviewer (Simple, Important, Critical)

```
Assume this change is wrong and show how it fails.

Change: `git diff <base>..HEAD` in <repo path>; commits `git log --oneline <base>..HEAD`.
Review level output: <paste the `level` output>. Check this level first: if a path or a planned action deserves
a higher level under REVIEW.md, that is a Blocker.
Read: REVIEW.md (the "Failure looks like" list is what this repo has got wrong before), <spec path>.
Shown output from the author: <paste the commands and summary lines>. Re-run the cheapest of them (one test, one
--help) and compare the exit code and summary line. If your sandbox blocks the re-run, say so, ask the author for
the transcript lines, and never mark the output confirmed.

Lenses, in order:
1. Correctness: inputs, edges and failure paths the change gets wrong; a reply that says ok for a non-success.
2. Security and secrets: injection, unsafe quoting through a shell, secrets reaching output or logs, checks
   the change skips or switches off; a secret in the diff; every new `.gitleaksignore` entry or `.gitleaks.toml`
   change, which silences the secret scan.
3. Holes in the tests: tests that cannot fail, fakes kinder than the real service, data shapes assumed rather
   than observed from a real reply.
4. Instructions an agent would follow wrongly: placeholders it cannot fill, commands nobody ran.
5. Checks weakened elsewhere: the suite's test lines, skip markers, test config (addopts, coverage thresholds),
   package scripts, CI files.
<the rules every brief carries>
```

For two adversarial reviewers, split the lenses: one takes 1, 3 and 5, the other 2 and 4.

## Standards reviewer (Important, Critical)

```
Check this change against the standards this repo has written down.

Change: `git diff <base>..HEAD` in <repo path>; commits `git log --oneline <base>..HEAD`.
Read: the repo's agent instructions (AGENTS.md, CLAUDE.md), CONTRIBUTING, lint and format configs, REVIEW.md,
and the code around each changed hunk.
Report where the change breaks a written standard or the conventions of the code around it: naming, structure,
error handling, tests beside the code they test, docs updated with behaviour. Quote the standard (file:line) for
each review finding; a preference with no written source is a Nit.
<the rules every brief carries>
```

## Spec reviewer (Important, Critical)

```
Check that this change does what was asked: all of it, and nothing else.

Change: `git diff <base>..HEAD` in <repo path>; commits `git log --oneline <base>..HEAD`.
Spec: <path to the spec: the issue, the plan or roadmap item, or the user's request saved to a file>.
Read the spec first, then the change.
Report each requirement the change misses or gets wrong (Fix or Blocker), anything it adds that the spec did not
ask for (Fix if it changes behaviour, else Nit), and each requirement nobody can check from the change (say what
shown output would prove it).
<the rules every brief carries>
```

The `code-review` skill (mattpocock/skills) can stand in for the Standards and Spec reviewers if it is installed.
Invoke it with the fixed point and the spec as arguments, so its issue-tracker step never runs
(`fixed point: <base sha>; spec: <path>`), hand its reviewers the rules every brief carries, and start the
adversarial reviewer in the same message.

## Second round

Resume the same reviewers. Brief: "Confirm whether each of your review findings is fixed, on the new commits
`git diff <old head>..HEAD` only. Report only new defects tagged Fix or Blocker. If none, say converged."
