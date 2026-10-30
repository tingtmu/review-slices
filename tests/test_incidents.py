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

    def test_items_joined_by_and_are_each_read(self):
        plugs, unread = incidents.parse_plug("test a.py::f and test b.py::g; guard c (x, and y), `test d.py::h`.")
        self.assertEqual(unread, [])
        self.assertEqual([plug.path for plug in plugs], ["a.py", "b.py", "c", "d.py"])

    def test_text_after_an_item_that_is_not_a_parenthetical_is_not_understood(self):
        self.assertEqual(incidents.parse_plug("test a.py::f plus test b.py::g")[1], ["test a.py::f plus test b.py::g"])

    def test_backticks_inside_a_rule_line_are_kept(self):
        plugs, _unread = incidents.parse_plug('rule REVIEW.md "a `#` cut a test command"')
        self.assertEqual(plugs[0].names, ["a `#` cut a test command"])

    def test_nested_plug_bullets_are_items(self):
        (_ident, _title, fields), = incidents.split_entries(
            "## I1. T\n\n- **Plug:**\n  - test a.py::f\n  - guard b\n- **Recurrences:** none\n")
        self.assertEqual(len(incidents.parse_plug(fields["plug"])[0]), 2)

    def test_none_yet_is_no_plug(self):
        self.assertEqual(incidents.parse_plug("none yet (a test arrives with the installer)"), ([], []))

    def test_a_slice_is_found_by_number_or_by_name(self):
        for text, expected in (("2 Review. Why it did not: x", "2 Review"), ("Offline tests. Why it did not: x",
                               "1 Offline suite"), ("Slice 4. Why it did not: x", "4 Acceptance"),
                               ("Go-ahead", "3 Go-ahead"), ("shown output", "0 Shown output"), ("CI", "unknown"),
                               ("Acceptance. Why it didn't: the review missed it", "4 Acceptance"),
                               ("Acceptance. why it did not: no review", "4 Acceptance")):
            self.assertEqual(incidents.slice_of(text), expected, text)

    def test_a_code_title_with_angle_brackets_is_not_skipped(self):
        found, _problems, _notes, skipped = incidents.parse_log(entry(1, "`Option<T>` unwrap panics"))
        self.assertEqual((len(found), skipped), (1, 0))

    def test_a_heading_that_is_almost_an_incident_is_a_problem(self):
        for heading in ("### I1.", "## i1.", "## Incident 1."):
            _found, problems, _notes, _skipped = incidents.parse_log(entry(1).replace("## I1.", heading))
            self.assertIn("looks like an incident heading", problems[0], heading)

    def test_headings_inside_a_code_fence_are_not_read(self):
        found, problems, _notes, _skipped = incidents.parse_log("```\n## i1. example\n## I2. example\n```\n" + entry(3))
        self.assertEqual(([incident.id for incident in found], problems), (["I3"], []))

    def test_a_comma_inside_test_parameters_does_not_split_the_item(self):
        self.assertEqual(incidents.parse_plug("test a.py::test_top[1,2], guard b")[1], [])

    def test_no_or_a_dash_is_no_recurrence(self):
        for text in ("none", "No", "n/a", "Not yet", "-", ""):
            self.assertFalse(incidents.has_recurrences(incidents.parse_log(entry(1, recurrences=text))[0][0]), text)

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

    def test_misses_through_a_reduced_review_load_are_counted(self):
        done = LogRepo(self, entry(1, slice_text="2 Review (merged reviewer)"),
                       entry(2, slice_text="2 Review (Adversarial + conformance)"),
                       entry(3, slice_text="2 Review (merged reviewer)"), entry(4)).run()
        self.assertIn("  2 Review         4\n", done.stdout)
        self.assertIn("\n  misses through a reduced load, recurrences included: merged reviewer 2, "
                      "adversarial + conformance 1\n", done.stdout)
        self.assertNotIn("reduced load", LogRepo(self, entry(1)).run().stdout)

    def test_a_second_miss_through_the_merged_reviewer_needs_the_small_band_off(self):
        merged = "2 Review (merged reviewer)"
        for rules, refused in (("", True), ("small: off\n", False), ("small: off  # I1, I2\n", False),
                               ("# small: off\n", True), ("small: 20 lines, 2 files\n", True),
                               ("medium: off\n", True)):
            log = LogRepo(self, entry(1, slice_text=merged), entry(2, slice_text=merged))
            with open(os.path.join(log.path, "REVIEW.md"), "a", encoding="utf-8") as handle:
                handle.write("\nsmall: off, said in prose\n\n```review-slices\ndefault: simple\n%s```\n" % rules)
            done = log.run("--check")
            self.assertEqual(done.returncode, int(refused), rules + done.stdout)
            self.assertEqual("problem: 2 misses went through the merged reviewer load (I1, I2) and I1, I2 has no "
                             "working test plug for each, so REVIEW.md's review-slices block needs `small: off`"
                             in done.stdout, refused, done.stdout)
        self.assertEqual(LogRepo(self, entry(1, slice_text=merged), entry(2)).run("--check").returncode, 0)

    def test_the_load_is_named_as_skill_md_writes_it_or_as_status_prints_it(self):  # review: "(one merged reviewer)"
        for first, second, load in (("(one merged reviewer)", "(Merged Reviewer)", "merged reviewer"),
                                    ("(one merged reviewer, small band)", "(merged reviewer: small band)",
                                     "merged reviewer"),
                                    ("(one merged reviewer (small: 12 weighted line(s), 2 file(s)))",
                                     "(merged reviewer (small band))", "merged reviewer"),
                                    ("(adversarial and conformance)", "(adversarial+conformance)",
                                     "adversarial + conformance")):
            done = LogRepo(self, entry(1, slice_text="2 Review " + first),
                           entry(2, slice_text="2 Review " + second)).run("--check")
            self.assertEqual(done.returncode, 1, done.stdout)
            self.assertIn("2 misses went through the %s load" % load, done.stdout)

    def test_only_the_block_the_guard_reads_turns_a_band_off(self):  # review: a decoy fence passed the check
        log = LogRepo(self, entry(1, slice_text="2 Review (merged reviewer)"),
                      entry(2, slice_text="2 Review (merged reviewer)"))
        with open(os.path.join(log.path, "REVIEW.md"), "a", encoding="utf-8") as handle:
            handle.write("\n```review-slices-example\nsmall: off\n```\n\n```review-slices\ndefault: simple\n```\n")
        self.assertEqual(log.run("--check").returncode, 1)

    def test_a_missing_review_md_is_named_in_the_problem(self):
        log = LogRepo(self, entry(1, slice_text="2 Review (merged reviewer)"),
                      entry(2, slice_text="2 Review (merged reviewer)"))
        os.remove(os.path.join(log.path, "REVIEW.md"))
        done = log.run("--check")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("needs `small: off` until each has one (REVIEW.md cannot be read: ", done.stdout)

    def test_a_narrowing_plug_still_counts_once_its_band_is_off(self):  # review: turning off broke the first plug
        log = LogRepo(self, entry(1, slice_text="2 Review (merged reviewer)", status="plugged",
                                  plug='rule REVIEW.md "small: 20 lines, 2 files"'),
                      entry(2, slice_text="2 Review (merged reviewer)"))
        with open(os.path.join(log.path, "REVIEW.md"), "a", encoding="utf-8") as handle:
            handle.write("\n```review-slices\nsmall: off  # I1, I2\n```\n")
        done = log.run("--check")
        self.assertEqual(done.returncode, 0, done.stdout)
        log.write("REVIEW.md", "# Rules\n\n```review-slices\nmedium: off\n```\n")
        self.assertIn("I1: plug `rule REVIEW.md \"small: 20 lines, 2 files\"` is missing", log.run("--check").stdout)

    def test_the_band_stays_on_only_when_every_miss_has_a_working_test_plug(self):
        merged, test, rule = "2 Review (merged reviewer)", "test tests/test_a.py::test_top", 'rule REVIEW.md "Rules"'
        for plugs, refused in (((test, test), False), ((test, rule), True), ((test, "none yet"), True),
                               ((test, "test tests/test_a.py::test_gone"), True)):
            log = LogRepo(self, *(entry(n, slice_text=merged, status="open" if plug == "none yet" else "plugged",
                                        plug=plug) for n, plug in enumerate(plugs, 1)))
            done = log.run("--check")
            self.assertEqual(done.returncode, int(refused), plugs)
            self.assertEqual("and I2 has no working test plug" in done.stdout, refused, done.stdout)

    def test_each_miss_needs_its_own_test_in_the_plug(self):  # review: the plug that missed it covered it
        line = ("\n  - 2026-10-01, 2 Review (merged reviewer): the merged reviewer read only the diff, and the plug "
                "test tests/test_a.py::test_top missed it.")
        top, cls, dot = ("test tests/test_a.py::test_top", "test tests/test_a.py::ATest::test_in_class",
                         "test tests/test_a.py::ATest.test_in_class")
        for plug, recurrences, refused in ((top, line, True), (top + ", " + cls, line, False),
                                           (top + ", " + cls + ", " + dot, line * 2, True),
                                           (top + ", test ./tests/test_a.py::test_top", line, True),
                                           (cls + ", test tests/test_a.py::test_in_class", line, True),
                                           (top + ", " + cls + ", test tests/test_a.py::test_gone", line, True),
                                           (top, "none", False)):
            done = LogRepo(self, entry(1, slice_text="2 Review (merged reviewer)", status="plugged", plug=plug,
                                       recurrences=recurrences)).run("--check")
            self.assertEqual(done.returncode, int(refused), plug + recurrences + done.stdout)

    def test_a_second_miss_by_the_pair_turns_off_every_band_that_gives_it(self):
        pair = "2 Review (adversarial + conformance)"
        for rules, missing in (("", "`medium: off`"), ("medium: off\n", None),
                               ("critical code: src/*\n", "`medium: off` and `small: off`"),
                               ("critical code: src/*\nmedium: off\n", "`small: off`"),
                               ("critical   code: src/*\nmedium: off\nsmall: off\n", None)):
            log = LogRepo(self, entry(1, slice_text=pair), entry(2, slice_text=pair))
            with open(os.path.join(log.path, "REVIEW.md"), "a", encoding="utf-8") as handle:
                handle.write("\n```review-slices\ndefault: simple\n%s```\n" % rules)
            done = log.run("--check")
            self.assertEqual(done.returncode, int(bool(missing)), rules + done.stdout)
            if missing:
                self.assertIn("review-slices block needs %s until each has one\n" % missing, done.stdout)

    def test_a_recurrence_that_names_a_load_is_a_miss_through_it(self):
        recurrence = "\n  - 2026-10-01, 2 Review (merged reviewer): the same class again."
        for entries, count in (((entry(1, slice_text="1 Offline suite", recurrences=recurrence),), 1),
                               ((entry(1, slice_text="2 Review (merged reviewer)", recurrences=recurrence),), 2),
                               ((entry(1, recurrences=recurrence * 2),), 2)):
            done = LogRepo(self, *entries).run("--check")
            self.assertIn("recurrences included: merged reviewer %d," % count, done.stdout)
            self.assertEqual(done.returncode, int(count > 1), done.stdout)

    def test_misses_from_one_review_unit_count_once(self):  # #21: one bad review is not a second miss
        unit = "2 Review (merged reviewer), unit %s"
        for first, second, refused in ((unit % "1a2b3c4d", unit % "1A2B3C4D5E6F", False),
                                       (unit % "1a2b3c4d", unit % "9f8e7d6c", True),
                                       (unit % "1a2b3c4d", "2 Review (merged reviewer)", True),
                                       ("2 Review (merged reviewer)", "2 Review (merged reviewer)", True)):
            done = LogRepo(self, entry(1, slice_text=first), entry(2, slice_text=second)).run("--check")
            self.assertEqual(done.returncode, int(refused), first + second + done.stdout)
            self.assertEqual("merged reviewer 2 in 1 review unit(s)," in done.stdout, not refused, done.stdout)

    def test_a_recurrence_names_its_own_unit(self):
        recurrence = "\n  - 2026-10-01, 2 Review (merged reviewer), unit %s: the same class again."
        slice_text = "2 Review (adversarial + conformance), unit 1a2b3c4d; then (merged reviewer), unit 1a2b3c4d"
        for recurrences, refused in ((recurrence % "1a2b3c4", False), (recurrence % "abcdef12", True),
                                     ("\n  - 2026-10-01, 2 Review (merged reviewer): no unit" + recurrence
                                      % "1a2b3c4d", True)):
            done = LogRepo(self, entry(1, slice_text=slice_text, recurrences=recurrences)).run("--check")
            self.assertEqual(done.returncode, int(refused), recurrences + done.stdout)

    def test_a_band_plug_must_be_a_line_the_guard_reads(self):  # review: a commented-out band passed the check
        plug = 'rule REVIEW.md "small: off"'
        for rules, refused in (("small: off\n", False), ("small: off  # incident I1\n", False),
                               ("# small: off\n", True), ("small: 40 lines, 3 files\n", True)):
            log = LogRepo(self, entry(1, status="plugged", plug=plug))
            with open(os.path.join(log.path, "REVIEW.md"), "a", encoding="utf-8") as handle:
                handle.write("\nsmall: off, said in prose\n\n```review-slices\n%s```\n" % rules)
            done = log.run("--check")
            self.assertEqual(done.returncode, int(refused), rules + done.stdout)
            self.assertEqual("review-slices block has no line 'small: off'" in done.stdout, refused, done.stdout)

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

    def test_a_second_item_joined_by_and_is_checked(self):
        plug = "test tests/test_a.py::test_top and test tests/test_a.py::test_gone"
        done = LogRepo(self, entry(1, status="plugged", plug=plug)).run("--check")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("test_gone", done.stdout)

    def test_a_plugged_code_title_is_still_checked(self):
        plug = "test tests/test_a.py::test_gone"
        done = LogRepo(self, entry(1, "`Option<T>` unwrap panics", status="plugged", plug=plug)).run("--check")
        self.assertEqual(done.returncode, 1, done.stdout)

    def test_a_plug_outside_review_md_or_the_repo_does_not_count(self):
        for plug in ('rule docs/INCIDENTS.md "Intro text"', 'rule REVIEW.md " "', "guard /etc/passwd",
                     "guard ../outside"):
            done = LogRepo(self, entry(1, status="plugged", plug=plug)).run("--check")
            self.assertEqual(done.returncode, 1, plug)
            self.assertIn("the hole is open again", done.stdout, plug)

    def test_a_test_that_cannot_fail_is_no_plug(self):
        repo = LogRepo(self)
        repo.write("tests/test_b.py", "import unittest\nimport pytest\n\n\nclass BTest(unittest.TestCase):\n"
                                      "    @unittest.expectedFailure\n    def test_x(self):\n        pass\n\n"
                                      "    @unittest.skipIf(False, 'no')\n    def test_live(self):\n        pass\n\n\n"
                                      "@unittest.skip('later')\nclass CTest(unittest.TestCase):\n"
                                      "    def test_y(self):\n        pass\n\n\n@pytest.mark.xfail\ndef test_z():\n"
                                      "    pass\n")
        for name, code in (("test_x", 1), ("CTest::test_y", 1), ("test_z", 1), ("test_live", 0)):
            repo.write("docs/INCIDENTS.md", entry(1, status="plugged", plug="test tests/test_b.py::" + name))
            done = repo.run("--check")
            self.assertEqual(done.returncode, code, name + "\n" + done.stdout)

    def test_every_way_a_test_never_fails_is_found(self):
        cases = {
            "redefined": "def test_x():\n    pass\n\n\n@pytest.mark.skip\ndef test_x():\n    pass\n",
            "skipped base": "@unittest.skip('x')\nclass A(unittest.TestCase):\n    pass\n\n\nclass B(A):\n"
                            "    def test_x(self):\n        pass\n",
            "pytestmark": "pytestmark = [pytest.mark.skip]\n\n\ndef test_x():\n    pass\n",
            "skipIf True": "@unittest.skipIf(True, 'until fixed')\ndef test_x():\n    pass\n",
            "skipTest": "class B(unittest.TestCase):\n    def test_x(self):\n        self.skipTest('later')\n",
        }
        repo = LogRepo(self, entry(1, status="plugged", plug="test tests/test_b.py::test_x"))
        for case, body in cases.items():
            repo.write("tests/test_b.py", "import unittest\nimport pytest\n\n\n" + body)
            done = repo.run("--check")
            self.assertEqual(done.returncode, 1, case + "\n" + done.stdout)
            self.assertIn("so it passes while the defect is back", done.stdout, case)

    def test_a_half_filled_template_entry_is_still_checked(self):
        text = entry(1, status="plugged", plug="test tests/test_a.py::test_gone")
        done = LogRepo(self, text.replace("defect", "<defect or process>")).run("--check")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("test_gone", done.stdout)

    def test_a_guard_linked_outside_the_repo_does_not_count(self):
        repo = LogRepo(self, entry(1, status="plugged", plug="guard g"))
        outside = tempfile.NamedTemporaryFile(prefix="review-slices-outside-")
        self.addCleanup(outside.close)
        os.symlink(outside.name, os.path.join(repo.path, "g"))
        done = repo.run("--check")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("is a link to a file outside the repo", done.stdout)

    def test_a_rule_line_with_backticks_is_found(self):
        repo = LogRepo(self, entry(1, status="plugged", plug='rule REVIEW.md "a `#` cut a test command"'))
        repo.write("REVIEW.md", "- a `#` cut a test\n  command\n")
        done = repo.run("--check")
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_unreadable_plug_files_are_problems_not_tracebacks(self):
        repo = LogRepo(self, entry(1, status="plugged", plug="test tests/test_nul.py::test_top"))
        with open(os.path.join(repo.path, "tests", "test_nul.py"), "wb") as handle:
            handle.write(b"def test_top():\n    pass\n\0\n")
        done = repo.run("--check")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_a_log_that_is_not_utf8_is_a_friendly_error(self):
        repo = LogRepo(self)
        with open(os.path.join(repo.path, "docs", "INCIDENTS.md"), "wb") as handle:
            handle.write(entry(1).encode("utf-16"))
        done = repo.run("--check")
        self.assertEqual(done.returncode, 2)
        self.assertIn("is not UTF-8 text", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_text_a_strict_stdout_cannot_encode_is_escaped_not_a_traceback(self):
        repo = LogRepo(self, entry(1, "Café au lait"))
        done = subprocess.run((sys.executable, INCIDENTS), cwd=repo.path, capture_output=True, text=True,
                              env=dict(ENV, PYTHONIOENCODING="ascii:strict"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Caf\\xe9 au lait", done.stdout)

    @unittest.skipUnless(sys.platform.startswith("linux"), "needs a filesystem that takes non-UTF-8 names")
    def test_a_log_path_that_is_not_utf8_is_printed_escaped(self):
        repo = LogRepo(self, entry(1))
        folder = os.path.join(os.fsencode(repo.path), b"logs-\xff")
        os.mkdir(folder)
        shutil.copy(os.path.join(os.fsencode(repo.path), b"docs", b"INCIDENTS.md"), folder)
        done = subprocess.run((sys.executable, INCIDENTS, "--path", os.path.join(folder, b"INCIDENTS.md")),
                              cwd=repo.path, capture_output=True, env=dict(ENV, PYTHONIOENCODING="utf-8"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(b"logs-\\udcff", done.stdout)

    def test_a_future_date_is_a_note(self):
        self.assertIn("in the future", LogRepo(self, entry(1, days=-3)).run().stdout)

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

    def test_this_repo_s_log_parses(self):
        found, problems, _notes, _skipped = incidents.parse_log(self.read_log())
        self.assertGreaterEqual(len(found), 4)
        self.assertEqual(problems, [])
        self.assertNotIn(incidents.UNKNOWN_SLICE, [incident.slice for incident in found])

    def test_this_repo_s_open_plugs_exist_and_wait_only_on_their_expected_failure(self):
        found, _problems, _notes, _skipped = incidents.parse_log(self.read_log())
        plugs = [plug for incident in found for plug in incidents.parse_plug(incident.fields.get("plug", ""))[0]]
        self.assertTrue(plugs)
        for plug in plugs:
            reason = incidents.plug_problem(ROOT, plug)
            self.assertTrue(reason is None or reason.endswith("is marked expectedFailure, so it passes while the "
                                                              "defect is back"), "%s: %s" % (plug.text, reason))


if __name__ == "__main__":
    unittest.main()
