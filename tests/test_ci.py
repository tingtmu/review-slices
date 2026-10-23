"""`ci BASE HEAD`: trailer coverage for a pull request, checked on the server where no clone opted out."""
import os
import subprocess
import sys
import unittest

from support import ENV, GUARD, Repo


class CiTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.base = self.repo.out("rev-parse", "main")
        self.repo.git("switch", "-q", "-c", "feature")

    def ci(self, base, head):
        return subprocess.run((sys.executable, GUARD, "ci", base, head), cwd=self.repo.path, capture_output=True,
                              text=True, env=ENV)

    def test_covered_commits_pass(self):
        repo = self.repo
        repo.write("core/a.py")
        head = repo.commit("reviewed", trailer=repo.trailer("critical"))
        done = self.ci(self.base, head)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("every one covered", done.stdout)

    def test_uncovered_commits_fail(self):
        repo = self.repo
        repo.write("core/a.py")
        head = repo.commit("unreviewed")
        done = self.ci(self.base, head)
        self.assertEqual(done.returncode, 1)
        self.assertIn("core/a.py", done.stdout)

    def test_github_s_synthetic_merge_commit_needs_no_trailer(self):  # H18
        repo = self.repo
        repo.write("core/a.py", "one\n1\n2\n3\n4\ntwo\n")
        head = repo.commit("reviewed", trailer=repo.trailer("critical"))
        repo.git("switch", "-q", "main")
        repo.write("core/b.py")
        base = repo.commit("main moved on", trailer=repo.trailer("critical"))
        repo.git("switch", "-q", "--detach", base)
        repo.git("merge", "-q", "--no-ff", "--no-edit", head)
        synthetic = repo.out("rev-parse", "HEAD")
        done = self.ci(base, synthetic)
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_a_pull_request_that_deletes_review_md_fails(self):
        repo = self.repo
        repo.git("rm", "-q", "REVIEW.md")
        head = repo.commit("drop the rules", trailer=repo.trailer("critical"))
        done = self.ci(self.base, head)
        self.assertEqual(done.returncode, 1)
        self.assertIn("deletes or moves REVIEW.md", done.stdout)

    def test_ci_runs_the_guard_committed_at_base(self):
        repo = self.repo
        path = os.path.join(repo.path, ".githooks", "review_slices.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        repo.write(".githooks/review_slices.py", source.replace("def cmd_ci(args):\n",
                                                                "def cmd_ci(args):\n    return 0\n", 1))
        repo.write("core/a.py")
        head = repo.commit("unreviewed, with a friendlier guard")
        done = subprocess.run((sys.executable, path, "ci", self.base, head), cwd=repo.path, capture_output=True,
                              text=True, env=ENV)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
