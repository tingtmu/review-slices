"""`copy-credit:`: in a commit that moves a file under the globs, text already there counts no lines (issue: archive
units measured as large)."""
import os
import re
import unittest

from support import Repo, read_text
from test_calibrate import calibrate
import test_merged_reviewer as base  # a module, not its classes: unittest would run them here again

GUARD, SIZER, LIB_RULES, WIDEST_SMALL = base.GUARD, base.SIZER, base.LIB_RULES, base.WIDEST_SMALL

CREDIT_RULES = LIB_RULES + "copy-credit: lib/specs/* lib/changes/*\n"
SPEC = "".join("req %d SHALL hold\n" % number for number in range(60)) + "old wording\n"
DELTA = "".join("new %d SHALL hold\n" % number for number in range(50)) + "old wording\n"  # its REMOVED entry
TASKS = "- [ ] 1 do it\n- [ ] 2 check it\n"


class CopyCreditTest(unittest.TestCase):
    rules = CREDIT_RULES
    setUp, status, review, change, on_main = (base.MergedReviewerTest.setUp, base.MergedReviewerTest.status,
                                              base.MergedReviewerTest.review, base.MergedReviewerTest.change,
                                              base.MergedReviewerTest.on_main)
    assertAllowed, assertCeiling = base.MergedReviewerTest.assertAllowed, base.MergedReviewerTest.assertCeiling

    def proposed(self):
        """Main holds a spec, a reviewed change's delta and tasks, and an older archive with the spec's text."""
        self.on_main({"lib/specs/s.md": SPEC, "lib/changes/x/delta.md": DELTA, "lib/changes/x/tasks.md": TASKS,
                      "lib/changes/archive/old/s.md": SPEC, "lib/other.txt": "outside text\n"}, "propose and apply")

    def archive(self, extra=None, spec_extra=""):
        """Move change x into the archive with its tasks ticked, and sync its delta into the spec."""
        os.makedirs(os.path.join(self.repo.path, "lib", "changes", "archive"), exist_ok=True)
        self.repo.git("mv", "lib/changes/x", "lib/changes/archive/x")
        spec = SPEC.replace("old wording\n", "") + DELTA.replace("old wording\n", "") + spec_extra
        return self.change(dict({"lib/changes/archive/x/tasks.md": TASKS.replace("[ ]", "[x]"),
                                 "lib/specs/s.md": spec}, **(extra or {})), "archive x")

    def test_an_archive_counts_only_its_new_text(self):
        self.proposed()
        self.archive()
        self.assertAllowed("4 weighted line(s), 0 file(s) in 1 commit(s); 1 exact rename(s) counted as 0 lines; "
                           "51 weighted line(s) credited as copies")

    def test_a_commit_that_moves_nothing_gets_no_credit(self):  # plan review r1 B1: a live spec edit
        self.proposed()
        self.change({"lib/specs/s.md": SPEC.replace("old wording\n", "") + DELTA}, "sync by hand")
        self.assertCeiling("large: 50 weighted line(s), 1 file(s) in 1 commit(s): over every band" + WIDEST_SMALL)

    def test_deleting_a_spec_file_the_archive_holds_counts_in_full(self):  # plan review r2 B1: a delete alone
        self.proposed()
        self.repo.remove("lib/specs/s.md")
        self.change({}, "drop the spec")
        self.assertCeiling("large: 61 weighted line(s), 1 file(s) in 1 commit(s): over every band" + WIDEST_SMALL)

    def test_a_path_outside_the_globs_and_text_from_outside_them_count(self):
        self.proposed()
        self.archive({"lib/a.py": "a\nb\n"}, spec_extra="outside text\n")
        self.assertAllowed("7 weighted line(s), 1 file(s) in 1 commit(s); 1 exact rename(s) counted as 0 lines; "
                           "51 weighted line(s) credited as copies")

    def test_a_floor_path_still_has_no_measure(self):
        self.proposed()
        self.archive({".githooks/extra.py": "e\n"})
        self.assertCeiling("large: .githooks/extra.py is a floor path")

    def test_text_written_and_archived_in_one_unit_counts_once(self):
        self.on_main({"lib/specs/s.md": SPEC}, "a spec")
        self.change({"lib/changes/x/delta.md": "".join("y %d\n" % number for number in range(20))}, "propose")
        os.makedirs(os.path.join(self.repo.path, "lib", "changes", "archive"))
        self.repo.git("mv", "lib/changes/x", "lib/changes/archive/x")
        self.change({"lib/specs/s.md": SPEC + "".join("y %d\n" % number for number in range(20))}, "archive")
        self.assertAllowed("20 weighted line(s), 1 file(s) in 2 commit(s); 1 exact rename(s) counted as 0 lines; "
                           "20 weighted line(s) credited as copies")

    def test_a_file_edited_in_three_commits_counts_once(self):  # plan review r2 F1: one file set across commits
        for number in range(3):
            self.change({"lib/a.py": "a\n" * (number + 1)}, "edit %d" % number)
        self.assertAllowed("3 weighted line(s), 1 file(s) in 3 commit(s)")


