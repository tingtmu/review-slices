"""`run-suite`: run every check in the suite and stamp the tree only on a clean pass."""
import os
import unittest

from support import RULES, Repo, review_md


class RunSuiteTest(unittest.TestCase):
    def stamp_file(self, repo):
        return os.path.join(repo.path, ".git", "review-slices", "suite-pass")

    def test_a_pass_stamps_the_tree(self):
        repo = Repo(self)
        done = repo.run_suite()
        self.assertEqual(done.returncode, 0, done.stderr)
        tree = repo.out("rev-parse", "HEAD^{tree}")
        with open(self.stamp_file(repo), encoding="utf-8") as handle:
            self.assertIn(tree, handle.read())

    def test_a_failure_writes_no_stamp(self):
        repo = Repo(self, rules=RULES.replace("test: true", "test: false"))
        self.assertNotEqual(repo.run_suite().returncode, 0)
        self.assertFalse(os.path.exists(self.stamp_file(repo)))

    def test_files_changed_during_the_run_write_no_stamp(self):
        repo = Repo(self, rules=RULES.replace("test: true", "test: echo more >> README.md"))
        done = repo.run_suite()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("changed", done.stderr)
        self.assertFalse(os.path.exists(self.stamp_file(repo)))

    def test_the_suite_comes_from_the_working_copy_tree_it_stamps(self):
        repo = Repo(self)
        repo.write("REVIEW.md", review_md(RULES.replace("test: true", "test: false")))
        self.assertNotEqual(repo.run_suite().returncode, 0)

    def test_every_test_line_is_required(self):  # H13
        repo = Repo(self, rules=RULES.replace("test: true", "test: false\ntest: true"))
        self.assertNotEqual(repo.run_suite().returncode, 0)


if __name__ == "__main__":
    unittest.main()
