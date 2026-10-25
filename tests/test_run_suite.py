"""`run-suite`: run every check in the suite and stamp the tree only on a clean pass."""
import os
import subprocess
import sys
import unittest

from support import ENV, RULES, Repo, review_md


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

    def test_each_check_reports_its_exit_code_and_time(self):
        repo = Repo(self, rules=RULES.replace("test: true", "test: true\ntest: true"))
        done = repo.run_suite()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("[1/2] exit 0 after", done.stdout)
        self.assertIn("[2/2] exit 0 after", done.stdout)

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

    def test_a_pass_on_a_tree_that_is_not_head_says_so(self):
        repo = Repo(self)
        repo.write("README.md", "someone else's uncommitted edit\n")
        done = repo.run_suite()
        self.assertEqual(done.returncode, 0)
        self.assertIn("NOT HEAD's tree", done.stderr)
        self.assertIn("README.md", done.stderr)

    def test_the_repo_copy_runs_the_suite_wrapper_beside_it(self):
        repo = Repo(self)
        guard = os.path.join(repo.path, ".githooks", "review_slices.py")
        done = subprocess.run((sys.executable, guard, "run-suite"), cwd=repo.path, capture_output=True, text=True,
                              env=ENV)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("stamped tree", done.stdout)
        repo.remove(".githooks/run_suite.py")
        repo.commit("lose the suite wrapper")
        done = subprocess.run((sys.executable, guard, "run-suite"), cwd=repo.path, capture_output=True, text=True,
                              env=ENV)
        self.assertEqual(done.returncode, 2)
        self.assertIn("run_suite.py did not load (FileNotFoundError", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_each_guard_runs_the_suite_wrapper_beside_it(self):
        repo = Repo(self)
        repo.write(".githooks/run_suite.py", "def run(guard, args):\n    return 7\n")
        repo.commit("a branch's own suite wrapper")
        self.assertEqual(repo.run_suite().returncode, 0)  # the skill's guard runs the skill's
        guard = os.path.join(repo.path, ".githooks", "review_slices.py")
        done = subprocess.run((sys.executable, guard, "run-suite"), cwd=repo.path, capture_output=True, text=True,
                              env=ENV)
        self.assertEqual(done.returncode, 7)

    def test_a_broken_suite_wrapper_is_named_not_a_traceback(self):
        repo = Repo(self)
        repo.write(".githooks/run_suite.py", 'VERSION = "0.7.0"\n')
        repo.commit("a suite wrapper with no run()")
        done = subprocess.run((sys.executable, os.path.join(repo.path, ".githooks", "review_slices.py"), "run-suite"),
                              cwd=repo.path, capture_output=True, text=True, env=ENV)
        self.assertEqual(done.returncode, 2)
        self.assertIn("run_suite.py did not load (AttributeError", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_every_test_line_is_required(self):  # H13
        repo = Repo(self, rules=RULES.replace("test: true", "test: false\ntest: true"))
        self.assertNotEqual(repo.run_suite().returncode, 0)


if __name__ == "__main__":
    unittest.main()
