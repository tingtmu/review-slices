"""Parsing the review-slices block in REVIEW.md, and matching paths to levels."""
import unittest

from support import load_guard

guard = load_guard()


def parse(block):
    return guard.parse_config("```review-slices\n%s```\n" % block)


def commands(config):
    return config.get("tests") or [config["test"]]


class ParseTest(unittest.TestCase):
    def test_a_path_takes_the_highest_matching_level(self):
        config = parse("important: core/a.py\ncritical: core/*\n")
        self.assertEqual(guard.path_level(config, "core/a.py")[0], "critical")

    def test_an_unmatched_path_takes_the_default(self):
        config = parse("default: important\ncritical: core/*\n")
        self.assertEqual(guard.path_level(config, "src/x.py")[0], "important")

    def test_star_matches_slashes(self):
        config = parse("critical: engine/*/approval.py\n")
        self.assertEqual(guard.path_level(config, "engine/src/deep/approval.py")[0], "critical")

    def test_an_unknown_key_is_an_error(self):
        with self.assertRaises(guard.GuardError):
            parse("Critical: core/*\n")

    def test_a_trailing_comment_is_dropped(self):
        config = parse("critical: core/*   # one-way doors\n")
        self.assertEqual(guard.path_level(config, "core/a.py")[0], "critical")

    def test_a_missing_block_is_an_error(self):
        with self.assertRaises(guard.GuardError):
            guard.parse_config("# Review rules\n\nno block here\n")

    @unittest.expectedFailure  # H3
    def test_comma_separated_globs_are_read_as_separate_globs(self):
        config = parse("critical: core/*, deploy/*\n")
        self.assertEqual(guard.path_level(config, "core/a.py")[0], "critical")
        self.assertEqual(guard.path_level(config, "deploy/prod.tf")[0], "critical")

    @unittest.expectedFailure  # H4
    def test_a_hash_inside_a_command_is_kept(self):
        config = parse("test: make check URL=http://x/#frag\n")
        self.assertEqual(commands(config), ["make check URL=http://x/#frag"])


if __name__ == "__main__":
    unittest.main()
