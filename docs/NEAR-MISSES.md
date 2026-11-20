# Near misses

Blocker and Fix review findings that review caught and the author accepted and fixed, whose reviewer tagged them
with an `F<n>` "Failure looks like" entry or `none`. A finding tagged with an incident's id is a Recurrence in
docs/INCIDENTS.md instead. A near miss is never an incident. Terms: the review-slices skill's GLOSSARY.md; how to
promote one: its references/incidents.md. No check reads this file, so REVIEW.md lists it `trivial:`.

- One line per failure class: its `F<n>` id once it has one, the class as a trap, then one sighting per review
  unit: the date, the short hash of the head review read, and Blocker or Fix.
- A rejected review finding of a logged class: `rejected <date> <unit>` on its line, read at pruning.
- Once a test or check pins the class: `plugged: <plug>` at the end of its line.
- A line with one sighting older than 90 days: delete it in your next commit (`incidents.py` names it).

```
- F2 <the class, as a trap> — 2026-11-09 abc1234 Blocker, 2026-11-12 def5678 Fix; rejected 2026-11-13 9abc012; plugged: <plug>
```

Lines go below. The first ones were seeded on 2026-11-09 from notes kept before this file existed; their
reviewers gave no tag, so they count as `none`.

- F1 A release note or CHANGELOG line claims what the diff or a cited source does not show — 2026-10-30 bcaed43 Fix, 2026-11-08 6504a70 Fix, 2026-11-18 419aeb8 Fix, 2026-11-20 581f6a4 Fix
- A test passes without exercising the claim it names (a branch the fixture never reaches) — 2026-11-06 b657054 Fix, 2026-11-18 d23085d Fix
- A notice tells the agent to delete a record a later step reads (the 90-day note on plugged and promoted near-miss lines) — 2026-11-09 01461a9 Fix; plugged: test tests/test_incidents.py::NoticeTest::test_a_stale_one_sighting_near_miss_is_a_notice
- Wording written during a build sets agent behaviour or an exit rule the plan never decided — 2026-11-09 01461a9 Fix
- A plan step on an untracked file (ROADMAP.md) is skipped because no diff shows it — 2026-11-09 01461a9 Fix
- A brief tells the author to run, unsandboxed, a command a sandboxed reviewer names — 2026-11-18 613f25b Blocker
- A command run after `cd` reads a relative input path inside the worktree under review — 2026-11-18 d23085d Fix
- A fallback reviewer is started fresh without the findings it is asked to confirm — 2026-11-18 7dbb28c Fix
- A new branch keys on a value a fallback also produces (open_unit's HEAD fallback read as "HEAD carries a trailer") — 2026-11-18 28d5848 Fix
- An incident's plug pins only the instance that slipped while its `(suite)` line claims the whole class — 2026-11-18 28d5848 Fix
- Two reads of the working tree in one command can disagree, so its lines contradict each other — 2026-11-18 28d5848 Fix
- A plan restates the brief's condition more narrowly and drops a case (a pushed HEAD that carries its trailer) — 2026-11-18 ba44a1c Fix
- A step reads a version after an earlier step or run replaced the copy it reads — 2026-11-18 fee27b0 Fix
- A doc states a rule broader than the code enforces (every new block line waits; every doctor problem names a fix) — 2026-11-18 419aeb8 Fix
- A doc's command fails on an old version it still covers (a 0.1.0 guard has no `--version`) — 2026-11-18 419aeb8 Fix
- A doc's range is left open where the code bounds it (release notes past the installed skill's version) — 2026-11-18 419aeb8 Fix
- A command written into docs is not shown run (Slice 0) — 2026-11-18 419aeb8 Fix
- A config's comment claims more coverage than its check gives (ruff silently skipped the noqa-headed guard scripts) — 2026-11-19 2d438d7 Fix
- A rule turned off to pass a check, with a reason the code does not bear out (PLW1510; `git_version` read only stdout) — 2026-11-19 2d438d7 Fix
- A new file that configures a suite check takes the default level, so a later edit can empty the check under a lighter review — 2026-11-19 2d438d7 Fix
- A plan line dropped while trimming SKILL.md to its size ceiling (never skip the pre-commit hooks) — 2026-11-19 2d438d7 Fix
- A hook's file filter misses the files that configure it (a config-only change skipped the lint hook; then `pyproject.toml`, `.ruff.toml`, nested configs) — 2026-11-19 cb214d6 Fix, 2026-11-19 6a4b8aa Fix; plugged: test tests/test_dogfood.py::HookTriggerTest::test_the_ruff_hook_runs_on_every_file_that_configures_it
- A doc's principle and its own example disagree (turn off only None reports, yet the example also turned off argument types and lost a real bug) — 2026-11-19 d85db6b Fix
- A new doc uses a GLOSSARY Avoid word for a defined term ("gate" for the suite) — 2026-11-19 d85db6b Fix
- A doc pools several sources into one claim none of them makes alone — 2026-11-19 6a4b8aa Fix
- A doc claims the hook and the suite see the same tree where they differ (unstaged edits set aside) — 2026-11-19 6a4b8aa Fix
- A hand-written config reader takes a shape the real parser reads otherwise (a quoted or spaced key, a tab-led comment, `repo:` after `rev:`), so the check it feeds passes — 2026-11-20 0b1fb62 Fix
- A doc keeps recommending the config its own change shows too narrow (tool notes' hook filter) — 2026-11-20 0b1fb62 Fix
- A guide's command names the base branch other than the guard's own lookup (`review-slices.base`, unset before 0.3.0, then origin's default) — 2026-11-20 8767bfc Fix, 2026-11-20 1d8d5fc Fix
- A guide's recovery step undoes edits but not the untracked files the interrupted command added (`git restore` after `upgrade --apply`) — 2026-11-20 8767bfc Fix
- Two docs state one behaviour and only one keeps its fallback (set-up.md vs upgrade.md on the handoff of `status`) — 2026-11-20 8767bfc Fix
- A guide's expected output assumes the checkout has the merge (`guard: <new>, this copy` on a stale local base) — 2026-11-20 1d8d5fc Fix
