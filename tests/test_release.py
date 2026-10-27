"""A release names one version everywhere: every script's VERSION and "(skill version x)", and CHANGELOG.md."""
import glob
import os
import re
import subprocess
import sys
import unittest

from support import ENV, ROOT, SCRIPTS, Repo, load_guard, read_text

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

    def test_changelog_names_this_version(self):
        changelog = read_text(os.path.join(ROOT, "CHANGELOG.md"))
        self.assertRegex(changelog, r"\n## %s \(\d{4}-\d\d-\d\d\)\n" % re.escape(load_guard().VERSION))


CHECK = os.path.join(ROOT, "tests", "release_check.py")
FAKE_GUARD = 'VERSION = "%s"\n"""The guard (skill version %s)."""\n'


class ReleaseCheckTest(unittest.TestCase):
    """tests/release_check.py: REVIEW.md's version-swap check, run against a throwaway release."""

    def setUp(self):
        self.repo = Repo(self, rules=None, guard=False)
        self.repo.write("skills/review-slices/scripts/review_slices.py", FAKE_GUARD % ("1.2.0", "1.2.0"))
        self.repo.write(".githooks/helper.py", 'VERSION = "1.2.0"\nVERSION = "1.2.0" # not the line form\n')
        self.repo.write("docs/notes.md", "keep\n")
        self.base = self.repo.commit("base")

    def release(self, new="1.10.0"):
        self.repo.write("skills/review-slices/scripts/review_slices.py", FAKE_GUARD % (new, new))
        self.repo.write(".githooks/helper.py", 'VERSION = "%s"\nVERSION = "1.2.0" # not the line form\n' % new)
        self.repo.write("README.md", "start\nsee CHANGELOG.md\n")
        self.repo.write("CHANGELOG.md", "## %s\n\nnotes\n" % new)

    def check(self, *args, stdin=None, cwd=None):
        command = (sys.executable, "-I", "-" if stdin else CHECK, "--base", self.base) + args
        return subprocess.run(command, cwd=cwd or self.repo.path, capture_output=True, text=True, input=stdin,
                              env=ENV)

    def problems(self, cwd=None):
        done = self.check(cwd=cwd)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        return done.stdout.splitlines()

    def test_a_version_swap_passes_from_stdin_as_review_md_runs_it(self):
        self.release()
        self.repo.commit("release")
        done = self.check(stdin=read_text(CHECK))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("OK, 1.2.0 -> 1.10.0", done.stdout)

    def test_any_other_change_outside_readme_differs(self):
        self.release()
        self.repo.write("docs/notes.md", "keep \n")
        self.repo.commit("release")
        self.assertEqual(self.problems(), ["differs: docs/notes.md"])

    def test_a_file_left_on_the_old_version_differs(self):
        self.release()
        self.repo.write(".githooks/helper.py", read_text(os.path.join(self.repo.path, ".githooks/helper.py"))
                        .replace('"1.10.0"', '"1.2.0"'))
        self.repo.commit("release")
        self.assertEqual(self.problems(), ["still 1.2.0: .githooks/helper.py:1"])

    def test_added_deleted_and_mode_changed_files_are_listed(self):
        self.release()
        self.repo.write("new.txt")
        self.repo.remove("docs/notes.md")
        os.chmod(os.path.join(self.repo.path, ".githooks/helper.py"), 0o755)
        self.repo.commit("release")
        found = self.problems()
        self.assertIn("differs: new.txt", found)
        self.assertIn("differs: docs/notes.md", found)
        self.assertIn("entry: A 000000 -> 100644 new.txt", found)
        self.assertIn("entry: D 100644 -> 000000 docs/notes.md", found)
        self.assertIn("entry: M 100644 -> 100755 .githooks/helper.py", found)

    def test_a_subdirectory_still_checks_the_whole_tree(self):
        self.release()
        self.repo.write("docs/README.md", "not the root README\n")
        self.repo.write("docs/CHANGELOG.md", "not the root CHANGELOG\n")
        self.repo.write(".githooks/helper.py", read_text(os.path.join(self.repo.path, ".githooks/helper.py"))
                        .replace('"1.10.0"', '"1.2.0"'))
        self.repo.commit("release")
        found = self.problems(cwd=os.path.join(self.repo.path, "docs"))
        self.assertIn("differs: docs/README.md", found)
        self.assertIn("differs: docs/CHANGELOG.md", found)
        self.assertIn("still 1.2.0: .githooks/helper.py:1", found)

    def test_the_version_must_rise(self):
        self.release(new="1.1.9")
        self.repo.commit("release")
        self.assertEqual(self.problems(), ["version: 1.1.9 is not higher than the base's 1.2.0"])

    def test_a_bad_base_exits_2(self):
        done = subprocess.run((sys.executable, "-I", CHECK, "--base", "no-such-commit"), cwd=self.repo.path,
                              capture_output=True, text=True, env=ENV)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("release check: git rev-parse", done.stderr)


if __name__ == "__main__":
    unittest.main()
