"""This repo uses its own skill: its guard copy and rules must stay in step with the skill."""
import os
import unittest

from support import GUARD, ROOT, load_guard


class DogfoodTest(unittest.TestCase):
    def test_the_repo_guard_copy_matches_the_skill(self):
        with open(GUARD, encoding="utf-8") as skill, \
                open(os.path.join(ROOT, ".githooks", "review_slices.py"), encoding="utf-8") as copy:
            self.assertEqual(copy.read(), skill.read(), "copy skills/review-slices/scripts/review_slices.py to .githooks/ and commit it")

    def test_the_repo_rules_parse(self):
        with open(os.path.join(ROOT, "REVIEW.md"), encoding="utf-8") as handle:
            load_guard().parse_config(handle.read())


if __name__ == "__main__":
    unittest.main()
