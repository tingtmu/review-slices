# Incidents

Defects and rule breaks in agents' work that were found after the work was declared done, and the plugs that stop
each failure class from getting through again. Terms: the skill's
[GLOSSARY.md](../skills/review-slices/GLOSSARY.md). Rules: [REVIEW.md](../REVIEW.md).

- One entry per failure class. A later case of the same class goes under that entry's Recurrences, and says why
  the plug did not stop it.
- Status is `open` until the plug exists, then `plugged`. A fix repairs one instance; only a plug closes an entry.
- A plug is, in order of preference: `test <path>::<test function>`, `guard <path>`, `rule REVIEW.md "<line>"`.

## I1. The guard trusts input the change controls

- **Date / kind / status:** 2026-10-23 · defect · plugged
- **What happened:** In 0.1.0, a commit could swap the base's failing `test:` line for `test: true`, stamp and
  push without a word (H1), and an edited guard copy judged its own push (H10).
- **Slice that should have caught it:** 2 Review. Why it did not: 0.1.0 was released without a review or tests
  of the guard.
- **Failure class:** the guard trusts input the change itself controls
- **Fix:** 0.2.0 reports a changed suite and puts REVIEW.md at important or higher; 0.3.0 runs the guard committed
  on the base branch through a per-clone bootstrap; 0.4.0 does the same for `ci`.
- **Plug:** test tests/test_level.py::test_a_changed_test_command_is_reported,
  test tests/test_pre_push.py::test_an_edited_guard_does_not_judge_its_own_push,
  test tests/test_ci.py::test_ci_runs_the_guard_committed_at_base,
  test tests/test_agent_hook.py::test_the_settings_command_runs_the_base_branch_copy_not_an_edited_one,
  test tests/test_install.py::BootstrapTest::test_an_edited_checkout_guard_does_not_judge_after_the_base_lost_its_own,
  test tests/test_install.py::BootstrapTest::test_a_base_branch_tracking_an_upstream_without_rules_keeps_origin,
  test tests/test_install.py::BootstrapTest::test_a_base_branch_tracking_another_remote_without_rules_keeps_origin,
  test tests/test_install.py::BootstrapTest::test_an_upstream_that_only_mentions_a_rules_block_has_no_rules,
  test tests/test_agent_hook.py::SettingsTest::test_a_module_planted_where_the_hook_runs_never_stands_in_for_the_standard_library,
  test tests/test_install.py::UpgradeAndDoctorTest::test_a_module_planted_beside_the_bootstrap_never_stands_in_for_the_standard_library,
  test tests/test_install.py::UpgradeAndDoctorTest::test_a_pth_file_in_a_virtualenv_on_path_never_runs_in_the_hooks,
  test tests/test_agent_hook.py::SettingsTest::test_a_pth_file_in_a_virtualenv_on_path_never_runs_in_the_agent_hook,
  test tests/test_install.py::UpgradeAndDoctorTest::test_a_config_hook_never_imports_a_module_planted_beside_the_bootstrap,
  test tests/test_install.py::UpgradeAndDoctorTest::test_the_checkout_s_guard_in_adoption_never_imports_a_module_beside_it
- **Recurrences:**
  - 2026-10-24, review finding on 0.4.0: the agent hook ran the checkout's copy, which the agent can edit. The plug
    covered the guard and `ci`, not the agent hook added after it.
  - 2026-10-24, final review: when the base branch lost its guard, the bootstrap ran the checkout's copy. The plug
    tested a base branch with a guard; the last guard the base branch had now judges.
  - 2026-10-24, re-review of 0.6.0's last commit (2a67cce): install made a base branch's tracking remote the base
    even when it had no review rules (an `upstream` or any other remote), so the checkout's own guard judged
    pushes; a REVIEW.md that only mentioned the rules block in prose also counted as rules. The plug tested an
    `upstream` with no REVIEW.md, never a base branch tracking one, and never an edited guard after install.
  - 2026-10-26, reported by an adopter's session (seqslab_skill) after 0.9.0: the agent hook ran `python3 -c`, so
    a stdlib-named file the agent writes in the working directory (`json.py`) stood in for the hook's imports, the
    hook crashed, and "any error allows" let `git push --no-verify` through; the pre-push wrapper ran the
    bootstrap the same way, from `.git/review-slices/`, where only the stamp and the bootstrap are protected. The
    plugs ran the base branch's code, never asking what else Python imports beside it. Every Python the hooks
    start now runs isolated and without site (`-I -S`: the review found a `.pth` file in a virtualenv on PATH ran
    under `-I` alone), and `doctor` names hooks an older install wrote. The review also found that a push whose
    command line sets `PATH` or git's own variables gets past the agent hook; the owner chose to list it as a
    known hole rather than chase it in the hook's parser.

