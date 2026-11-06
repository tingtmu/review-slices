"""`cross-check: on` (0.13.0): the base branch's REVIEW.md turns it on; `status` then prints the pair plus a
cross-check, `next:` counts it, and the review log keeps the load the pair with a `; cross-check` suffix."""
import os
import unittest

from support import Repo, read_text
import test_merged_reviewer
from test_merged_reviewer import GUARD, LIB_RULES

Helpers = test_merged_reviewer.MergedReviewerTest
PLUS = "review: adversarial + conformance, plus a cross-check (large: "


class CrossCheckTest(unittest.TestCase):
    status, review, change, on_main = Helpers.status, Helpers.review, Helpers.change, Helpers.on_main

    def setUp(self):
        self.repo = Repo(self, rules=LIB_RULES + "cross-check: on\n")
        self.repo.install()

    def log(self):
        return read_text(os.path.join(self.repo.path, ".git", "review-slices", "review-log")).splitlines()

    def test_a_pair_unit_adds_a_cross_check(self):
        self.change({"lib/a.py": "a\n" * 50})
        review, step = self.review()
        self.assertTrue(review.startswith(PLUS), review)
        self.assertNotIn("weight=", review)  # the log keeps it; the line stays readable
        self.assertIn("then after round one a cross-check: 1 fresh adversarial reviewer on the whole unit, of "
                      "another model family where one is available", step)
        self.assertIn("load: <the review: line>", step)
        fields = self.log()[-1].split("\t")
        self.assertEqual(fields[5], "adversarial + conformance")  # older guards still read the log
        self.assertTrue(fields[6].endswith("; weight=important/large/none; cross-check"), fields[6])

    def test_one_merged_reviewer_takes_no_cross_check(self):
        self.change({"lib/a.py": "a\n"})
        self.assertTrue(self.review()[0].startswith("review: one merged reviewer (small: "))
        self.assertNotIn("cross-check", self.log()[-1])

    def test_a_branch_cannot_turn_it_off_for_itself(self):  # the standing rules decide (I1)
        rules = read_text(os.path.join(self.repo.path, "REVIEW.md"))
        self.change({"REVIEW.md": rules.replace("cross-check: on", "cross-check: off"), "lib/a.py": "a\n" * 50})
        self.assertTrue(self.review()[0].startswith("review: adversarial + conformance, plus a cross-check (large: "
                                                    "REVIEW.md is a floor path"), self.review()[0])

    def test_a_branch_cannot_turn_it_on_for_the_base(self):  # nor does a branch's own line count before it lands
        self.repo = Repo(self, rules=LIB_RULES)
        self.repo.install()
        rules = read_text(os.path.join(self.repo.path, "REVIEW.md"))
        self.change({"REVIEW.md": rules.replace("```review-slices\n", "```review-slices\ncross-check: on\n"),
                     "lib/a.py": "a\n" * 50})
        self.assertTrue(self.review()[0].startswith("review: adversarial + conformance (large: "),
                        self.review()[0])


class ParseTest(unittest.TestCase):
    def parse(self, rules):
        return GUARD.parse_config("```review-slices\n%s```\n" % rules)

    def test_on_off_and_a_value_it_cannot_read_is_on(self):  # I2: fail closed
        self.assertIsNone(self.parse("test: x\n")["cross-check"])
        self.assertEqual(self.parse("cross-check: on\n")["cross-check"], "on")
        self.assertEqual(self.parse("cross-check: off\n")["cross-check"], "off")
        config = self.parse("cross-check: yes\n")
        self.assertEqual((config["cross-check"], config["errors"]),
                         ("on", ["line 1: cross-check: takes on or off; read as on"]))
        self.assertEqual(self.parse("cross-check: on\ncross-check: off\n")["cross-check"], "on")

    def test_unreadable_rules_keep_it_on(self):
        rules = GUARD.unreadable_rules("broken", "```review-slices\ncross-check: on\nnonsense\n```\n")
        self.assertEqual(rules["cross-check"], "on")

    def test_printed_load(self):
        self.assertEqual(GUARD.printed_load({"cross-check": "on"}, "one merged reviewer", "small: x; weight=a/b/c"),
                         ("one merged reviewer", "small: x"))
        self.assertEqual(GUARD.printed_load({"cross-check": "on"}, "adversarial + conformance",
                                            "held: at t (x; weight=a/b/c; cross-check); now y; weight=a/b/c; "
                                            "cross-check"),
                         (GUARD.CROSS_CHECKED, "held: at t (x); now y"))
        self.assertEqual(GUARD.printed_load(None, "adversarial + conformance", "y")[0], "adversarial + conformance")


del Helpers  # its own tests run in test_merged_reviewer

if __name__ == "__main__":
    unittest.main()
