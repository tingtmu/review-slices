"""calibrate.py: how a level table would have judged the base branch's recent first-parent commits."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import ENV, RULES, SCRIPTS, Repo, review_md

CALIBRATE = os.path.join(SCRIPTS, "calibrate.py")


def calibrate(repo, *args, cwd=None):
    return subprocess.run((sys.executable, CALIBRATE) + args, cwd=cwd or repo.path, capture_output=True, text=True,
                          env=ENV, timeout=120)


class CalibrateTest(unittest.TestCase):
    def run_ok(self, repo, *args):
        """Calibrate against local main unless ARGS name a base: these commits are never pushed."""
        done = calibrate(repo, *(args if "--base" in args else args + ("--base", "main")))
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def assertShare(self, out, level, count, percent):
        self.assertRegex(out, r"\n  %s\s+%d\s+%d%%\n" % (level, count, percent))

    def change(self, repo, path, message=None):
        repo.write(path)
        return repo.commit(message or "change " + path)

    def test_distribution_and_recent_examples(self):
        repo = Repo(self)  # its first commit adds REVIEW.md: important
        critical = self.change(repo, "core/a.py", "touch the core")
        self.change(repo, "notes/n.md")
        self.change(repo, "src/b.py")
        out = self.run_ok(repo)
        self.assertIn("calibrate: 4 first-parent commit(s) of main", out)
        self.assertIn("note: the base branch has only 4 commit(s)", out)
        for level in ("trivial", "simple", "important", "critical"):
            self.assertShare(out, level, 1, 25)
        self.assertIn("%s  touch the core  core/a.py  (core/*)" % critical[:7], out)
        self.assertIn("src/b.py  (no glob: default)", out)
        self.assertIn("every glob matched", out)
        self.assertNotIn("warning", out)

    def test_examples_are_the_three_most_recent_per_level(self):
        repo = Repo(self)
        for number in range(5):
            self.change(repo, "core/%d.py" % number)
        out = self.run_ok(repo)
        self.assertIn("change core/4.py", out)
        self.assertIn("change core/2.py", out)
        self.assertNotIn("change core/1.py", out)

    def test_the_first_commit_is_judged_from_nothing(self):
        repo = Repo(self)
        out = self.run_ok(repo, "--count", "1")
        self.assertShare(out, "important", 1, 100)
        self.assertIn("init  .githooks/review_slices.py  (always at least important)", out)

    def test_a_merge_is_judged_by_its_first_parent_change(self):
        repo = Repo(self)
        repo.git("checkout", "-q", "-b", "side")
        self.change(repo, "core/x.py", "side work")
        repo.git("checkout", "-q", "main")
        self.change(repo, "notes/a.md")
        repo.git("merge", "-q", "--no-ff", "-m", "merge side", "side")
        out = self.run_ok(repo, "--count", "2")
        self.assertShare(out, "critical", 1, 50)
        self.assertShare(out, "trivial", 1, 50)
        self.assertIn("merge side  core/x.py  (core/*)", out)
        self.assertNotIn("side work", out)

    def test_warns_when_most_changes_would_be_critical(self):
        repo = Repo(self)  # init + 7 critical + 12 simple = 20 commits
        for number in range(19):
            self.change(repo, "core/%d.py" % number if number < 7 else "src/%d.py" % number)
        out = self.run_ok(repo)
        self.assertIn("warning: 35% are critical", out)
        self.assertIn("people will route around it", out)

    def test_warns_when_most_changes_would_be_trivial(self):
        repo = Repo(self)  # init + 15 trivial + 4 simple = 20 commits
        for number in range(19):
            self.change(repo, "notes/%d.md" % number if number < 15 else "src/%d.py" % number)
        self.assertIn("warning: 75% are trivial", self.run_ok(repo))

    def test_a_short_history_is_too_few_to_judge(self):  # acceptance trial: "40% critical" on 5 commits
        repo = Repo(self)
        for path in ("core/a.py", "core/b.py", "src/c.py", "src/d.py"):
            self.change(repo, path)
        out = self.run_ok(repo)
        self.assertShare(out, "critical", 2, 40)
        self.assertIn("note: too few commits to judge the mix (5, under 20); run it again later", out)
        self.assertNotIn("warning", out)

    def test_a_draft_in_the_working_copy_is_used_before_it_is_committed(self):
        repo = Repo(self)
        self.change(repo, "notes/n.md")
        repo.write("REVIEW.md", review_md(RULES.replace("trivial: notes/*", "critical: notes/*\nimportant: lib/*")))
        out = self.run_ok(repo, "--count", "1")
        self.assertShare(out, "critical", 1, 100)
        self.assertIn("globs that matched no path in these commits", out)
        self.assertIn("  important: lib/*", out)
        self.assertNotIn("  critical: notes/*", out.split("globs that matched")[1])

    def test_rules_from_another_path(self):
        repo = Repo(self)
        self.change(repo, "src/b.py")
        draft = os.path.join(repo.tmp, "draft.md")
        with open(draft, "w", encoding="utf-8") as handle:
            handle.write(review_md("test: true\ndefault: trivial\ncritical: <a path>\n"))
        out = self.run_ok(repo, "--rules", draft, "--count", "1")
        self.assertIn("judged by %s" % draft, out)
        self.assertShare(out, "trivial", 1, 100)
        self.assertIn("still holds a template placeholder", out)

    def test_the_base_comes_from_git_config_then_origin_head_then_main(self):
        repo = Repo(self)
        repo.git("checkout", "-q", "-b", "release")
        self.change(repo, "core/r.py")
        repo.git("checkout", "-q", "main")
        repo.git("remote", "set-head", "origin", "--delete", check=False)
        self.assertIn("of main (", calibrate(repo).stdout)
        repo.git("remote", "set-head", "origin", "main")
        self.assertIn("of origin/HEAD (", calibrate(repo).stdout)
        repo.git("config", "review-slices.base", "release")
        out = calibrate(repo).stdout
        self.assertIn("of release (", out)
        self.assertShare(out, "critical", 1, 50)
        self.assertIn("of main (", calibrate(repo, "--base", "main").stdout)

    def test_a_shallow_clone_leaves_out_its_edge(self):  # review: the edge commit looked like a root
        repo = Repo(self)
        for number in range(3):
            self.change(repo, "notes/%d.md" % number)
        repo.git("push", "-q", "origin", "main")
        clone = os.path.join(repo.tmp, "shallow")
        Repo.run_git(repo.tmp, "clone", "-q", "--depth", "2", "file://" + repo.remote, clone)
        done = subprocess.run((sys.executable, CALIBRATE), cwd=clone, capture_output=True, text=True, env=ENV)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("calibrate: 1 first-parent commit(s)", done.stdout)
        self.assertShare(done.stdout, "trivial", 1, 100)
        self.assertIn("shallow clone, so 1 commit(s) at its edge were left out", done.stdout)
        self.assertShare(done.stdout, "critical", 0, 0)
        self.assertIn("  critical: core/*", done.stdout)  # the edge is not judged as the whole repo

    @unittest.skipUnless(sys.platform.startswith("linux"), "needs a file system that allows non-UTF-8 names")
    def test_a_non_utf8_path_is_no_traceback(self):
        repo = Repo(self)
        open(os.path.join(os.fsencode(repo.path), b"f\xff"), "w").close()
        repo.commit("odd name")
        done = calibrate(repo, "--base", "main")
        self.assertEqual(done.returncode, 2)
        self.assertIn("not UTF-8", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_a_missing_base_is_named(self):
        repo = Repo(self)
        repo.git("config", "review-slices.base", "origin/gone")
        done = calibrate(repo)
        self.assertEqual(done.returncode, 2)
        self.assertIn("origin/gone (from git config review-slices.base) is not in this clone", done.stderr)

    def test_an_empty_history_has_nothing_to_calibrate(self):
        path = tempfile.mkdtemp(prefix="review-slices-test-")
        self.addCleanup(shutil.rmtree, path, True)
        Repo.run_git(path, "init", "-q", "-b", "main", ".")
        with open(os.path.join(path, "REVIEW.md"), "w", encoding="utf-8") as handle:
            handle.write(review_md())
        done = subprocess.run((sys.executable, CALIBRATE), cwd=path, capture_output=True, text=True, env=ENV)
        self.assertEqual(done.returncode, 2)
        self.assertIn("no commits yet", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_friendly_errors(self):
        repo = Repo(self, rules=None)
        done = calibrate(repo)
        self.assertEqual(done.returncode, 2)
        self.assertIn("REVIEW.md not found", done.stderr)
        repo.write("REVIEW.md", "no block here\n")
        self.assertIn("REVIEW.md (working copy): REVIEW.md has no ```review-slices block", calibrate(repo).stderr)
        for args in (("--count", "0"), ("--count", "x"), ("--rules", repo.tmp)):
            done = calibrate(repo, *args)
            self.assertEqual(done.returncode, 2, args)
            self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
