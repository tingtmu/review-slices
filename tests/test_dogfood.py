"""This repo uses its own skill: its guard copy and rules must stay in step with the skill."""
import os
import unittest

from support import GUARD, ROOT, SCRIPTS, load_guard


class DogfoodTest(unittest.TestCase):
    def test_the_repo_guard_copy_matches_the_skill(self):
        with open(GUARD, encoding="utf-8") as skill, \
                open(os.path.join(ROOT, ".githooks", "review_slices.py"), encoding="utf-8") as copy:
            self.assertEqual(copy.read(), skill.read(),
                             "copy skills/review-slices/scripts/review_slices.py to .githooks/ and commit it")

    def test_the_repo_agent_hook_copy_matches_the_skill(self):
        with open(os.path.join(SCRIPTS, "agent_hook.py"), encoding="utf-8") as skill, \
                open(os.path.join(ROOT, ".githooks", "agent_hook.py"), encoding="utf-8") as copy:
            self.assertEqual(copy.read(), skill.read(), "copy skills/review-slices/scripts/agent_hook.py to .githooks/")

    def test_the_repo_secret_scan_copy_matches_the_skill(self):
        with open(os.path.join(SCRIPTS, "secret_scan.py"), encoding="utf-8") as skill, \
                open(os.path.join(ROOT, ".githooks", "secret_scan.py"), encoding="utf-8") as copy:
            self.assertEqual(copy.read(), skill.read(), "copy skills/review-slices/scripts/secret_scan.py to .githooks/")

    def test_the_repo_merged_reviewer_copy_matches_the_skill(self):
        with open(os.path.join(SCRIPTS, "merged_reviewer.py"), encoding="utf-8") as skill, \
                open(os.path.join(ROOT, ".githooks", "merged_reviewer.py"), encoding="utf-8") as copy:
            self.assertEqual(copy.read(), skill.read(), "copy skills/review-slices/scripts/merged_reviewer.py to "
                                                        ".githooks/")

    def test_the_repo_rules_parse(self):
        with open(os.path.join(ROOT, "REVIEW.md"), encoding="utf-8") as handle:
            load_guard().parse_config(handle.read())


if __name__ == "__main__":
    unittest.main()
