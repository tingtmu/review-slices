"""`status`: when one merged reviewer may take an Important push (MERGED_LINES, MERGED_FILES)."""
import unittest

import os

from support import MERGED, RULES, Repo, load_guard, load_script, read_text

GUARD = load_guard()
SIZER = load_script("merged_reviewer", MERGED)
LIB_RULES = RULES + "important: lib/*\n"


class MergedReviewerTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self, rules=LIB_RULES)
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
        self.assertEqual(review, "review: merged reviewer allowed: one reviewer for the adversarial, Standards and "
                                 "Spec lenses (%s)" % size)
        self.assertIn("review at important: one merged reviewer", step)

    def assertThree(self, why):
        review, step = self.review()
        self.assertEqual(review, "review: three reviewers (%s)" % why)
        self.assertIn("review at important: a Standards, a Spec and an adversarial reviewer", step)
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
        self.assertAllowed("40 weighted line(s), 3 file(s) in 1 new commit(s)")

    def test_one_weighted_line_or_one_file_over_is_three_reviewers(self):
        self.change({"lib/a.py": "a\n" * 41})
        self.assertThree("41 weighted line(s), 1 file(s) in 1 new commit(s): over 40 or 3")
        self.repo.git("reset", "-q", "--hard", "origin/main")
        self.change({"lib/%d.py" % number: "x\n" for number in range(4)})
        self.assertThree("4 weighted line(s), 4 file(s) in 1 new commit(s): over 40 or 3")

    def test_a_few_minified_lines_are_not_small(self):
        self.change({"lib/min.js": ("x" * 1500 + "\n") * 3})
        self.assertThree("45 weighted line(s), 1 file(s) in 1 new commit(s): over 40 or 3")

    def test_a_floor_path_is_never_merged(self):
        self.change({"lib/a.py": "a\n", ".githooks/extra.py": "e\n"})
        self.assertThree(".githooks/extra.py is always at least important")

    def test_uncommitted_or_untracked_work_is_never_merged(self):
        self.change({"lib/a.py": "a\n"})
        self.repo.write("lib/new.py")
        self.assertEqual(self.review()[0], "review: three reviewers (uncommitted work)")
        self.repo.remove("lib/new.py")
        self.repo.write("lib/a.py", "edited\n")
        self.assertEqual(self.review()[0], "review: three reviewers (uncommitted work)")

    def test_no_base_branch_tip_is_never_merged(self):
        self.change({"lib/a.py": "a\n"})
        self.repo.git("update-ref", "-d", "refs/remotes/origin/main")
        self.assertThree("the base branch is not fetched")

    def test_several_small_units_in_one_push_add_up(self):
        self.change({"lib/a.py": "a\n" * 30}, "first unit", self.repo.trailer("important"))
        self.change({"lib/b.py": "b\n" * 20}, "second unit")
        self.assertThree("50 weighted line(s), 2 file(s) in 2 new commit(s): over 40 or 3")

    def test_a_binary_file_is_never_merged(self):
        self.change({"lib/b.bin": "\0\1\n"})
        self.assertThree("a binary file")

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
        self.assertAllowed("5 weighted line(s), 1 file(s) in 2 new commit(s)")

    def test_a_merge_with_changes_of_its_own_is_never_merged(self):
        self.other_work_on_main()
        self.repo.git("merge", "-q", "--no-commit", "origin/main")
        self.repo.write("lib/evil.py", "made in the merge\n")
        self.repo.git("add", "-A")
        self.repo.git("commit", "-q", "--no-edit")
        merge = self.repo.out("rev-parse", "HEAD")
        self.assertThree("merge %s has changes of its own" % merge[:12])

    def on_main(self, files, message):
        """Commit FILES on main and put it on the remote, as reviewed work already there."""
        self.change(files, message, self.repo.trailer("important"))
        self.repo.git("push", "-q", "--no-verify", "origin", "main")
        self.repo.git("fetch", "-q")

    def test_deleted_lines_that_start_with_dashes_count(self):  # review: hunk lengths were never exercised
        self.on_main({"lib/a.sql": "-- note\n" * 45 + "select 1;\n"}, "base")
        self.change({"lib/a.sql": "select 1;\n"})
        self.assertThree("45 weighted line(s), 1 file(s) in 1 new commit(s): over 40 or 3")

    def test_a_submodule_update_is_never_merged(self):  # review: a gitlink bump measured as 2 lines
        sha = self.repo.out("rev-parse", "HEAD")
        self.repo.git("update-index", "--add", "--cacheinfo", "160000,%s,lib/sub" % sha)
        self.repo.git("commit", "-q", "-m", "add a submodule")
        os.makedirs(os.path.join(self.repo.path, "lib", "sub"))  # not checked out: an empty directory
        self.assertThree("a submodule update")

    def test_a_submodule_its_own_gitmodules_ignores_is_never_merged(self):  # review: ignore = all hid it (I1)
        sha = self.repo.out("rev-parse", "HEAD")
        self.repo.write(".gitmodules", '[submodule "sub"]\n\tpath = lib/sub\n\turl = ./sub\n\tignore = all\n')
        self.repo.git("update-index", "--add", "--cacheinfo", "160000,%s,lib/sub" % sha)
        self.repo.git("add", ".gitmodules")
        self.repo.git("commit", "-q", "-m", "add a submodule")
        os.makedirs(os.path.join(self.repo.path, "lib", "sub"))
        self.assertThree("a submodule update")

    def test_a_git_lfs_pointer_is_never_merged(self):  # review: a 500 MB model measured as its pointer
        self.change({"lib/model.onnx": "version https://git-lfs.github.com/spec/v1\noid sha256:%s\nsize 524288000\n"
                                       % ("0" * 64)})
        self.assertThree("a binary file")

    def test_status_with_a_base_measures_no_push(self):  # review: BASE measured a subset of the push
        self.change({"lib/a.py": "a\n" * 200})
        self.change({"lib/b.py": "b\n"}, "small", self.repo.trailer("important"))
        self.change({"lib/c.py": "c\n"})
        done = self.repo.guard("status", self.repo.out("rev-parse", "HEAD~1"))
        self.assertIn("review: three reviewers (a BASE was given, so the push is not measured whole)", done.stdout)

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
        self.assertThree("merge %s has changes of its own" % repo.out("rev-parse", "HEAD")[:12])

    def test_a_base_branch_guard_without_the_line_prints_none(self):  # handoff to an older guard
        path = os.path.join(self.repo.path, ".githooks", "review_slices.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertEqual(source.count('    if merged:\n        print("review: '), 1)
        self.on_main({".githooks/review_slices.py": source.replace('    if merged:\n        print("review: ',
                                                                     '    if False:\n        print("review: ')},
                     "an older guard")
        self.change({"lib/a.py": "a\n"})
        review, step = self.review()
        self.assertIsNone(review)
        self.assertIn("a Standards, a Spec and an adversarial reviewer", step)

    def test_only_important_prints_the_line(self):
        self.change({"core/x.py": "x\n"})
        self.assertIsNone(self.review()[0])  # critical: never merged
        self.repo.git("reset", "-q", "--hard", "origin/main")
        self.change({"src/x.py": "x\n"})
        review, step = self.review()
        self.assertIsNone(review)
        self.assertIn("review at simple: 1-2 adversarial reviewers", step)


if __name__ == "__main__":
    unittest.main()