class NoCreditTest(unittest.TestCase):
    """The same archive under rules without the line, or with it only on the branch: measured as before."""
    rules = LIB_RULES
    setUp, status, review, change, on_main = CopyCreditTest.setUp, CopyCreditTest.status, CopyCreditTest.review, \
        CopyCreditTest.change, CopyCreditTest.on_main
    proposed, archive, assertCeiling = CopyCreditTest.proposed, CopyCreditTest.archive, CopyCreditTest.assertCeiling

    def test_without_the_line_an_archive_counts_in_full(self):
        self.proposed()
        self.archive()
        self.assertCeiling("large: 55 weighted line(s), 4 file(s) in 1 commit(s); 1 exact rename(s) counted as 0 "
                           "lines: over every band" + WIDEST_SMALL)

    def test_a_copy_credit_line_on_the_branch_never_counts(self):  # I1: only the standing rules
        self.proposed()
        self.change({"REVIEW.md": read_text(os.path.join(self.repo.path, "REVIEW.md")).replace(
            "important: lib/*\n", "important: lib/*\ncopy-credit: lib/specs/* lib/changes/*\n")}, "credit myself")
        self.archive()
        self.assertCeiling("large: REVIEW.md is a floor path")


class ParseTest(unittest.TestCase):
    def test_copy_credit_globs_add_up_and_default_to_none(self):
        parse = lambda rules: GUARD.parse_config("```review-slices\n%s```\n" % rules)  # noqa: E731
        config = parse("copy-credit: a/* b/*\ncopy-credit: c/*\n")
        self.assertEqual((config["copy-credit"], config["errors"]), (["a/*", "b/*", "c/*"], []))
        self.assertEqual(parse("test: true\n")["copy-credit"], [])
        self.assertEqual(SIZER.credited_size(GUARD, ("a/*",), []), (0, 0, False, 0, 0))


class CalibrateTest(unittest.TestCase):
    """calibrate.py sizes a unit with the same credit `status` gives it."""

    def test_calibrate_credits_an_archive_unit(self):
        repo = Repo(self, rules=CREDIT_RULES)
        test = CopyCreditTest()
        test.repo = repo
        test.proposed()
        test.archive()
        repo.git("commit", "-q", "--amend", "-m", "archive x", "-m", repo.trailer("important"))
        done = calibrate(repo, "--base", "main")
        self.assertEqual(done.returncode, 0, done.stderr)
        out = re.sub(r" \(\d+%\)", "", done.stdout)
        self.assertRegex(out, r"important\s+3 unit\(s\)\s+small 1\s+medium 0\s+large 2\s+->\s+one merged reviewer 1")


if __name__ == "__main__":
    unittest.main()