## I2. The guard fails open on unexpected input

- **Date / kind / status:** 2026-10-23 · defect · plugged
- **What happened:** In 0.1.0, comma-separated globs matched nothing (H3), a `#` cut a test command (H4), tag
  pushes went unchecked (H6), a hook chained before the guard could drain its input (H5), a deleted REVIEW.md
  switched the guard off (H7), `diff.relative` and `log.showSignature` hid paths and trailers (H9), a second
  `test:` line won silently (H13) and an ignored submodule update was invisible (H14).
- **Slice that should have caught it:** 1 Offline suite. Why it did not: the guard had no tests.
- **Failure class:** the guard fails open on input it did not expect
- **Fix:** 0.2.0 and 0.3.0; each repro is a test.
- **Plug:** test tests/test_rules.py::test_comma_separated_globs_are_read_as_separate_globs,
  test tests/test_rules.py::test_a_hash_inside_a_command_is_kept,
  test tests/test_pre_push.py::test_a_tag_push_is_checked,
  test tests/test_install.py::test_a_hook_file_chains_an_existing_hook_that_drains_stdin,
  test tests/test_pre_push.py::test_a_push_that_deletes_review_md_is_refused,
  test tests/test_level.py::test_diff_relative_does_not_hide_paths_outside_the_current_directory,
  test tests/test_pre_push.py::test_a_signed_commit_keeps_its_trailer_under_log_show_signature,
  test tests/test_run_suite.py::test_every_test_line_is_required,
  test tests/test_level.py::test_a_submodule_update_counts_even_when_gitmodules_ignores_it,
  test tests/test_pre_push.py::test_a_push_to_a_review_ref_is_checked,
  test tests/test_pre_push.py::test_broken_standing_rules_fail_closed,
  test tests/test_merges.py::MergePathsTest::test_a_dropped_change_is_counted,
  test tests/test_merges.py::MergePathsTest::test_an_octopus_merge_that_drops_a_change_is_counted,
  test tests/test_agent_hook.py::AgentHookTest::test_overrides_are_denied,
  test tests/test_agent_hook.py::AmendTest::test_staging_and_amending_in_one_command_is_denied
- **Recurrences:**
  - 2026-10-23, review finding on 0.2.0: a push to `refs/for/main` (Gerrit) went unchecked. The plug tested
    branches and tags only, the two ref kinds the fix had in mind.
  - 2026-10-23, review finding on 0.3.0: a config hook is invisible to a git older than 2.54 pushing from the same
    clone. The plug tested one git version; install now writes a hook file by default.
  - 2026-10-24, review finding on 0.4.0: a merge that dropped a change was invisible on git before 2.36 and in
    octopus merges, and wrappers such as `timeout` or `xargs` got `--no-verify` past the agent hook. The plugs ran
    on the newest git and plain commands only; the fallback is now tested directly, and the wrappers by name.
  - 2026-10-24, final review: `git add -A && git commit --amend` put unreviewed content under a trailer, because
    the agent hook read the index before the command staged anything. The plug staged the content beforehand.

## I3. A push is measured across other people's commits

- **Date / kind / status:** 2026-10-23 · defect · plugged
- **What happened:** In 0.1.0, merging an untrailered main commit into a pushed branch demanded a review of main's
  change (H2), and `level` measured from the upstream while the hook measured from the last trailer (H11).
- **Slice that should have caught it:** 1 Offline suite. Why it did not: the guard had no tests.
- **Failure class:** a push is measured across commits that are not the author's
- **Fix:** 0.4.0 judges only the new commits, each by its own paths, and a merge only where it differs from git's
  own merge; `status` and `ci` use the same code.
