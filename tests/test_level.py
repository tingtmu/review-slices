"""`level`: the review level of everything a push from here would add, and the trailer to write."""
import os
import subprocess
import unittest

from support import ENV, RULES, Repo, review_md


class LevelTest(unittest.TestCase):
    def level(self, repo, cwd=None):
        done = repo.guard("level", cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_reports_the_highest_level_and_the_trailer(self):
        repo = Repo(self)
        repo.write("core/a.py")
        repo.write("src/b.py")
        repo.commit("change")
        out = self.level(repo)
        self.assertIn("level: critical", out)
        self.assertIn("core/a.py", out)
        self.assertIn("Review: critical", out)

    def test_uncommitted_and_untracked_files_count(self):
        repo = Repo(self)
        repo.write("core/new.py")
        self.assertIn("level: critical", self.level(repo))

    def test_a_rename_counts_at_both_paths(self):
        repo = Repo(self)
        repo.write("core/a.py")
        repo.commit("add", trailer=repo.trailer("critical"))
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.git("fetch", "-q")
        os.makedirs(os.path.join(repo.path, "src"))
        repo.git("mv", "core/a.py", "src/a.py")
        repo.commit("move out of core")
        self.assertIn("level: critical", self.level(repo))

    def test_nothing_new_is_trivial(self):
        repo = Repo(self)
        self.assertIn("level: trivial", self.level(repo))

    def test_diff_relative_does_not_hide_paths_outside_the_current_directory(self):  # H9
        repo = Repo(self)
        repo.git("config", "diff.relative", "true")
        repo.write("core/a.py")
        repo.write("docs/x.md")
        repo.commit("change")
        self.assertIn("level: critical", self.level(repo, cwd=os.path.join(repo.path, "docs")))

    def test_level_measures_from_the_last_local_trailer(self):  # H11
        repo = Repo(self)
        repo.write("core/a.py")
        repo.commit("reviewed", trailer=repo.trailer("critical"))
        repo.write("notes/n.md")
        repo.commit("notes")
        self.assertIn("level: trivial", self.level(repo))

    def test_a_changed_test_command_is_reported(self):  # H1
        repo = Repo(self)
        repo.write("REVIEW.md", review_md(RULES.replace("test: true", "test: echo weaker")))
        repo.commit("change the suite")
        done = repo.guard("level")
        self.assertIn("echo weaker", done.stdout + done.stderr)

    def test_a_submodule_update_counts_even_when_gitmodules_ignores_it(self):  # H14
        repo = Repo(self)
        sub = os.path.join(repo.tmp, "sub")
        for args in (("init", "-q", "-b", "main", sub),
                     ("-C", sub, "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-q", "--allow-empty",
                      "-m", "one")):
            subprocess.run(("git",) + args, check=True, env=ENV, capture_output=True)
        repo.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", sub, "core/sub")
        repo.git("config", "-f", ".gitmodules", "submodule.core/sub.ignore", "all")
        repo.commit("add a submodule", trailer=repo.trailer("critical"))
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.git("fetch", "-q")
        subprocess.run(("git", "-C", sub, "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-q",
                        "--allow-empty", "-m", "two"), check=True, env=ENV, capture_output=True)
        inner = os.path.join(repo.path, "core", "sub")
        repo.git("-c", "protocol.file.allow=always", "fetch", "-q", "origin", cwd=inner)
        repo.git("checkout", "-q", "FETCH_HEAD", cwd=inner)
        repo.git("add", "--force", "core/sub")
        repo.commit("bump the submodule", all_files=False)
        changed = repo.out("diff-tree", "--no-commit-id", "-r", "--name-only", "--ignore-submodules=none", "HEAD")
        self.assertEqual(changed, "core/sub")
        self.assertIn("level: critical", self.level(repo))


if __name__ == "__main__":
    unittest.main()
