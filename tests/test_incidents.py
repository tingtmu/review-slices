"""The incident log report: parsing docs/INCIDENTS.md, counting per slice, and checking that plugs still exist."""
import datetime
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import ENV, ROOT, SCRIPTS

INCIDENTS = os.path.join(SCRIPTS, "incidents.py")
TODAY = datetime.date.today()


def load_incidents():
    spec = importlib.util.spec_from_file_location("incidents", INCIDENTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


incidents = load_incidents()


def entry(number, title="A failure", status="open", days=0, kind="defect", slice_text="2 Review", plug="none yet",
          recurrences="none"):
    date = (TODAY - datetime.timedelta(days=days)).isoformat()
    return ("## I%d. %s\n\n- **Date / kind / status:** %s · %s · %s\n- **What happened:** it broke.\n"
            "- **Slice that should have caught it:** %s. Why it did not: no one looked.\n"
            "- **Failure class:** a failure\n- **Fix:** not yet\n- **Plug:** %s\n- **Recurrences:** %s\n\n"
            % (number, title, date, kind, status, slice_text, plug, recurrences))


class LogRepo:
    """A throwaway git repo holding docs/INCIDENTS.md, REVIEW.md and the files plugs point at."""

    def __init__(self, test, *entries):
        self.path = tempfile.mkdtemp(prefix="review-slices-incidents-")
        test.addCleanup(shutil.rmtree, self.path, True)
        subprocess.run(("git", "init", "-q", self.path), check=True, capture_output=True, env=ENV)
        self.write("REVIEW.md", "# Rules\n\n## Failure looks like\n\n- The guard trusts input the change\n"
                                "  itself controls, sometimes\n")
        self.write("tests/test_a.py", "import unittest\n\n\ndef test_top():\n    pass\n\n\n"
                                      "class ATest(unittest.TestCase):\n    def test_in_class(self):\n        pass\n")
        self.write(".githooks/pre-push", "#!/bin/sh\n")
        self.write("docs/INCIDENTS.md", "# Incidents\n\nIntro text.\n\n" + "".join(entries))

    def write(self, relpath, text):
        full = os.path.join(self.path, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(text)

    def run(self, *args, cwd=None):
        return subprocess.run((sys.executable, INCIDENTS) + args, cwd=cwd or self.path, capture_output=True,
                              text=True, env=ENV)


class ParseTest(unittest.TestCase):
    def test_wrapped_plug_items_with_free_text_are_read(self):
        plugs, unread = incidents.parse_plug(
            "test tests/a.py::test_one,\n  test tests/b.py::BTest::test_two (expected failures until fixed), "
            "test tests/c.py::CTest.test_three, guard .githooks/pre-push, rule REVIEW.md \"a line, with a comma\"")
        self.assertEqual(unread, [])
        self.assertEqual([(plug.kind, plug.path, plug.names) for plug in plugs], [
            ("test", "tests/a.py", ["test_one"]), ("test", "tests/b.py", ["BTest", "test_two"]),
            ("test", "tests/c.py", ["CTest", "test_three"]), ("guard", ".githooks/pre-push", []),
            ("rule", "REVIEW.md", ["a line, with a comma"])])

    def test_an_item_that_is_no_plug_is_reported_not_dropped(self):
        plugs, unread = incidents.parse_plug("test tests/a.py::test_one, tests in tests/b.py marked H3")
        self.assertEqual(len(plugs), 1)
        self.assertEqual(unread, ["tests in tests/b.py marked H3"])

    def test_none_yet_is_no_plug(self):
        self.assertEqual(incidents.parse_plug("none yet (a test arrives with the installer)"), ([], []))

    def test_a_slice_is_found_by_number_or_by_name(self):
        for text, expected in (("2 Review. Why it did not: x", "2 Review"), ("Offline tests. Why it did not: x",
                               "1 Offline suite"), ("Slice 4. Why it did not: x", "4 Acceptance"),
                               ("Go-ahead", "3 Go-ahead"), ("shown output", "0 Shown output"), ("CI", "unknown")):
            self.assertEqual(incidents.slice_of(text), expected, text)

    def test_wrapped_bullets_are_joined(self):
        (_ident, _title, fields), = incidents.split_entries(
            "## I1. T\n\n- **Plug:** test a.py::f,\n  test b.py::g\n- **Recurrences:** none\n")
        self.assertEqual(fields["plug"], "test a.py::f, test b.py::g")

    def test_template_entries_are_skipped(self):
        with open(os.path.join(ROOT, "skills", "review-slices", "templates", "INCIDENTS.md"), encoding="utf-8") as h:
            found, problems, _notes, skipped = incidents.parse_log(h.read())
        self.assertEqual((found, problems, skipped), ([], [], 1))

    def test_a_bad_date_line_is_a_problem(self):
        text = entry(1).replace("· open", "open")
        found, problems, _notes, _skipped = incidents.parse_log(text)
        self.assertEqual(found, [])
        self.assertIn("I1: the date / kind / status line", problems[0])

    def test_an_id_used_twice_is_a_problem(self):
        _found, problems, _notes, _skipped = incidents.parse_log(entry(1) + entry(1))
        self.assertEqual(problems, ["I1 appears twice; give each incident its own id"])


class ReportTest(unittest.TestCase):
    def test_open_incidents_show_their_age_and_plug(self):
        done = LogRepo(self, entry(1, "Old one", days=3, plug="guard .githooks/pre-push"), entry(2, status="plugged",
                       plug="guard .githooks/pre-push")).run()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("2 incident(s), 1 open, 1 plugged", done.stdout)
        self.assertIn("  I1. Old one (3 days)\n      plug: guard .githooks/pre-push\n", done.stdout)
        self.assertNotIn("I2.", done.stdout)

    def test_counts_per_slice(self):
        done = LogRepo(self, entry(1, slice_text="2 Review"), entry(2, slice_text="Offline tests"),
                       entry(3, slice_text="1 Offline suite")).run()
        self.assertIn("  1 Offline suite  2\n  2 Review         1\n", done.stdout)

    def test_recurrences_are_listed_as_a_weak_plug(self):
        done = LogRepo(self, entry(1, recurrences="I1 again on 2026-10-01: the rule was not read"), entry(2)).run()
        self.assertIn("recurrences (each means a weak plug):\n  I1. A failure: I1 again on 2026-10-01", done.stdout)
        self.assertNotIn("  I2.", done.stdout.split("recurrences")[1])

    def test_existing_plugs_pass_the_check(self):
        plug = ("test tests/test_a.py::test_top, test tests/test_a.py::test_in_class, test tests/test_a.py::ATest::"
                "test_in_class,\n  test tests/test_a.py::ATest.test_in_class (expected failures until fixed),\n"
                "  guard .githooks/pre-push, rule REVIEW.md \"The guard trusts input the change itself controls\"")
        done = LogRepo(self, entry(1, status="plugged", plug=plug)).run("--check")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue(done.stdout.endswith("incidents: ok\n"), done.stdout)

    def test_a_missing_plug_reopens_the_hole(self):
        for plug in ("test tests/test_a.py::test_gone", "test tests/test_a.py::ATest::test_top",
                     "test tests/missing.py::test_top", "guard .githooks/gone", "rule REVIEW.md \"not there\""):
            repo = LogRepo(self, entry(1, status="plugged", plug=plug))
            checked, reported = repo.run("--check"), repo.run()
            self.assertEqual(checked.returncode, 1, plug)
            self.assertIn("the hole is open again; reopen the incident", checked.stdout)
            self.assertEqual(reported.returncode, 0, plug)

    def test_open_incidents_plugs_are_not_checked(self):
        done = LogRepo(self, entry(1, plug="test tests/test_a.py::test_gone, tests marked H3")).run("--check")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("note: I1: 1 plug item(s) not understood", done.stdout)

    def test_a_plugged_incident_needs_a_plug_it_can_read(self):
        for plug in ("none yet", "tests marked H3"):
            done = LogRepo(self, entry(1, status="plugged", plug=plug)).run("--check")
            self.assertEqual(done.returncode, 1, plug)
            self.assertIn("problem: I1", done.stdout)

    def test_an_old_open_incident_is_a_note_not_a_problem(self):
        done = LogRepo(self, entry(1, days=31)).run("--check")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("note: I1 has been open for 31 days", done.stdout)
        self.assertNotIn("open for", LogRepo(self, entry(1, days=30)).run().stdout)

    def test_plug_paths_are_relative_to_the_repo_root(self):
        repo = LogRepo(self, entry(1, status="plugged", plug="test tests/test_a.py::test_top"))
        done = repo.run("--check", cwd=os.path.join(repo.path, "tests"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_missing_log_is_a_friendly_error(self):
        done = LogRepo(self).run("--path", "nope.md")
        self.assertEqual(done.returncode, 2)
        self.assertIn("incidents: cannot read nope.md", done.stderr)
        self.assertNotIn("Traceback", done.stderr)


class DogfoodTest(unittest.TestCase):
    def read_log(self):
        with open(os.path.join(ROOT, "docs", "INCIDENTS.md"), encoding="utf-8") as handle:
            return handle.read()

    def test_this_repo_s_log_parses_and_its_plugs_exist(self):
        found, problems, _notes, _skipped = incidents.parse_log(self.read_log())
        self.assertGreaterEqual(len(found), 4)
        self.assertEqual(problems, [])
        self.assertNotIn(incidents.UNKNOWN_SLICE, [incident.slice for incident in found])
        done = subprocess.run((sys.executable, INCIDENTS, "--check"), cwd=ROOT, capture_output=True, text=True,
                              env=ENV)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_this_repo_s_test_plugs_would_pass_once_plugged(self):
        found, _problems, _notes, _skipped = incidents.parse_log(self.read_log())
        tests = [plug for incident in found for plug in incidents.parse_plug(incident.fields.get("plug", ""))[0]]
        self.assertTrue(tests)
        for plug in tests:
            self.assertIsNone(incidents.plug_problem(ROOT, plug), plug.text)


if __name__ == "__main__":
    unittest.main()
