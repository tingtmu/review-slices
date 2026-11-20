"""This repo uses its own skill: its guard copy and rules must stay in step with the skill."""
import os
import re
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

    def test_the_repo_suite_wrapper_copy_matches_the_skill(self):
        with open(os.path.join(SCRIPTS, "run_suite.py"), encoding="utf-8") as skill, \
                open(os.path.join(ROOT, ".githooks", "run_suite.py"), encoding="utf-8") as copy:
            self.assertEqual(copy.read(), skill.read(), "copy skills/review-slices/scripts/run_suite.py to .githooks/")

    def test_the_repo_rules_parse(self):
        with open(os.path.join(ROOT, "REVIEW.md"), encoding="utf-8") as handle:
            load_guard().parse_config(handle.read())


# Every file ruff 0.17.5 reads here (`ruff check --show-settings .`, file_resolver.include, less *.md, which it
# lints only in preview): an edit to any of them must trigger the lint hook.
RUFF_INPUTS = ("a.py", "skills/x/a.py", "a.pyi", "sub/a.ipynb", "ruff.toml", ".ruff.toml", "sub/ruff.toml",
               "sub/.ruff.toml", "pyproject.toml", "sub/pyproject.toml", ".pre-commit-config.yaml")
HOOK_FILTERS = ("exclude", "types", "types_or", "exclude_types")


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _scalar(value):
    """A YAML scalar this reader understands: plain, or single-quoted with '' for a quote. Anything else fails."""
    if len(value) >= 2 and value[0] == value[-1] == "'":
        inner = value[1:-1]
        if "'" in inner.replace("''", ""):
            raise AssertionError("cannot read the YAML value %r" % value)
        return inner.replace("''", "'")
    if not value or value[0] in "'\"|>[{&*!%@`" or " #" in value:
        raise AssertionError("cannot read the YAML value %r" % value)
    return value


def read_hook(text, hook_id):
    """The top-level keys and one hook's keys of a .pre-commit-config.yaml, without a YAML library. Fails on
    any shape it does not read, so a filter it cannot see fails the test instead of passing it."""
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    top = [line.split(":", 1)[0] for line in lines if _indent(line) == 0]
    starts = [i for i, line in enumerate(lines) if line.strip() == "- id: " + hook_id]
    if len(starts) != 1:
        raise AssertionError("expected one hook %r, found %d" % (hook_id, len(starts)))
    key_indent = _indent(lines[starts[0]]) + 2
    hook = {"id": hook_id}
    for line in lines[starts[0] + 1:]:
        if _indent(line) < key_indent:
            break
        key, sep, value = line.strip().partition(":")
        if _indent(line) > key_indent or not sep or not value.strip():
            raise AssertionError("cannot read the hook line %r" % line)
        hook[key] = _scalar(value.strip())
    return top, hook


class HookTriggerTest(unittest.TestCase):
    """The lint hook must run on every file that configures ruff or the hook, and run what the suite runs."""

    def setUp(self):
        with open(os.path.join(ROOT, ".pre-commit-config.yaml"), encoding="utf-8") as handle:
            self.top, self.hook = read_hook(handle.read(), "ruff-check")

    def test_the_ruff_hook_runs_on_every_file_that_configures_it(self):
        self.assertEqual(self.top, ["repos"], "a top-level filter (files:, exclude:) applies to every hook")
        self.assertEqual([key for key in HOOK_FILTERS if key in self.hook], [],
                         "this test models only the hook's files: regex")
        pattern = self.hook.get("files", "")
        missed = [path for path in RUFF_INPUTS if not re.search(pattern, path)]
        self.assertEqual(missed, [], "the hook's files: regex skips these")

    def test_the_ruff_hook_runs_a_suite_line(self):
        with open(os.path.join(ROOT, "REVIEW.md"), encoding="utf-8") as handle:
            tests = load_guard().parse_config(handle.read())["tests"]
        self.assertIn(self.hook.get("entry"), tests)


if __name__ == "__main__":
    unittest.main()
