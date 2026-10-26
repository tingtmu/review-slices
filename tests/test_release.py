"""A release names one version everywhere: every script's VERSION and "(skill version x)", and README's Versions."""
import glob
import os
import re
import unittest

from support import ROOT, SCRIPTS, load_guard, read_text

VERSION_LINE = re.compile(r'^VERSION = "([^"]*)"', re.M)
SKILL_VERSION = re.compile(r"\(skill version ([^)]*)\)")


class ReleaseTest(unittest.TestCase):
    def test_every_script_names_the_guard_s_version(self):
        version = load_guard().VERSION
        found = {}
        paths = glob.glob(os.path.join(SCRIPTS, "*.py")) + glob.glob(os.path.join(ROOT, ".githooks", "*.py"))
        for path in sorted(paths):
            text = read_text(path)
            for match in VERSION_LINE.findall(text) + SKILL_VERSION.findall(text):
                found.setdefault(match, []).append(os.path.relpath(path, ROOT))
        self.assertEqual(list(found), [version], found)
        self.assertIn(os.path.join(".githooks", "run_suite.py"), found[version])  # unreleased since PR #8

    def test_readme_versions_name_this_version(self):
        readme = read_text(os.path.join(ROOT, "README.md"))
        versions = readme.split("\n## Versions\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("\n`%s`: " % load_guard().VERSION, versions)


if __name__ == "__main__":
    unittest.main()
