"""`check` lints the working copy's rules against this repo; `--version` names the guard's version."""
import unittest

from support import RULES, Repo, load_guard, review_md


class CheckTest(unittest.TestCase):
    def test_good_rules_pass(self):
        repo = Repo(self, rules=RULES.replace("trivial: notes/*\n", ""))
        done = repo.guard("check")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("check: ok", done.stdout)

    def test_a_glob_that_matches_no_tracked_file_is_a_warning(self):
        repo = Repo(self)
        done = repo.guard("check")
        self.assertEqual(done.returncode, 0)
        self.assertIn("notes/* matches no tracked file", done.stdout)

    def test_a_placeholder_is_an_error(self):
        repo = Repo(self, rules=RULES + "critical: <paths whose change contains a one-way door>\n")
        done = repo.guard("check")
        self.assertEqual(done.returncode, 1)
        self.assertIn("placeholder", done.stdout)

    def test_a_base_that_does_not_resolve_is_an_error(self):
        repo = Repo(self, rules=RULES.replace("base: main", "base: master"))
        done = repo.guard("check")
        self.assertEqual(done.returncode, 1)
        self.assertIn("base: master", done.stdout)

    def test_a_remote_tracking_base_resolves(self):
        repo = Repo(self, rules=RULES.replace("base: main", "base: develop"))
        repo.git("push", "-q", "origin", "main:develop")
        repo.git("fetch", "-q")
        self.assertEqual(repo.guard("check").returncode, 0)

    def test_level_shows_lint_messages(self):
        repo = Repo(self)
        repo.write("REVIEW.md", review_md(RULES + "critical: core/*, deploy/*\n"))
        self.assertIn("one glob per line", repo.guard("level").stdout)

    def test_version(self):
        repo = Repo(self)
        done = repo.guard("--version")
        self.assertEqual(done.stdout.strip(), load_guard().VERSION)


if __name__ == "__main__":
    unittest.main()
