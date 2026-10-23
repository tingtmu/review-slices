# Incidents

Defects and rule breaks in agents' work that were found after the work was declared done, and the plugs that stop
each failure class from getting through again. Terms: the skill's
[GLOSSARY.md](../skills/review-slices/GLOSSARY.md). Rules: [REVIEW.md](../REVIEW.md).

- One entry per failure class. A later case of the same class goes under that entry's Recurrences, and says why
  the plug did not stop it.
- Status is `open` until the plug exists, then `plugged`. A fix repairs one instance; only a plug closes an entry.
- A plug is, in order of preference: `test <path>::<test function>`, `guard <path>`, `rule REVIEW.md "<line>"`.

## I1. The guard trusts input the change controls

- **Date / kind / status:** 2026-10-23 · defect · open
- **What happened:** In 0.1.0, a commit could swap the base's failing suite for `test: true`, stamp and push
  (H1), and an edited guard copy judged its own push (H10).
- **Slice that should have caught it:** 2 Review. Why it did not: 0.1.0 was released without a review or tests
  of the guard.
- **Failure class:** the guard trusts input the change itself controls
- **Fix:** not yet
- **Plug:** test tests/test_level.py::test_a_changed_test_command_is_reported,
  test tests/test_pre_push.py::test_an_edited_guard_does_not_judge_its_own_push (expected failures until fixed)
- **Recurrences:** none

## I2. The guard fails open on unexpected input

- **Date / kind / status:** 2026-10-23 · defect · open
- **What happened:** In 0.1.0, comma-separated globs matched nothing (H3), a `#` cut a test command (H4), tag
  pushes went unchecked (H6), a hook chained before the guard could drain its input (H5), a deleted REVIEW.md switched the guard off (H7), `diff.relative` hid paths (H9),
  a duplicate `test:` line won silently (H13) and an ignored submodule update was invisible (H14).
- **Slice that should have caught it:** 1 Offline suite. Why it did not: the guard had no tests.
- **Failure class:** the guard fails open on input it did not expect
- **Fix:** not yet
- **Plug:** tests in tests/test_rules.py, tests/test_level.py, tests/test_pre_push.py and
  tests/test_run_suite.py marked H3, H4, H6, H7, H9, H13 and H14 (expected failures until fixed)
- **Recurrences:** none

## I3. A push is measured across other people's commits

- **Date / kind / status:** 2026-10-23 · defect · open
- **What happened:** In 0.1.0, merging an untrailered main commit into a pushed branch demanded a review of main's
  change (H2), and `level` measured from the upstream while the hook measured from the last trailer (H11).
- **Slice that should have caught it:** 1 Offline suite. Why it did not: the guard had no tests.
- **Failure class:** a push is measured across commits that are not the author's
- **Fix:** not yet
- **Plug:** test tests/test_pre_push.py::test_merging_main_into_a_branch_does_not_ask_to_review_main,
  test tests/test_level.py::test_level_measures_from_the_last_local_trailer (expected failures until fixed)
- **Recurrences:** none

## I4. Setup breaks the host repo's hooks

- **Date / kind / status:** 2026-10-23 · defect · open
- **What happened:** 0.1.0's setup set `core.hooksPath .githooks`, which silently disables every hook in
  `.git/hooks`, including git-lfs's pre-push upload (H16).
- **Slice that should have caught it:** 2 Review. Why it did not: no reviewer checked setup against repos with
  existing hooks.
- **Failure class:** setup breaks the host repo's existing hooks
- **Fix:** 0.1.1 setup refuses to set `core.hooksPath` when other hooks exist (SKILL.md, Set up a repo)
- **Plug:** none yet (a test arrives with the installer)
- **Recurrences:** none
