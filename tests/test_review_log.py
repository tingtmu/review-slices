"""`status`'s review log: the load it printed per review unit, held at the highest, three after a rewrite."""
import os
import re
import shlex
import unittest

from support import MERGED, Repo, read_text
from test_calibrate import calibrate
import test_merged_reviewer
from test_merged_reviewer import LIB_RULES, WIDEST_SMALL

MERGED_WHY = "one merged reviewer (small: %s, within the small band's 40 lines, 3 files)"


Helpers = test_merged_reviewer.MergedReviewerTest


class ReviewLogTest(unittest.TestCase):
    status, review, change, on_main = Helpers.status, Helpers.review, Helpers.change, Helpers.on_main
    assertAllowed, assertThree = Helpers.assertAllowed, Helpers.assertThree

    def setUp(self):
        self.repo = Repo(self, rules=LIB_RULES)
        self.repo.install()

    def log(self):
        path = os.path.join(self.repo.path, ".git", "review-slices", "review-log")
        return read_text(path).splitlines() if os.path.exists(path) else []

    def add_trailer(self):
        step = self.review()[1]
        self.repo.git(*shlex.split(step[step.index("`git -c"):].strip("`"))[1:])

    def test_status_logs_a_printed_load_once(self):
        self.change({"lib/a.py": "a\n"})
        self.assertAllowed("1 weighted line(s), 1 file(s) in 1 commit(s)")
        self.status()
        lines = self.log()
        self.assertEqual(len(lines), 1, lines)
        fields = lines[0].split("\t")
        self.assertEqual(fields[1:6], ["refs/heads/main", self.repo.out("rev-parse", "origin/main"),
                                       self.repo.out("rev-parse", "HEAD"), "important", "one merged reviewer"])

    def test_a_unit_keeps_the_highest_load_printed(self):
        self.change({"lib/a.py": "a\n"})
        self.status()
        fields = self.log()[0].split("\t")
        fields[5:7] = ["three reviewers", "large: as once printed"]
        with open(os.path.join(self.repo.path, ".git", "review-slices", "review-log"), "a", encoding="utf-8") as log:
            log.write("\t".join(fields) + "\n")
        review = self.review()[0]
        self.assertTrue(review.startswith("review: three reviewers (held: status printed it for this unit at "),
                        review)
        self.assertIn("(large: as once printed); now small: 1 weighted line(s)", review)

    def test_a_rewrite_inside_the_unit_is_three_reviewers(self):
        self.change({"lib/a.py": "a\n"})
        old = self.repo.out("rev-parse", "HEAD")
        self.status()
        self.repo.write("lib/a.py", "b\n")
        self.repo.git("commit", "-q", "-a", "--amend", "--no-edit")
        self.assertThree("history inside the unit was rewritten after status printed one merged reviewer at %s"
                         % old[:12])
        self.status()  # and it stays three
        self.assertTrue(self.log()[-1].endswith("\tthree reviewers\thistory inside the unit was rewritten after "
                                                "status printed one merged reviewer at %s" % old[:12]))

    def test_a_step_back_and_forth_is_never_held_at_three(self):  # review: the rewrite's three was held for good
        self.repo.git("switch", "-q", "--detach")
        self.change({"lib/a.py": "a\n"})
        tip = self.change({"lib/b.py": "b\n"})
        self.status()
        self.repo.git("switch", "-q", "--detach", "HEAD~1")
        self.assertIn("history inside the unit was rewritten", self.review()[0])
        self.repo.git("switch", "-q", "--detach", tip)
        self.assertAllowed("2 weighted line(s), 2 file(s) in 2 commit(s)")

    def test_the_trailer_closes_the_unit(self):
        self.change({"lib/a.py": "a\n" * 50})
        self.assertThree("large: 50 weighted line(s), 1 file(s) in 1 commit(s): over every band" + WIDEST_SMALL)
        self.add_trailer()  # an amend, but it starts the next unit
        self.change({"lib/b.py": "b\n"})
        review = self.review()[0]
        self.assertTrue(review.startswith("review: one merged reviewer (small: 1 weighted line(s)"), review)
        self.assertIn("since %s, a unit large on its own" % self.repo.out("rev-parse", "HEAD~1")[:12], review)
        self.assertNotIn("held", review)  # nothing is held from the closed unit (test_restart.py: the restart)
        self.assertNotIn("rewritten", review)

    def test_uncommitted_work_is_never_logged(self):
        self.repo.write("lib/a.py", "a\n")
        self.assertEqual(self.review()[0], "review: three reviewers (large: uncommitted work)")
        self.assertEqual(self.log(), [])
        self.repo.commit("change")
        self.assertAllowed("1 weighted line(s), 1 file(s) in 1 commit(s)")

    def test_a_log_line_it_cannot_read_is_three_reviewers(self):  # I2
        os.makedirs(os.path.join(self.repo.path, ".git", "review-slices"), exist_ok=True)
        with open(os.path.join(self.repo.path, ".git", "review-slices", "review-log"), "w", encoding="utf-8") as log:
            log.write("not a log line\n")
        self.change({"lib/a.py": "a\n"})
        review = self.review()[0]
        self.assertIn("review-log line 1 is not a review log line: fix or delete it", review)
        self.assertTrue(review.startswith("review: three reviewers ("), review)

    def test_a_base_branch_module_without_hold_logs_nothing(self):  # a 0.9.1 module
        module = re.sub(r"\n\ndef hold\(.*", "\n", read_text(MERGED), flags=re.S)
        self.assertNotIn("def hold", module)
        self.on_main({".githooks/merged_reviewer.py": module}, "a 0.9.1 measure")
        self.change({"lib/a.py": "a\n"})
        self.assertAllowed("1 weighted line(s), 1 file(s) in 1 commit(s)")
        self.assertEqual(self.log(), [])

    def test_branches_cut_from_one_base_commit_never_share_a_unit(self):  # plan review 1
        self.repo.git("switch", "-q", "-c", "big")
        self.change({"lib/a.py": "a\n" * 50})
        self.status()
        other = os.path.join(self.repo.tmp, "other")
        self.repo.git("worktree", "add", "-q", "-b", "small", other, "origin/main")
        self.repo.write("../other/lib/b.py", "b\n")
        self.repo.git("add", "-A", cwd=other)
        self.repo.git("commit", "-q", "-m", "small", cwd=other)
        done = self.repo.guard("status", cwd=other)
        self.assertIn("review: " + MERGED_WHY % "1 weighted line(s), 1 file(s) in 1 commit(s)", done.stdout)
        self.assertEqual(len(self.log()), 2)

    def test_calibrate_reports_the_logged_loads(self):
        self.change({"lib/a.py": "a\n"}, "logged")
        self.status()
        self.add_trailer()
        self.change({"lib/b.py": "b\n"}, "never logged", self.repo.trailer("important", self.repo.out(
            "rev-parse", "HEAD")))
        self.repo.git("checkout", "-q", "-b", "pr")
        self.change({"lib/c.py": "c\n"}, "pr part one")
        self.status()
        self.add_trailer()
        self.change({"lib/d.py": "d\n" * 50}, "pr part two")
        self.status()
        self.add_trailer()
        self.repo.git("checkout", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #1 from someone/pr", "pr")
        done = calibrate(self.repo, "--base", "main")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stdout, r"important\s+4 unit\(s\), 2 logged: one merged reviewer 1, adversarial \+ "
                                      r"conformance 0, three reviewers 1; held 0, history rewritten 0")

    def test_calibrate_never_takes_a_stacked_branch_s_unit_for_another(self):  # review: x's merged was y's load
        self.repo.git("switch", "-q", "-c", "x")
        self.change({"lib/x.py": "x\n"})
        self.status()
        self.repo.git("switch", "-q", "-c", "y")
        self.change({"lib/y.py": "y\n" * 60})
        self.status()
        self.add_trailer()
        self.change({"lib/z.py": "z\n"}, "after the last status", self.repo.trailer("important", self.repo.out(
            "rev-parse", "HEAD")))
        self.repo.git("switch", "-q", "main")
        self.repo.git("merge", "-q", "--ff-only", "y")
        done = calibrate(self.repo, "--base", "main")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stdout, r"important\s+4 unit\(s\), 1 logged: one merged reviewer 0, adversarial \+ "
                                      r"conformance 0, three reviewers 1;")


del Helpers  # its own tests run in test_merged_reviewer

if __name__ == "__main__":
    unittest.main()
