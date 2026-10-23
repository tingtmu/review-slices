# Reviewer briefs

Copy a brief into each reviewer's prompt and fill the angle brackets. A reviewer knows only what the brief gives
it, so give it paths to read, not your conclusions. Launch all reviewers of one round in a single message so
they run in parallel.

## Rules every brief carries

```
You are read-only: do not edit, stage, commit or push anything.
Never print secret-shaped strings (tokens, signatures, passwords, keys): report their file and line only.
<the repo's extra restrictions from REVIEW.md, for example files a live session must never open>
Each review finding: file:line, a tag (Blocker / Fix / Nit / Pre-existing), the evidence, and the exact change.
Any security problem is a Blocker. Raise at most three Nits. Under <N> words.
```

## Adversarial reviewer (Simple, Important, Critical)

```
Assume this change is wrong and show how it fails.

Change: `git diff <base>..<head>` in <repo path>; commits `git log --oneline <base>..<head>`.
Review level output: <paste the `level` output>. Check this level first: if a path or a planned action deserves
a higher level under REVIEW.md, that is a Blocker.
Read: REVIEW.md (the "Failure looks like" list is what this repo has got wrong before), <spec path>.
Shown output from the author: <paste the commands and summary lines>. Re-run the cheapest of them (one test, one
--help) and compare the exit code and summary line. If your sandbox blocks the re-run, say so, ask the author for
the transcript lines, and never mark the output confirmed.

Lenses, in order:
1. Correctness: inputs, edges and failure paths the change gets wrong; a reply that says ok for a non-success.
2. Security and secrets: injection, unsafe quoting through a shell, secrets reaching output or logs, guards
   bypassed.
3. Holes in the tests: tests that cannot fail, fakes kinder than the real service, data shapes assumed rather
   than observed from a real reply.
4. Instructions an agent would follow wrongly: placeholders it cannot fill, commands nobody ran.
<the rules every brief carries>
```

For two adversarial reviewers, split the lenses: one takes 1 and 3, the other 2 and 4.

## The code-review skill (Important, Critical)

`code-review` (mattpocock/skills) runs a Standards reviewer and a Spec reviewer in parallel. Invoke it with the
fixed point and the spec as arguments, so its issue-tracker step never runs:

```
fixed point: <base sha>; spec: <path to the OpenSpec change, the roadmap item, or the user's request saved to a file>
```

In the same message, start the adversarial reviewer above, so all three run at once. Hand the code-review
reviewers the rules every brief carries as well.

## Second round

Resume the same reviewers. Brief: "Confirm whether each of your findings is fixed, on the new diff
`git diff <old head>..<new head>` only. Report only new defects tagged Fix or Blocker. If none, say converged."
