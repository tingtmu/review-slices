"""`status`: the measure starts over after a unit large on its own that the review log shows went to three."""
import os
import types
import unittest

from support import Repo, read_text
import test_merged_reviewer
from test_merged_reviewer import ENGINE_RULES, LIB_RULES, SIZER
import test_review_log

Helpers = test_merged_reviewer.MergedReviewerTest
SINCE = " since %s, a unit large on its own"


class RestartTest(unittest.TestCase):
    rules = LIB_RULES
    status, review, change, other_work_on_main = Helpers.status, Helpers.review, Helpers.change, \
        Helpers.other_work_on_main
    assertAllowed, assertThree = Helpers.assertAllowed, Helpers.assertThree
    log, add_trailer = test_review_log.ReviewLogTest.log, test_review_log.ReviewLogTest.add_trailer

    def setUp(self):
        self.repo = Repo(self, rules=self.rules)
        self.repo.install()

    def amend_trailer(self, level="important"):
        """Add the trailer to HEAD without running `status` first, for the unit `status` printed last."""
        start = self.log()[-1].split("\t")[2]
        self.repo.git("-c", "trailer.ifexists=replace", "commit", "--amend", "--only", "--no-edit", "--trailer",
                      "Review: %s %s" % (level, start[:12]))

    def large_unit(self, files=None):
        """A 50-line unit `status` sends to three reviewers, then a 1-line fix, then the trailer after `status`."""
        self.change(files or {"lib/a.py": "a\n" * 50})
        self.assertIn("review: three reviewers (large: ", self.review()[0])
        self.change({"lib/a.py": "a\n" * 51}, "fix")
        self.add_trailer()
        return self.repo.out("rev-parse", "HEAD")

    def assertRestarted(self, trailer, size="1 weighted line(s), 1 file(s) in 1 commit(s)"):
        self.assertAllowed(size + SINCE % trailer[:12])

    def test_a_small_fix_after_a_large_reviewed_unit_takes_one_merged_reviewer(self):
        trailer = self.large_unit()
        self.change({"lib/b.py": "b\n"})
        self.assertRestarted(trailer)

    def test_status_before_the_fixes_only_still_restarts(self):  # the logged head is an ancestor of the trailer
        self.change({"lib/a.py": "a\n" * 50})
        self.status()
        self.change({"lib/a.py": "a\n" * 51}, "fix")
        self.amend_trailer()
        trailer = self.repo.out("rev-parse", "HEAD")
        self.change({"lib/b.py": "b\n"})
        self.assertRestarted(trailer)

    def test_a_restart_survives_the_push(self):
        self.repo.git("checkout", "-q", "-b", "feature")
        trailer = self.large_unit()
        self.repo.git("push", "-q", "--no-verify", "-u", "origin", "feature")
        self.change({"lib/b.py": "b\n"})
        self.assertRestarted(trailer)

    def test_a_trivial_commit_pushed_first_still_restarts(self):  # status logs it as the unit's start
        self.repo.git("checkout", "-q", "-b", "feature")
        self.change({"notes/a.txt": "typo\n"})
        self.repo.git("push", "-q", "--no-verify", "-u", "origin", "feature")
        trailer = self.large_unit()
        self.change({"lib/b.py": "b\n"})
        self.assertRestarted(trailer)

    def test_a_large_unit_with_a_floor_path_restarts_and_a_later_floor_path_is_three(self):  # owner's call
        trailer = self.large_unit({"lib/a.py": "a\n" * 50, "REVIEW.md": read_text(
            os.path.join(self.repo.path, "REVIEW.md")) + "\nA note.\n"})
        self.change({"lib/b.py": "b\n"})
        self.assertRestarted(trailer)
        self.change({".githooks/x.txt": "x\n"})
        self.assertThree("large: .githooks/x.txt is a floor path")

    def test_slices_that_add_up_never_restart(self):
        for name in ("a", "b"):
            self.change({"lib/%s.py" % name: "x\n" * 30})
            self.status()
            self.amend_trailer()
        self.change({"lib/c.py": "c\n"})
        self.assertThree("large: 61 weighted line(s), 3 file(s) in 3 commit(s): over every band")

    def test_a_unit_grown_past_the_band_after_a_lighter_load_never_restarts(self):  # plan review 1 Blocker
        self.change({"lib/a.py": "a\n" * 35})
        self.assertAllowed("35 weighted line(s), 1 file(s) in 1 commit(s)")
        self.change({"lib/b.py": "b\n" * 10}, "a nit fix")
        self.amend_trailer()
        self.change({"lib/c.py": "c\n"})
        self.assertThree("large: 46 weighted line(s), 3 file(s) in 3 commit(s): over every band")

    def test_three_printed_while_the_unit_was_small_is_no_evidence(self):  # plan review 2
        self.change({"core/x.py": "x\n"})
        self.assertIn("review: three reviewers (", self.review()[0])
        self.change({"lib/a.py": "a\n" * 50}, "grown with no status")
        self.amend_trailer("critical")
        self.change({"lib/b.py": "b\n"})
        self.assertThree("large: 52 weighted line(s), 3 file(s) in 3 commit(s): over every band")

    def test_a_trailer_below_the_unit_s_level_never_restarts(self):
        self.change({"lib/a.py": "a\n" * 50})
        self.status()
        self.amend_trailer("simple")
        self.change({"lib/b.py": "b\n"})
        self.assertThree("large: 51 weighted line(s), 2 file(s) in 2 commit(s): over every band")

    def test_churn_never_restarts(self):  # the net diff, not the commits summed
        self.change({"lib/a.py": "a\n" * 50})
        self.status()
        self.repo.remove("lib/a.py")
        self.change({"lib/keep.py": "k\n"}, "take it back")
        self.add_trailer()
        self.change({"lib/b.py": "b\n"})
        self.assertThree("large: 102 weighted line(s), 3 file(s) in 3 commit(s): over every band")

    def test_a_pure_move_large_by_files_never_restarts(self):  # plan review 1: nothing for the reviewers to read
        for name in "abcd":
            self.repo.write("lib/%s.py" % name, "%s\n" % name)
        self.repo.commit("on main", trailer=self.repo.trailer("important"))
        self.repo.git("push", "-q", "--no-verify", "origin", "main")
        for name in "abcd":
            self.repo.git("mv", "lib/%s.py" % name, "lib/moved_%s.py" % name)
        self.change({}, "move")
        self.assertIn("review: three reviewers (large: ", self.review()[0])
        self.add_trailer()
        self.change({"lib/e.py": "e\n"})
        self.assertIn("review: three reviewers (large: 1 weighted line(s), 5 file(s)", self.review()[0])

    def test_without_the_log_line_there_is_no_restart(self):  # another clone, a rebase, a deleted log
        self.large_unit()
        os.remove(os.path.join(self.repo.path, ".git", "review-slices", "review-log"))
        self.change({"lib/b.py": "b\n"})
        self.assertThree("large: 52 weighted line(s), 2 file(s) in 3 commit(s): over every band")

    def test_another_branch_s_log_line_is_no_evidence(self):
        self.large_unit()
        self.repo.git("switch", "-q", "-c", "copy")
        self.change({"lib/b.py": "b\n"})
        self.assertThree("large: 52 weighted line(s), 2 file(s) in 3 commit(s): over every band")

    def test_a_unit_with_a_merge_never_restarts(self):
        self.other_work_on_main()
        self.repo.git("merge", "-q", "--no-edit", "origin/main")
        self.large_unit()
        self.change({"lib/b.py": "b\n"})
        self.assertIn("review: three reviewers (large: ", self.review()[0])

    def test_a_merge_of_main_in_an_earlier_unit_leaves_main_s_work_out(self):
        self.other_work_on_main()
        self.repo.git("merge", "-q", "--no-edit", "origin/main")
        self.repo.git("commit", "-q", "--amend", "--no-edit", "--trailer", self.repo.trailer("important"))
        trailer = self.large_unit()
        self.change({"lib/b.py": "b\n"})
        self.assertRestarted(trailer)

    def test_a_restart_never_lowers_a_held_load(self):
        trailer = self.large_unit()
        self.change({"lib/b.py": "b\n"})
        fields = self.log()[-1].split("\t") if self.status() else None
        fields[5:7] = ["three reviewers", "large: as once printed"]
        with open(os.path.join(self.repo.path, ".git", "review-slices", "review-log"), "a", encoding="utf-8") as log:
            log.write("\t".join(fields) + "\n")
        review = self.review()[0]
        self.assertTrue(review.startswith("review: three reviewers (held: "), review)
        self.assertIn("now small: 1 weighted line(s), 1 file(s) in 1 commit(s)" + SINCE % trailer[:12], review)

    def test_a_guard_without_the_helpers_never_restarts(self):  # mixed versions: no restart, never an error
        guard = types.SimpleNamespace(git=lambda *args, **kwargs: None)
        self.assertEqual(SIZER.restarts(guard, {"small": (40, 3)}, ["0" * 40], ()), [])

    def test_no_standing_rules_never_restart(self):  # a branch on its own REVIEW.md (I1)
        self.assertEqual(SIZER.restarts(None, None, ["0" * 40], ()), [])


