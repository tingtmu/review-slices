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

    def test_comma_separated_globs_are_read_as_separate_globs(self):  # H3
        config = parse("critical: core/*, deploy/*\n")
        self.assertEqual(guard.path_level(config, "core/a.py")[0], "critical")
        self.assertEqual(guard.path_level(config, "deploy/prod.tf")[0], "critical")

    def test_a_hash_inside_a_command_is_kept(self):  # H4
        config = parse("test: make check URL=http://x/#frag\n")
        self.assertEqual(commands(config), ["make check URL=http://x/#frag"])

    def test_a_comment_line_is_skipped(self):
        config = parse("# one-way doors\ncritical: core/*\n")
        self.assertEqual(config["globs"], [("critical", "core/*")])

    def test_comma_separated_globs_draw_a_warning(self):
        self.assertTrue(parse("critical: core/*, deploy/*\n")["warnings"])

    def test_a_template_placeholder_is_a_lint_error_not_a_parse_error(self):
        config = parse("test: <the full offline test command>\ncritical: core/*\n")
        self.assertTrue(config["errors"])
        self.assertEqual(guard.path_level(config, "core/a.py")[0], "critical")

    def test_a_shell_redirect_is_not_a_placeholder(self):
        self.assertEqual(parse("test: sort < in.txt > out.txt\n")["errors"], [])

    def test_a_repeated_base_is_a_lint_error(self):
        config = parse("base: main\nbase: develop\n")
        self.assertTrue(config["errors"])
        self.assertEqual(config["base"], "develop")

    def test_every_test_line_is_kept_in_order(self):
        self.assertEqual(parse("test: ruff check .\ntest: pytest\n")["tests"], ["ruff check .", "pytest"])

    def test_review_md_and_the_guard_are_at_least_important(self):
        config = parse("trivial: *\n")
        self.assertEqual(guard.path_level(config, "REVIEW.md")[0], "important")
        self.assertEqual(guard.path_level(config, ".githooks/review_slices.py")[0], "important")
        self.assertEqual(guard.path_level(config, "docs/REVIEW.md")[0], "trivial")

    def test_unreadable_rules_put_every_path_at_critical(self):
        config = guard.unreadable_rules("broken")
        self.assertEqual(guard.path_level(config, "notes/n.md")[0], "critical")
        self.assertTrue(config["tests"])


if __name__ == "__main__":
    unittest.main()
