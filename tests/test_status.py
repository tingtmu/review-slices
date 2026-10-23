"""`status`: where the work stands, and the next step, at every point of the procedure."""
import os
import shlex
import subprocess
import sys
import unittest

from support import ENV, RULES, Repo, review_md


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.repo.install()

    def status(self):
        done = self.repo.guard("status")
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def next_step(self):
        return [line for line in self.status().splitlines() if line.startswith("next: ")][0]

    def test_the_procedure_from_edit_to_push(self):
        repo = self.repo
        repo.write("core/a.py")
        self.assertIn("commit this work locally", self.next_step())
        repo.commit("change")
        step = self.next_step()
        start = repo.out("rev-parse", "--short=12", "origin/main")
        self.assertIn("git diff %s..HEAD" % start, step)  # H12: reviewers see the committed work
        self.assertIn("a Standards, a Spec and an adversarial reviewer", step)
        command = step[step.index("`git -c"):].strip("`")
        repo.git(*shlex.split(command)[1:])
        self.assertIn("run the suite", self.next_step())
        self.assertEqual(repo.run_suite().returncode, 0)
        self.assertIn("go-ahead", self.next_step())
        done = repo.try_push()
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_amend_command_keeps_the_message_and_ignores_staged_work(self):
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("the change itself")
        step = self.next_step()
        repo.write("src/later.py")
        repo.git("add", "src/later.py")
        repo.git(*shlex.split(step[step.index("`git -c"):].strip("`"))[1:])
        self.assertEqual(repo.out("log", "-1", "--format=%s"), "the change itself")
        self.assertNotIn("src/later.py", repo.out("show", "--name-only", "--format=", "HEAD"))
        self.assertIn("Review: critical", repo.out("log", "-1", "--format=%B"))

    def test_status_names_the_standing_rules_and_the_hook(self):
        out = self.status()
        self.assertIn("standing rules: REVIEW.md at", out)
        self.assertIn("hook: ", out)
        self.assertNotIn("NOT WIRED", out)

    def test_a_too_low_trailer_is_fixed_by_the_printed_command(self):
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("reviewed too lightly", trailer=repo.trailer("simple"))
        step = self.next_step()
        self.assertIn("fix the trailers", step)
        self.assertNotIn("go-ahead", step)
        command = 'git -c trailer.ifexists=replace commit --amend --only --no-edit --trailer "%s"' % (
            repo.trailer("critical"))
        repo.git(*shlex.split(command)[1:])
        self.assertEqual(repo.out("log", "-1", "--format=%(trailers:key=Review,valueonly)").count("\n"), 0)
        self.assertEqual(repo.run_suite().returncode, 0)
        done = repo.try_push()
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_status_counts_unpushed_work_on_main_like_the_hook_does(self):
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("unpushed and unreviewed, on main")
        repo.git("switch", "-q", "-c", "feature")
        repo.write("src/b.py")
        repo.commit("a feature", trailer=repo.trailer("simple"))
        self.assertIn("fix the trailers", self.next_step())
        self.assertEqual(repo.run_suite().returncode, 0)
        self.assertNotEqual(repo.try_push("origin", "feature").returncode, 0)

    def test_status_names_the_guard_and_a_base_mismatch(self):
        repo = self.repo
        repo.git("config", "review-slices.base", "origin/develop")
        out = self.status()
        self.assertIn("guard: ", out)
        self.assertIn("REVIEW.md's base is main", out)

    def test_an_unwired_clone_is_named(self):
        repo = Repo(self)
        self.assertIn("NOT WIRED", repo.guard("status").stdout)

    def test_an_error_in_the_standing_rules_says_where_to_fix_it(self):
        repo = self.repo
        repo.write("REVIEW.md", review_md(RULES + "critical: <a placeholder nobody filled>\n"))
        repo.commit("a placeholder")
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.git("fetch", "-q")
        repo.write("src/x.py")
        self.assertIn("fix on the base branch, not in this change", self.status())

    def test_status_hands_off_to_the_base_branch_guard(self):
        repo = self.repo
        path = os.path.join(repo.path, ".githooks", "review_slices.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        repo.write(".githooks/review_slices.py", source.replace('print("level: %s" % level)',
                                                                'print("level: %s (edited)" % level)'))
        self.assertNotIn("(edited)", self.repo_copy_status())
        self.assertIn("(edited)", self.repo_copy_status(REVIEW_SLICES_HANDOFF="1"))

    def repo_copy_status(self, **env):
        """Run the repo's own (edited) copy of the guard, not the skill's."""
        done = subprocess.run((sys.executable, os.path.join(self.repo.path, ".githooks", "review_slices.py"),
                               "status"), cwd=self.repo.path, capture_output=True, text=True, env=dict(ENV, **env))
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

if __name__ == "__main__":
    unittest.main()