class CriticalRestartTest(unittest.TestCase):
    rules = ENGINE_RULES + "medium: 100 lines, 6 files\n"
    setUp, status, review, change = RestartTest.setUp, RestartTest.status, RestartTest.review, RestartTest.change
    log, add_trailer = RestartTest.log, RestartTest.add_trailer

    def test_a_small_code_fix_after_a_large_critical_unit_takes_the_pair(self):
        self.change({"engine/a.py": "a\n" * 150})
        self.assertIn("review: three reviewers (large: ", self.review()[0])
        self.add_trailer()
        trailer = self.repo.out("rev-parse", "HEAD")
        self.change({"engine/b.py": "b\n" * 2})
        self.assertEqual(self.review()[0], "review: adversarial + conformance (small: 2 weighted line(s), 1 file(s) "
                                           "in 1 commit(s)%s, within the small band's 40 lines, 3 files)"
                                           % (SINCE % trailer[:12]))

    def test_a_medium_critical_unit_never_restarts(self):  # three, but within a band's line limit
        self.change({"engine/a.py": "a\n" * 60})
        self.assertIn("review: three reviewers (medium: ", self.review()[0])
        self.add_trailer()
        self.change({"engine/b.py": "b\n" * 2})
        self.assertIn("review: three reviewers (medium: 62 weighted line(s)", self.review()[0])


if __name__ == "__main__":
    unittest.main()
