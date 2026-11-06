"""`status` makes the printed review load binding where the agent decides (issue #26): `next:` counts the first
round's separate reviewers, says who may lower them and asks for the `load:` line before they start, and the `why`
of a large change names the limit crossed."""
import unittest

from support import Repo
from test_merged_reviewer import ENGINE_RULES, LIB_RULES, MergedReviewerTest

ASKED = "only with the user's go-ahead asked first"
LEAST = "the least: more where step 3 raises the level, step 5 escalates, or step 6 after a rebase; "
LOAD = "; before starting them, write in your message `load: <%s>; starting: <each reviewer, its lenses>`"
TRAILER = "; a second round as step 6 says; once they have reported, add the trailer to the last commit with `git -c "
THREE = ("3 separate reviewers (Standards, Spec, adversarial), each its own fresh agent", "fewer, or lenses combined "
         "into fewer reviewers, only with the user's go-ahead asked first, or step 4's exceptions (size was already "
         "counted)")


PAIR = ("2 separate reviewers (adversarial; conformance: the Standards and Spec lenses), each its own fresh agent",
        LEAST + "fewer, or the two combined into one, " + ASKED + ", or step 4's exceptions")


class NextStepTest(unittest.TestCase):
    """The first round's reviewers, counted and separate; a reduction is the user's call, asked first; the `load:`
    line written before they start (canary: Sonnet skipped SKILL.md's sentence 4/4); the trailer only once they
    have reported, still last on the line."""
    setUp, status, review, change = (MergedReviewerTest.setUp, MergedReviewerTest.status, MergedReviewerTest.review,
                                     MergedReviewerTest.change)
    rules = ENGINE_RULES + "medium: 100 lines, 6 files\n"

    def assertStep(self, files, level, reviewers, fewer):
        self.change(files)
        step = self.review()[1]
        start = self.repo.out("rev-parse", "--short=12", "origin/main")
        go_ahead = ", then the user's go-ahead for the one-way door" if level == "critical" else ""
        self.assertTrue(step.startswith("next: review at %s, first round on the whole unit: %s, on `git diff %s..HEAD`"
                                        "%s; %s%s%s" % (level, reviewers, start, go_ahead, fewer, LOAD % (
                                            "this load" if level == "simple" else "the review: line"), TRAILER)), step)
        self.assertTrue(step.endswith("--trailer \"Review: %s %s\"`" % (level, start)), step)
        return step

    def test_the_ceiling_pair_is_counted_and_only_the_user_lowers_it(self):  # I6; three before 0.13.0
        step = self.assertStep({"lib/a.py": "a\n" * 200}, "important", *PAIR)
        self.assertNotIn("merged", step)  # no lighter load named where the agent decides
        self.assertNotIn("cross-check", step)

    def test_a_critical_content_path_takes_the_pair_and_the_go_ahead_for_the_one_way_door(self):
        step = self.assertStep({"engine/golden/a.txt": "a\n"}, "critical", *PAIR)
        self.assertNotIn("merged", step)

    def test_three_reviewers_where_status_cannot_measure_are_counted(self):  # the fallback
        self.change({"lib/a.py": "a\n"})
        done = self.repo.guard("status", "origin/main")
        self.assertIn("review: three reviewers (a BASE was given, so the branch is not measured whole)", done.stdout)
        self.assertIn("first round on the whole unit: %s, on `git diff " % THREE[0], done.stdout)
        self.assertIn(THREE[1], done.stdout)

    def test_one_merged_reviewer_is_the_least(self):
        self.assertStep({"lib/a.py": "a\n"}, "important", "1 merged reviewer (the adversarial, Standards and Spec "
                        "lenses), its own fresh agent", LEAST + "none " + ASKED)

    def test_the_conformance_pair_is_two_separate_reviewers_and_the_least(self):
        self.assertStep({"lib/a.py": "a\n" * 41}, "important", *PAIR)
        self.repo.git("checkout", "-q", "-b", "other", "origin/main")
        self.assertStep({"engine/a.py": "a\n" * 12}, "critical", *PAIR)

    def test_simple_and_trivial(self):
        self.assertStep({"src/a.py": "a\n"}, "simple", "1-2 adversarial reviewers, each its own fresh agent",
                        "the least: more where step 3 raises the level; none " + ASKED)
        self.repo.git("checkout", "-q", "-b", "other", "origin/main")
        self.change({"notes/a.md": "a\n"})
        self.assertNotIn("review at", self.review()[1])


class WhyNamesTheLimitTest(unittest.TestCase):
    """A large change's `why` keeps "over every band" and names the widest band that is on, so a move or a docs
    archive reads as counted."""
    status, review, change = MergedReviewerTest.status, MergedReviewerTest.review, MergedReviewerTest.change
    size = "large: 50 weighted line(s), 1 file(s) in 1 commit(s): over every band "

    def assertWhy(self, rules, widest):
        self.repo = Repo(self, rules=LIB_RULES + rules)
        self.repo.install()
        self.change({"lib/a.py": "a\n" * 50})
        self.assertEqual(self.review()[0], "review: adversarial + conformance (%s(%s))" % (self.size, widest))

    def test_small_only(self):
        self.assertWhy("", "widest on: small, 40 lines, 3 files")

    def test_medium_on(self):
        self.assertWhy("small: 20 lines, 2 files\nmedium: 45 lines, 6 files\n", "widest on: medium, 45 lines, 6 files")

    def test_a_medium_band_narrower_than_small(self):  # review: the widest by its limits, not the last listed
        self.assertWhy("medium: 30 lines, 6 files\n", "widest on: small, 40 lines, 3 files")

    def test_every_band_off(self):
        self.assertWhy("small: off\n", "every band is off")


if __name__ == "__main__":
    unittest.main()
