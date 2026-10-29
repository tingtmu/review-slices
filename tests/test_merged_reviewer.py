"""`status`: the review load of an Important or Critical change (size bands, glob kinds, merged_reviewer.load)."""
import unittest

import os

from support import MERGED, RULES, Repo, load_guard, load_script, read_text

GUARD = load_guard()
SIZER = load_script("merged_reviewer", MERGED)
LIB_RULES = RULES + "important: lib/*\n"
ENGINE_RULES = LIB_RULES + "critical code: engine/*\ncritical: engine/golden/*\n"
# What `status` prints: the widest band on, after "over every band"; the first round, in `next:`.
WIDEST_SMALL, WIDEST_MEDIUM = " (widest on: small, 40 lines, 3 files)", " (widest on: medium, 100 lines, 6 files)"
FIRST = "first round on the whole unit: "


class MergedReviewerTest(unittest.TestCase):
    rules = LIB_RULES

    def setUp(self):
        self.repo = Repo(self, rules=self.rules)
        self.repo.install()

    def status(self):
        done = self.repo.guard("status")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def review(self):
        """The `review:` line of status, or None."""
        out = self.status()
        lines = [line for line in out.splitlines() if line.startswith("review: ")]
        return (lines or [None])[0], [line for line in out.splitlines() if line.startswith("next: ")][0]

    def change(self, files, message="change", trailer=None):
        for path, text in files.items():
            self.repo.write(path, text)
        return self.repo.commit(message, trailer=trailer)

    def assertAllowed(self, size):
        review, step = self.review()
        self.assertEqual(review, "review: one merged reviewer (small: %s, within the small band's 40 lines, 3 files)"
                                 % size)
        self.assertIn("review at important, " + FIRST + "1 merged reviewer", step)

    def assertThree(self, why, level="important"):
        review, step = self.review()
        self.assertEqual(review, "review: three reviewers (%s)" % why)
        self.assertIn("review at %s, " % level + FIRST + "3 separate reviewers (Standards, Spec, adversarial)", step)
        self.assertNotIn("merged", step)

    def test_the_thresholds(self):
        self.assertEqual((SIZER.MERGED_LINES, SIZER.MERGED_FILES), (40, 3))

    def test_a_hunk_header_it_cannot_read_is_an_error(self):  # review: it counted nothing after it (I2)
        self.assertEqual(SIZER.patch_size(GUARD, "diff --git a/x b/x\n@@ -1 +1 @@\n-a\n+b\n"), (2, 1, False))
        with self.assertRaises(GUARD.GuardError):
            SIZER.patch_size(GUARD, "diff --git a/x b/x\n@@ -1 +1,2 xx @@\n+a\n+b\n")

    def test_without_the_base_branch_s_measure_it_is_three_reviewers(self):  # loaded as the secret scanner is
        self.repo.remove(".githooks/merged_reviewer.py")
        self.on_main({}, "drop the measure")
        self.change({"lib/a.py": "a\n"})
        self.assertThree("%s has no .githooks/merged_reviewer.py: run the skill's setup_tools.py upgrade"
                         % self.repo.out("rev-parse", "origin/main")[:12])
        self.assertNotEqual(self.repo.git("cat-file", "-e", "origin/main:.githooks/merged_reviewer.py",
                                          check=False).returncode, 0)

    def test_a_base_branch_without_a_guard_never_lets_the_branch_measure_itself(self):  # review: I1 in adoption
        self.repo = Repo(self, rules=LIB_RULES, guard=False)
        self.change({".githooks/review_slices.py": read_text(GUARD.__file__),
                     ".githooks/merged_reviewer.py": "def allowed(*args):\n    return True, 'branch-module'\n",
                     "lib/a.py": "a\n" * 200})
        self.assertThree("the base branch has no guard yet")

    def test_a_broken_measure_on_the_base_branch_is_three_reviewers(self):
        self.on_main({".githooks/merged_reviewer.py": "def allowed(*args):\n    raise ValueError('broken')\n"},
                     "break the measure")
        self.change({"lib/a.py": "a\n"})
        review = self.review()[0]
        self.assertTrue(review.startswith("review: three reviewers (.githooks/merged_reviewer.py at "), review)
        self.assertIn("did not run: ValueError('broken')", review)

    def test_the_branch_s_own_measure_never_judges_it(self):  # I1: an edited copy that always allows
        self.change({".githooks/merged_reviewer.py": "def allowed(*args):\n    return True, 'edited'\n",
                     "lib/a.py": "a\n" * 100})
        self.assertNotIn("edited", self.review()[0])
        self.repo.git("update-ref", "-d", "refs/remotes/origin/main")  # review: unfetched, it ran this copy
        self.assertThree("the base branch is not fetched")

    def test_a_small_important_push_is_allowed_up_to_the_thresholds(self):
        self.change({"lib/a.py": "a\n" * 38, "lib/b.py": "b\n", "lib/c.py": "c\n"})
        self.assertAllowed("40 weighted line(s), 3 file(s) in 1 commit(s)")

    def test_one_weighted_line_or_one_file_over_is_three_reviewers(self):
        self.change({"lib/a.py": "a\n" * 41})
        self.assertThree("large: 41 weighted line(s), 1 file(s) in 1 commit(s): over every band" + WIDEST_SMALL)
        self.repo.git("switch", "-q", "-c", "files", "origin/main")  # a new unit: a reset is a rewrite
        self.change({"lib/%d.py" % number: "x\n" for number in range(4)})
        self.assertThree("large: 4 weighted line(s), 4 file(s) in 1 commit(s): over every band" + WIDEST_SMALL)

    def test_a_few_minified_lines_are_not_small(self):
        self.change({"lib/min.js": ("x" * 1500 + "\n") * 3})
        self.assertThree("large: 45 weighted line(s), 1 file(s) in 1 commit(s): over every band" + WIDEST_SMALL)

    def test_a_floor_path_is_never_merged(self):
        self.change({"lib/a.py": "a\n", ".githooks/extra.py": "e\n"})
        self.assertThree("large: .githooks/extra.py is a floor path")

    def test_uncommitted_or_untracked_work_is_never_merged(self):
        self.change({"lib/a.py": "a\n"})
        self.repo.write("lib/new.py")
        self.assertEqual(self.review()[0], "review: three reviewers (large: uncommitted work)")
        self.repo.remove("lib/new.py")
        self.repo.write("lib/a.py", "edited\n")
        self.assertEqual(self.review()[0], "review: three reviewers (large: uncommitted work)")

    def test_no_base_branch_tip_is_never_merged(self):
        self.change({"lib/a.py": "a\n"})
        self.repo.git("update-ref", "-d", "refs/remotes/origin/main")
        self.assertThree("the base branch is not fetched")

    def test_several_small_units_in_one_push_add_up(self):
        self.change({"lib/a.py": "a\n" * 30}, "first unit", self.repo.trailer("important"))
        self.change({"lib/b.py": "b\n" * 20}, "second unit")
        self.assertThree("large: 50 weighted line(s), 2 file(s) in 2 commit(s): over every band" + WIDEST_SMALL)

    def test_a_binary_file_is_never_merged(self):
        self.change({"lib/b.bin": "\0\1\n"})
        self.assertThree("large: a binary file")

    def other_work_on_main(self):
        """A feature branch with a small change, and someone else's commit on main, already on the remote."""
        repo = self.repo
        repo.git("checkout", "-q", "-b", "feature")
        self.change({"lib/a.py": "a\n" * 5})
        repo.git("checkout", "-q", "main")
        self.change({"lib/other.py": "o\n" * 50}, "someone else's work")
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.git("checkout", "-q", "feature")

    def test_a_clean_merge_of_main_adds_nothing(self):
        self.other_work_on_main()
        self.repo.git("merge", "-q", "--no-edit", "origin/main")
        self.assertAllowed("5 weighted line(s), 1 file(s) in 2 commit(s)")

    def test_a_merge_with_changes_of_its_own_is_never_merged(self):
        self.other_work_on_main()
        self.repo.git("merge", "-q", "--no-commit", "origin/main")
        self.repo.write("lib/evil.py", "made in the merge\n")
        self.repo.git("add", "-A")
        self.repo.git("commit", "-q", "--no-edit")
        merge = self.repo.out("rev-parse", "HEAD")
        self.assertThree("large: merge %s has changes of its own" % merge[:12])

    def on_main(self, files, message):
        """Commit FILES on main and put it on the remote, as reviewed work already there."""
        self.change(files, message, self.repo.trailer("important"))
        self.repo.git("push", "-q", "--no-verify", "origin", "main")
        self.repo.git("fetch", "-q")

    def moved(self, edit=lambda lines: lines):
        """Move lib/a.md, 100 distinct lines on main, to lib/archive/a.md with EDIT applied to its lines."""
        lines = ["line %d\n" % number for number in range(100)]
        self.on_main({"lib/a.md": "".join(lines)}, "base")
        os.makedirs(os.path.join(self.repo.path, "lib", "archive"))
        self.repo.git("mv", "lib/a.md", "lib/archive/a.md")
        self.repo.write("lib/archive/a.md", "".join(edit(lines)))

    def test_an_exact_rename_counts_one_file_and_no_lines(self):  # issue #13: an archive move measured as 405 lines
        self.moved()
        self.change({"lib/b.py": "b\n" * 20})
        self.assertAllowed("20 weighted line(s), 2 file(s) in 1 commit(s); 1 exact rename(s) counted as 0 lines")

    def test_a_rename_with_an_edit_counts_in_full(self):
        self.moved(lambda lines: lines[:-1] + ["edited\n"])
        self.change({})
        self.assertThree("large: 200 weighted line(s), 2 file(s) in 1 commit(s): over every band" + WIDEST_SMALL)

    def test_a_move_with_two_lines_swapped_counts_in_full(self):  # only git's exact pass, never its similarity
        self.moved(lambda lines: [lines[1], lines[0]] + lines[2:])
        self.change({})
        self.assertThree("large: 200 weighted line(s), 2 file(s) in 1 commit(s): over every band" + WIDEST_SMALL)

    def test_deleted_lines_that_start_with_dashes_count(self):  # review: hunk lengths were never exercised
        self.on_main({"lib/a.sql": "-- note\n" * 45 + "select 1;\n"}, "base")
        self.change({"lib/a.sql": "select 1;\n"})
        self.assertThree("large: 45 weighted line(s), 1 file(s) in 1 commit(s): over every band" + WIDEST_SMALL)

    def test_a_submodule_update_is_never_merged(self):  # review: a gitlink bump measured as 2 lines
        sha = self.repo.out("rev-parse", "HEAD")
        self.repo.git("update-index", "--add", "--cacheinfo", "160000,%s,lib/sub" % sha)
        self.repo.git("commit", "-q", "-m", "add a submodule")
        os.makedirs(os.path.join(self.repo.path, "lib", "sub"))  # not checked out: an empty directory
        self.assertThree("large: a submodule update")

    def test_a_submodule_its_own_gitmodules_ignores_is_never_merged(self):  # review: ignore = all hid it (I1)
        sha = self.repo.out("rev-parse", "HEAD")
        self.repo.write(".gitmodules", '[submodule "sub"]\n\tpath = lib/sub\n\turl = ./sub\n\tignore = all\n')
        self.repo.git("update-index", "--add", "--cacheinfo", "160000,%s,lib/sub" % sha)
        self.repo.git("add", ".gitmodules")
        self.repo.git("commit", "-q", "-m", "add a submodule")
        os.makedirs(os.path.join(self.repo.path, "lib", "sub"))
        self.assertThree("large: a submodule update")

    def test_a_git_lfs_pointer_is_never_merged(self):  # review: a 500 MB model measured as its pointer
        self.change({"lib/model.onnx": "version https://git-lfs.github.com/spec/v1\noid sha256:%s\nsize 524288000\n"
                                       % ("0" * 64)})
        self.assertThree("large: a binary file")

    def test_a_binary_or_lfs_file_moved_unchanged_is_an_exact_rename(self):  # review: untested
        self.on_main({"lib/b.bin": "\0\1\n", "lib/model.onnx": "version https://git-lfs.github.com/spec/v1\n"}, "base")
        os.makedirs(os.path.join(self.repo.path, "lib", "archive"))
        for name in ("b.bin", "model.onnx"):
            self.repo.git("mv", "lib/" + name, "lib/archive/" + name)
        self.change({})
        self.assertAllowed("0 weighted line(s), 2 file(s) in 1 commit(s); 2 exact rename(s) counted as 0 lines")
        self.repo.remove("lib/archive/b.bin")
        self.change({}, "a binary file deleted")
        self.assertThree("large: a binary file")

    def test_status_with_a_base_measures_no_push(self):  # review: BASE measured a subset of the push
        self.change({"lib/a.py": "a\n" * 200})
        self.change({"lib/b.py": "b\n"}, "small", self.repo.trailer("important"))
        self.change({"lib/c.py": "c\n"})
        done = self.repo.guard("status", self.repo.out("rev-parse", "HEAD~1"))
        self.assertIn("review: three reviewers (a BASE was given, so the branch is not measured whole)", done.stdout)

    def test_a_conflict_resolution_is_never_merged(self):
        repo = self.repo
        self.on_main({"lib/a.py": "base\n"}, "base")
        repo.git("checkout", "-q", "-b", "feature")
        self.change({"lib/a.py": "feature\n"})
        repo.git("checkout", "-q", "main")
        self.on_main({"lib/a.py": "main\n"}, "theirs")
        repo.git("checkout", "-q", "feature")
        repo.git("merge", "-q", "origin/main", check=False)
        repo.write("lib/a.py", "resolved\n")
        repo.git("add", "-A")
        repo.git("commit", "-q", "--no-edit")
        self.assertThree("large: merge %s has changes of its own" % repo.out("rev-parse", "HEAD")[:12])

    def test_a_base_branch_guard_without_the_line_prints_none(self):  # handoff to an older guard
        path = os.path.join(self.repo.path, ".githooks", "review_slices.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertEqual(source.count('    if load:\n        print("review: '), 1)
        self.on_main({".githooks/review_slices.py": source.replace('    if load:\n        print("review: ',
                                                                     '    if False:\n        print("review: ')},
                     "an older guard")
        self.change({"lib/a.py": "a\n"})
        review, step = self.review()
        self.assertIsNone(review)
        self.assertIn("review at important, " + FIRST, step)

    def test_only_important_and_critical_print_the_line(self):
        self.change({"core/x.py": "x\n"})
        self.assertThree("core/x.py is not in `critical code:` globs alone", "critical")  # content by default
        self.assertIn("then the user's go-ahead for the one-way door", self.review()[1])
        self.repo.git("reset", "-q", "--hard", "origin/main")
        self.change({"src/x.py": "x\n"})
        review, step = self.review()
        self.assertIsNone(review)
        self.assertIn("review at simple, " + FIRST + "1-2 adversarial reviewers", step)


class ReviewLoadTest(unittest.TestCase):
    """The load table's cells, the bands and the glob kinds (`critical code:`)."""
    setUp, status, review, change = (MergedReviewerTest.setUp, MergedReviewerTest.status, MergedReviewerTest.review,
                                     MergedReviewerTest.change)
    on_main, other_work_on_main = MergedReviewerTest.on_main, MergedReviewerTest.other_work_on_main
    rules = ENGINE_RULES + "medium: 100 lines, 6 files\n"

    def assertLoad(self, load, why):
        self.assertEqual(self.review()[0], "review: %s (%s)" % (load, why))

    def test_important_takes_the_conformance_pair_in_the_medium_band(self):
        self.change({"lib/a.py": "a\n" * 41})
        self.assertLoad("adversarial + conformance", "medium: 41 weighted line(s), 1 file(s) in 1 commit(s), within "
                                                     "the medium band's 100 lines, 6 files")
        self.assertIn("review at important, " + FIRST + "2 separate reviewers (adversarial; conformance",
                      self.review()[1])
        self.change({"lib/b.py": "b\n" * 60})
        self.assertLoad("three reviewers", "large: 101 weighted line(s), 2 file(s) in 2 commit(s): over every band"
                                           + WIDEST_MEDIUM)

    def test_a_small_critical_change_in_code_globs_alone_takes_the_pair(self):
        self.change({"engine/a.py": "a\n" * 12})
        self.assertLoad("adversarial + conformance", "small: 12 weighted line(s), 1 file(s) in 1 commit(s), within "
                                                     "the small band's 40 lines, 3 files")
        step = self.review()[1]
        self.assertIn("review at critical, " + FIRST + "2 separate reviewers (adversarial; conformance", step)
        self.assertIn("then the user's go-ahead for the one-way door", step)
        self.change({"engine/b.py": "b\n" * 30})  # medium at Critical: three
        self.assertLoad("three reviewers", "medium: 42 weighted line(s), 2 file(s) in 2 commit(s), within the "
                                           "medium band's 100 lines, 6 files")

    def test_an_exact_rename_is_judged_at_both_paths(self):  # issue #13: only its size is relieved
        self.on_main({"lib/a.py": "a\n" * 50}, "base")
        os.makedirs(os.path.join(self.repo.path, "engine", "golden"))
        self.repo.git("mv", "lib/a.py", "engine/a.py")
        self.change({}, "into critical code")
        self.assertLoad("adversarial + conformance", "small: 0 weighted line(s), 1 file(s) in 1 commit(s); 1 exact "
                                                     "rename(s) counted as 0 lines, within the small band's 40 lines, "
                                                     "3 files")
        self.repo.git("mv", "engine/a.py", "engine/golden/a.py")
        self.change({}, "into critical content")
        self.assertLoad("three reviewers", "engine/golden/a.py is not in `critical code:` globs alone")

    def test_a_content_path_that_sets_the_level_takes_three(self):
        self.change({"engine/a.py": "a\n" * 12, "engine/golden/x.json": "{}\n"})
        self.assertLoad("three reviewers", "engine/golden/x.json is not in `critical code:` globs alone")

    def test_a_branch_pushed_in_slices_is_measured_whole(self):  # plan review 1: @{push} was a tip; no logged three,
        # so the large unit does not start the measure over (test_restart.py)
        self.repo.git("checkout", "-q", "-b", "feature")
        self.change({"engine/a.py": "a\n" * 200}, "big", self.repo.trailer("critical"))
        self.repo.git("push", "-q", "--no-verify", "-u", "origin", "feature")
        self.change({"engine/b.py": "b\n" * 2})
        self.assertIn("new commits: 1 not yet", self.status())
        self.assertLoad("three reviewers", "large: 202 weighted line(s), 2 file(s) in 2 commit(s): over every band"
                                           + WIDEST_MEDIUM)

    def test_a_pushed_merge_with_changes_of_its_own_still_counts(self):
        self.other_work_on_main()
        self.repo.git("merge", "-q", "--no-commit", "origin/main")
        self.repo.write("lib/evil.py", "made in the merge\n")
        self.repo.git("add", "-A")
        self.repo.git("commit", "-q", "--no-edit")
        merge = self.repo.out("rev-parse", "HEAD")
        self.repo.git("push", "-q", "--no-verify", "-u", "origin", "feature")
        self.change({"lib/c.py": "c\n"})
        self.assertLoad("three reviewers", "large: merge %s has changes of its own" % merge[:12])

    def test_a_branch_that_loosens_the_bands_is_still_judged_by_the_standing_ones(self):  # I1
        self.change({"REVIEW.md": read_text(os.path.join(self.repo.path, "REVIEW.md")).replace(
            "medium: 100 lines", "medium: 400 lines").replace("critical: core/*", "critical code: core/*"),
            "lib/a.py": "a\n" * 150})
        self.assertLoad("three reviewers", "large: REVIEW.md is a floor path")
        self.repo.git("switch", "-q", "-c", "core", "origin/main")  # a new unit: a reset is a rewrite
        self.change({"core/x.py": "x\n"})
        self.assertLoad("three reviewers", "core/x.py is not in `critical code:` globs alone")

    def test_a_base_branch_measure_without_load_judges_important_only(self):  # a 0.8.0 module
        self.on_main({".githooks/merged_reviewer.py": "def allowed(guard, commits, uncommitted, tips):\n"
                                                      "    return True, 'old measure'\n"}, "an 0.8.0 measure")
        self.change({"lib/a.py": "a\n"})
        self.assertLoad("one merged reviewer", "old measure")
        self.change({"engine/a.py": "a\n"})
        at = self.repo.out("rev-parse", "origin/main")[:12]
        self.assertLoad("three reviewers", ".githooks/merged_reviewer.py at %s has no load(): it measures Important "
                                           "changes, under no small: line, only" % at)

    def test_a_base_branch_measure_without_load_never_ignores_a_small_line(self):  # review: small: off was ignored
        self.on_main({".githooks/merged_reviewer.py": "def allowed(guard, commits, uncommitted, tips):\n"
                                                      "    return True, 'old measure'\n",
                      "REVIEW.md": read_text(os.path.join(self.repo.path, "REVIEW.md")).replace(
                          "medium: 100 lines, 6 files", "small: off")}, "an 0.8.0 measure under small: off")
        self.change({"lib/a.py": "a\n"})
        self.assertEqual(self.review()[0].split(" (")[0], "review: three reviewers")


class BandAndKindTest(unittest.TestCase):
    """What parse_config reads from the new lines, and kind(): no Repo, the guard's parser alone."""

    def parse(self, rules):
        return GUARD.parse_config("```review-slices\n%s```\n" % rules)

    def kind(self, rules, path):
        return SIZER.kind(GUARD, self.parse(rules), path)

    def test_a_band_reads_lines_and_files_or_off(self):
        config = self.parse("small: 20 lines, 2 files\nmedium: off\n")
        self.assertEqual((config["small"], config["medium"], config["errors"]), ((20, 2), "off", []))
        self.assertEqual(self.parse("small: 1 line, 1 file\n")["small"], (1, 1))

    def test_a_repeated_band_reads_as_the_stricter(self):
        self.assertEqual(self.parse("small: 30 lines, 1 file\nsmall: 10 lines, 3 files\n")["small"], (10, 1))
        self.assertEqual(self.parse("small: 30 lines, 1 file\nsmall: off\n")["small"], "off")
        self.assertEqual(self.parse("small: off\nsmall: 30 lines, 1 file\n")["small"], "off")

    def test_a_value_it_cannot_read_is_an_error_and_off(self):  # I2: never the looser default
        config = self.parse("small: 30 lines\n")
        self.assertEqual(config["small"], "off")
        self.assertEqual(config["errors"], ["line 1: small: takes off or 'N lines, M files'; read as off"])
        config = self.parse("small: %s lines, 3 files\n" % ("9" * 4400))  # review: int() raised past 4300 digits
        self.assertEqual((config["small"], len(config["errors"])), ("off", 1))

    def test_a_band_over_its_ceiling_reads_as_the_ceiling(self):
        config = self.parse("small: 100 lines, 2 files\nmedium: 900 lines, 99 files\n")
        self.assertEqual((config["small"], config["medium"]), ((80, 2), (400, 20)))
        self.assertEqual(len(config["warnings"]), 2)
        self.assertIn("line 1: small: is over the most it may say, so it reads as 80 lines, 2 files",
                      config["warnings"])

    def test_a_medium_band_at_or_below_small_adds_nothing(self):
        rules = self.parse("small: 40 lines, 3 files\nmedium: 30 lines, 2 files\n")
        for size, expected in (((20, 1), "small"), ((41, 1), "large"), ((30, 4), "large")):
            self.assertEqual(band_with(size, rules)[0], expected, size)
        rules = self.parse("small: off\nmedium: 30 lines, 2 files\n")  # off: the next band that fits
        self.assertEqual(band_with((1, 1), rules)[0], "medium")
        self.assertEqual(band_with((1, 1), self.parse("small: off\n"))[0], "large")

    def test_an_empty_key_is_still_a_parse_error(self):  # review: the kind split must not crash on it
        with self.assertRaises(GUARD.GuardError):
            self.parse(": engine/*\n")

    def test_a_path_in_a_code_and_a_content_glob_is_content_in_either_order(self):  # plan review 1
        for rules in ("critical code: engine/*\ncritical: engine/golden/*\n",
                      "critical: engine/golden/*\ncritical code: engine/*\n"):
            self.assertEqual(self.kind(rules, "engine/golden/x.json"), "content", rules)
            self.assertEqual(self.kind(rules, "engine/src/a.py"), "code", rules)
        self.assertEqual(self.kind("critical code: engine/*\ncritical: engine/*\n", "engine/a.py"), "content")

    def test_a_floor_path_a_default_and_unreadable_rules_are_content(self):
        self.assertEqual(self.kind("critical code: .githooks/*\n", ".githooks/x.py"), "content")
        self.assertEqual(self.kind("default: critical\n", "a.py"), "content")
        self.assertEqual(SIZER.kind(GUARD, GUARD.unreadable_rules("broken"), "a.py"), "content")
        self.assertEqual(SIZER.kind(GUARD, None, "a.py"), "content")

    def test_a_mistyped_kind_is_an_error_and_its_globs_stay_critical_content(self):  # I2
        config = self.parse("critical cdoe: engine/*\nimportant code: lib/*\n")
        self.assertEqual(config["globs"], [("critical", "engine/*"), ("important", "lib/*")])
        self.assertEqual(len(config["errors"]), 2)
        self.assertIn("'critical cdoe' is not a key; its globs count at critical", config["errors"][0])
        self.assertEqual(SIZER.kind(GUARD, config, "engine/a.py"), "content")
        self.assertEqual(GUARD.path_level(config, "engine/a.py")[0], "critical")


def band_with(size, rules):
    """SIZER.band with measure() replaced by a fixed SIZE."""
    measure = SIZER.measure
    SIZER.measure = lambda *args: (size, "%d weighted line(s), %d file(s)" % size)
    try:
        return SIZER.band(GUARD, rules, ["c"], [], ())
    finally:
        SIZER.measure = measure


if __name__ == "__main__":
    unittest.main()