- **Plug:** test tests/test_pre_push.py::test_merging_main_into_a_branch_does_not_ask_to_review_main,
  test tests/test_pre_push.py::test_a_clean_merge_of_main_needs_no_review,
  test tests/test_pre_push.py::test_status_and_pre_push_agree_after_a_trailer,
  test tests/test_status.py::test_status_counts_unpushed_work_on_main_like_the_hook_does,
  test tests/test_ci.py::test_github_s_synthetic_merge_commit_needs_no_trailer,
  test tests/test_merges.py::UnitsFollowHistoryTest::test_a_trailer_on_one_branch_never_covers_the_other_with_a_first,
  test tests/test_status.py::StatusTest::test_an_upstream_that_is_someone_else_s_branch_is_not_trusted
- **Recurrences:**
  - 2026-10-23, review finding on 0.3.0: `status` measured from the merge-base with local main while the hook
    measured what the remote lacked. The plug compared the two after a trailer, not with unpushed work on main.
  - 2026-10-24, review finding on 0.4.0: review units followed listing order, so a trailer on one merged branch
    covered the other branch's unreviewed commit. The plug merged main into a branch, never two reviewed
    branches into each other; units now follow each trailer's own history.
  - 2026-10-24, final review: `status` trusted the branch's upstream, which `pre-push` does not, so work branched
    from a teammate's unreviewed branch looked trivial. The plug's branches had no upstream of someone else's.

## I4. Setup breaks the host repo's existing tooling

- **Date / kind / status:** 2026-10-23 · defect · plugged
- **What happened:** 0.1.0's setup set `core.hooksPath .githooks`, which silently disables every hook in
  `.git/hooks`, including git-lfs's pre-push upload (H16).
- **Slice that should have caught it:** 2 Review. Why it did not: no reviewer checked setup against repos with
  existing hooks.
- **Failure class:** setup breaks the host repo's existing hooks or checks
- **Fix:** 0.3.0's `setup_tools.py install` never sets `core.hooksPath`: it chains an existing pre-push hook, uses
  pre-commit's `.legacy` hook, or registers a config hook beside a foreign `core.hooksPath`.
- **Plug:** test tests/test_pre_push.py::test_an_existing_hook_keeps_running_beside_the_guard,
  test tests/test_install.py::test_a_config_hook_runs_beside_a_foreign_hooks_path,
  test tests/test_install.py::test_install_moves_a_0_1_0_clone_off_hooks_path,
  test tests/test_install.py::InstallTest::test_installed_copies_are_executable,
  test tests/test_install.py::InstallTest::test_copied_scripts_tell_strict_linters_to_skip_them
- **Recurrences:**
  - 2026-10-24, acceptance trial: adopting turned a repo's `ruff check .` red on the copied scripts (not
    executable, linted as the repo's own code). The plug covered hooks only; the copies now carry skip headers
    and are executable, and SKILL.md says how to exclude them from formatters.
  - 2026-10-25, roadmap item: `ruff check --select ALL` still failed on the copies, since ruff 0.11+ flags their
    blanket `# ruff: noqa` and `# flake8: noqa` (PGH004). No plug checked the headers (the executable test reads
    only the mode bit), and they were tried with ruff's default rules only. The headers now exempt PGH004 too,
    checked on ruff 0.1.15 to 0.17.2, and a test pins them; ruff's preview rules still need the exclude in SKILL.md.

## I5. A setup tool runs a one-way door it should only list

- **Date / kind / status:** 2026-10-24 · defect · plugged
- **What happened:** `discover.py --run`, which tries a repo's checks on a clean tree, counted deploy steps,
  `--push`/`--publish` flags, and publishing commands in package.json, Makefile, justfile and CONTRIBUTING as local
  checks, so it would have run them with the user's stored credentials.
- **Slice that should have caught it:** 2 Review. Why it did not: the first review round saw CI workflows only; the
  later rounds and the final review found the same shape in every other source.
- **Failure class:** a tool runs a one-way door it should only list
- **Fix:** every candidate, from every source, goes through the deploy and publish check; anything remote is
  listed, never run.
- **Plug:** test tests/test_discover.py::ListTest::test_deploy_jobs_and_steps_are_never_local,
  test tests/test_discover.py::RunTest::test_run_never_runs_a_publishing_script_recipe_or_contributing_line,
  test tests/test_discover.py::RunTest::test_run_never_runs_a_deploy
- **Recurrences:** none
