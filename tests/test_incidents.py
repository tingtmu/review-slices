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
BANDS_ONLY = "none yet (no check: this test is about the bands)"  # a recurrence otherwise needs a test or check plug


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

    def run(self, *args, cwd=None, timeout=None):
        return subprocess.run((sys.executable, INCIDENTS) + args, cwd=cwd or self.path, capture_output=True,
                              text=True, env=ENV, timeout=timeout)


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

    def test_a_check_plug_and_a_no_check_reason_are_read(self):
        value = "check \"test: ! git grep -n 'old_api(' -- src\" (pins I1), guard g (no check: the rest is judgement)"
        plugs, unread = incidents.parse_plug(value)
        self.assertEqual(unread, [])
        self.assertEqual([(plug.kind, plug.path, plug.names) for plug in plugs], [
            ("check", "REVIEW.md", ["test: ! git grep -n 'old_api(' -- src"]), ("guard", "g", [])])
        for text, reason in ((value, "the rest is judgement"), ("none yet (no check: a judgement call).",
                                                                 "a judgement call"),
                             ("test a.py::f", None), ("none yet (no check: )", None), ("none yet", None)):
            self.assertEqual(incidents.no_check(text), reason, text)
        self.assertEqual(incidents.parse_plug("none yet (no check: a judgement call)"), ([], []))

    def test_a_recurrence_that_names_no_load_is_no_miss(self):  # a recurrence review caught names no load
        for text in ("\n  - 2026-10-01, 2 Review, unit 1a2b3c4d: the adversarial reviewer caught it again.",
                     "\n  - 2026-10-01, 2 Review: the merged reviewer caught it; adversarial + conformance agreed."):
            found = incidents.parse_log(entry(1, slice_text="1 Offline suite", recurrences=text))[0][0]
            self.assertEqual(incidents.misses(found), [], text)


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
                      "adversarial + conformance 1 (1 name no band: add it)\n", done.stdout)
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

    def test_a_second_miss_by_the_pair_needs_the_cross_check(self):  # 0.13.0: no band turned off lightens it
        pair = "2 Review (adversarial + conformance)"
        for rules, missing in (("", True), ("cross-check: on\n", False), ("cross-check: on  # I1, I2\n", False),
                               ("medium: off\nsmall: off\n", True), ("cross-check: off\n", True),
                               ("# cross-check: on\n", True)):
            log = LogRepo(self, entry(1, slice_text=pair), entry(2, slice_text=pair))
            with open(os.path.join(log.path, "REVIEW.md"), "a", encoding="utf-8") as handle:
                handle.write("\n```review-slices\ndefault: simple\n%s```\n" % rules)
            done = log.run("--check")
            self.assertEqual(done.returncode, int(missing), rules + done.stdout)
            if missing:
                self.assertIn("review-slices block needs `cross-check: on` until each has one\n", done.stdout)

    def test_misses_through_the_pair_on_a_large_or_critical_unit_are_counted(self):  # the stop rule
        done = LogRepo(self, entry(1, slice_text="2 Review (adversarial + conformance, large), unit 1a2b3c4d"),
                       entry(2, slice_text="2 Review (adversarial + conformance, medium)"),
                       entry(3, slice_text="2 Review (adversarial and conformance, Critical small)")).run()
        self.assertIn("adversarial + conformance 3 (2 on a large or Critical unit: tell the user before the next "
                      "one)\n", done.stdout)
        done = LogRepo(self, entry(1, slice_text="2 Review (adversarial + conformance), large later")).run()
        self.assertIn("adversarial + conformance 1 (1 name no band: add it)\n", done.stdout)  # review r2 F3

    def test_a_recurrence_that_names_a_load_is_a_miss_through_it(self):
        recurrence = "\n  - 2026-10-01, 2 Review (merged reviewer): the same class again."
        for entries, count in (((entry(1, slice_text="1 Offline suite", recurrences=recurrence, plug=BANDS_ONLY),), 1),
                               ((entry(1, slice_text="2 Review (merged reviewer)", recurrences=recurrence,
                                       plug=BANDS_ONLY),), 2),
                               ((entry(1, recurrences=recurrence * 2, plug=BANDS_ONLY),), 2)):
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
            done = LogRepo(self, entry(1, slice_text=slice_text, recurrences=recurrences, plug=BANDS_ONLY)
                           ).run("--check")
            self.assertEqual(done.returncode, int(refused), recurrences + done.stdout)

    def test_a_unit_counts_only_right_after_its_load(self):  # review: a later line's unit merged two units
        slice_text = "2 Review (merged reviewer), unit 1a2b3c4d"
        later = "\n  - 2026-10-09, 3 Go-ahead, unit 1a2b3c4d: pushed anyway."
        for first, recurrences in ((slice_text, "\n  - 2026-10-01, 2 Review (merged reviewer): again." + later),
                                   ("2 Review (one merged reviewer (small band)), unit 1a2b3c4d",
                                    "\n  - 2026-10-01, 2 Review (merged reviewer) again; the unit 1a2b3c4d test"),
                                   ("2 Review (merged reviewer). Why: the unit 1a2b3c4d test was skipped",
                                    "\n  - 2026-10-01, 2 Review (merged reviewer), unit 1a2b3c4d: again.")):
            done = LogRepo(self, entry(1, slice_text=first, recurrences=recurrences)).run("--check")
            self.assertEqual(done.returncode, 1, first + recurrences + done.stdout)
        done = LogRepo(self, entry(1, slice_text="2 Review (one merged reviewer (small band)), unit 1a2b3c4d",
                                   recurrences="\n  - 2026-10-01, 2 Review (merged reviewer), unit 1A2B3C4D9: again.",
                                   plug=BANDS_ONLY)).run("--check")
        self.assertEqual(done.returncode, 0, done.stdout)

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


CHECKS = ("# Rules\n\nPrecheck: grep for 'gone(' in prose, not in the block.\n\n```review-slices\n"
          "test: python3 -m unittest -q\nbase: main\n"
          "test: ! git grep -n 'old_api(' -- src  # I1\n"
          "test: ! git grep -n 'other(' -- src  # I2\n"
          "test: ! git grep -n 'both(' -- src  # I1, I2\n```\n")
OLD_API = "check \"test: ! git grep -n 'old_api(' -- src\""
REVIEWED = "\n  - 2026-10-01, 2 Review: caught again in review."


class CheckPlugTest(unittest.TestCase):
    def run_plug(self, plug, ident=1):
        log = LogRepo(self, entry(ident, status="plugged", plug=plug))
        log.write("REVIEW.md", CHECKS)
        return log.run("--check")

    def test_a_check_plug_on_its_own_tagged_test_line_is_working(self):
        for plug in (OLD_API, OLD_API + " (pins old_api)", "`%s`" % OLD_API,
                     "check \"test: ! git grep -n 'old_api(' -- src  # I1\""):
            done = self.run_plug(plug)
            self.assertEqual(done.returncode, 0, plug + done.stdout)

    def test_a_check_plug_that_is_no_test_line_of_the_block_reopens_the_hole(self):
        for text in ("test: ! git grep -n 'gone(' -- src", "base: main", "Precheck: grep for 'gone(' in prose",
                     "test: python3 -m unittest"):
            done = self.run_plug('check "%s"' % text)
            self.assertEqual(done.returncode, 1, text + done.stdout)
            self.assertIn("is not a `test:` line of REVIEW.md's review-slices block; " + incidents.REOPEN,
                          done.stdout, text)

    def test_a_check_plug_line_must_end_with_its_own_incident_id(self):  # else one plug could name the suite
        for text, ident in (("test: python3 -m unittest -q", 1), ("test: ! git grep -n 'other(' -- src", 1),
                            ("test: ! git grep -n 'both(' -- src", 1), ("test: ! git grep -n 'old_api(' -- src", 11)):
            done = self.run_plug('check "%s"' % text, ident)
            self.assertEqual(done.returncode, 1, text + done.stdout)
            self.assertIn("does not end with the comment `# I%d`" % ident, done.stdout, text)

    def test_a_check_plug_with_a_double_quote_is_a_problem(self):
        done = self.run_plug('check "test: ! git grep -n "old_api(" -- src"')
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("contains `\"`; quote the test: line's arguments with single quotes", done.stdout)


class EscalationTest(unittest.TestCase):
    def test_a_recurrence_needs_a_working_test_or_check_plug_or_a_reason(self):
        for status, plug, recurrences, refused in (
                ("open", "none yet", REVIEWED, True), ("plugged", 'rule REVIEW.md "Rules"', REVIEWED, True),
                ("plugged", "guard .githooks/pre-push", REVIEWED, True),
                ("plugged", "test tests/test_a.py::test_gone", REVIEWED, True),
                ("open", "test tests/test_a.py::test_gone", REVIEWED, True),
                ("open", "none yet (no check: )", REVIEWED, True),
                ("plugged", 'rule REVIEW.md "Rules"', "none", False),
                ("open", "none yet", "none", False),
                ("plugged", "test tests/test_a.py::test_top", REVIEWED, False),
                ("open", "test tests/test_a.py::ATest::test_in_class", REVIEWED, False),
                ("plugged", OLD_API, REVIEWED, False), ("open", OLD_API, REVIEWED, False),
                ("open", "none yet (no check: judgement only)", REVIEWED, False),
                ("plugged", 'rule REVIEW.md "Rules" (no check: judgement only)', REVIEWED, False)):
            log = LogRepo(self, entry(1, status=status, plug=plug, recurrences=recurrences))
            log.write("REVIEW.md", CHECKS)
            done = log.run("--check")
            self.assertEqual(done.returncode, int(refused), "%s %s %s\n%s" % (status, plug, recurrences, done.stdout))
            self.assertEqual("problem: I1 has a recurrence but no working test or check plug" in done.stdout, refused,
                             done.stdout)

    def test_a_test_plug_on_a_text_file_is_no_plug(self):  # review: `test docs/INCIDENTS.md::again` passed
        for plug in ("test docs/INCIDENTS.md::Incidents", "test REVIEW.md::Rules", "test notes.txt::x",
                     "test docs/a.rst::x"):
            log = LogRepo(self, entry(1, status="plugged", plug=plug),
                          entry(2, plug=plug, recurrences=REVIEWED))
            log.write("notes.txt", "x\n")
            log.write("docs/a.rst", "x\n")
            done = log.run("--check")
            self.assertEqual(done.returncode, 1, plug + done.stdout)
            self.assertIn("a test plug must name a test file the suite runs", done.stdout, plug)
            self.assertIn("problem: I2 has a recurrence but no working test or check plug", done.stdout, plug)

    def test_a_no_check_reason_must_be_words(self):  # review: the template's <reason> and `-` counted
        for reason in ("<reason>", "-", " — ", "123"):
            done = LogRepo(self, entry(1, plug="none yet (no check: %s)" % reason, recurrences=REVIEWED)).run("--check")
            self.assertEqual(done.returncode, 1, reason + done.stdout)
            self.assertIn("problem: I1 has a recurrence but no working test or check plug", done.stdout, reason)
            self.assertIn("gives no reason in words", done.stdout, reason)
            self.assertNotIn("note: I1: no check", done.stdout, reason)

    def test_a_recurrence_is_any_dated_line_in_the_field(self):  # review: three spellings slipped past
        for text in (entry(1, recurrences="none\n  - 2026-10-05, 2 Review: caught again"),
                     entry(1, recurrences=REVIEWED).replace("**Recurrences:**", "**Recurrence:**"),
                     entry(1, recurrences="No plug stopped it: 2026-10-05, 2 Review again")):
            done = LogRepo(self, text).run("--check")
            self.assertEqual(done.returncode, 1, text + done.stdout)
            self.assertIn("problem: I1 has a recurrence but no working test or check plug", done.stdout, text)

    def test_an_undated_recurrence_counts_everywhere(self):  # review: listed as weak, yet not escalated
        undated = "\n  - review of 0.4.0, unit 1a2b3c4: caught again"
        done = LogRepo(self, entry(1, recurrences=undated)).run("--check")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("problem: I1 has a recurrence but no working test or check plug", done.stdout)
        self.assertIn("recurrences (each means a weak plug):\n  I1. A failure: review of 0.4.0", done.stdout)
        log = LogRepo(self, entry(1, status="plugged", plug="test tests/test_a.py::test_top", recurrences=undated))
        log.write("REVIEW.md", "# Rules\n\n## Failure looks like\n\n- A thing (suite) ([I1](docs/INCIDENTS.md))\n")
        done = log.run("--check")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("is marked (suite) but I1 has a recurrence", done.stdout)
        singular = entry(1, recurrences=undated).replace("**Recurrences:**", "**Recurrence:**")
        self.assertIn("  I1. A failure: review of 0.4.0", LogRepo(self, singular).run().stdout)

    def test_every_no_check_reason_is_a_note(self):
        done = LogRepo(self, entry(1, plug="none yet (no check: judgement only)", recurrences=REVIEWED),
                       entry(2, status="plugged", plug='rule REVIEW.md "Rules" (no check: prose)')).run("--check")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("note: I1: no check: judgement only\n", done.stdout)
        self.assertIn("note: I2: no check: prose\n", done.stdout)


class SuiteMarkerTest(unittest.TestCase):
    def run_line(self, line):
        log = LogRepo(self, entry(1, status="plugged", plug="test tests/test_a.py::test_top"),
                      entry(2, status="plugged", plug='rule REVIEW.md "Rules"'),
                      entry(3, status="plugged", plug="test tests/test_a.py::test_top", recurrences=REVIEWED),
                      entry(4, status="plugged", plug=OLD_API),
                      entry(5, status="plugged", plug="test tests/test_a.py::ATest::test_in_class",
                            recurrences="none\n  - 2026-10-05, 2 Review: caught again"))
        log.write("REVIEW.md", CHECKS.replace("# I1\n", "# I4\n") + "\n## Failure looks like\n\n" + line
                  + "\n\n## Repo rules\n\n- Nothing marked here\n")
        return log.run("--check")

    def test_a_suite_line_needs_every_linked_incident_tested_and_never_recurred(self):
        link = "[I%d](docs/INCIDENTS.md#i%d)"
        for line, refused in (("- A thing (suite) (%s)" % (link % (1, 1)), False),
                              ("- A thing (suite) (%s, %s)" % (link % (1, 1), link % (4, 4)), False),
                              ("- A thing\n  (suite) (%s)" % (link % (1, 1)), False), ("- A thing", False),
                              ("- A thing (suite)", True), ("- A thing (suite) (%s)" % (link % (2, 2)), True),
                              ("- A thing (suite) (%s)" % (link % (3, 3)), True),
                              ("- A thing (suite) (%s, %s)" % (link % (1, 1), link % (2, 2)), True),
                              ("- A thing (suite) (%s)" % (link % (9, 9)), True),
                              ("- A thing (suite) (%s)" % (link % (5, 5)), True)):
            done = self.run_line(line)
            self.assertEqual(done.returncode, int(refused), line + "\n" + done.stdout)
            self.assertEqual("problem: REVIEW.md's \"Failure looks like\" line" in done.stdout, refused, done.stdout)

    def test_every_suite_marker_is_found_and_must_sit_on_a_failure_item(self):  # review: (Suite), ###, numbered
        link = "[I%d](docs/INCIDENTS.md#i%d)"
        for line, refused, outside in (("- A thing (Suite) (%s)" % (link % (2, 2)), True, False),
                                       ("1. A thing (suite) (%s)" % (link % (2, 2)), True, False),
                                       ("1. A thing (suite) (%s)" % (link % (1, 1)), False, False),
                                       ("### Sub\n\n- A thing (SUITE) (%s)" % (link % (2, 2)), True, False),
                                       ("### Sub\n\n- A thing (suite) (%s)" % (link % (1, 1)), False, False),
                                       ("Prose (suite) here (%s)" % (link % (1, 1)), True, True),
                                       ("- A thing\n\n## Repo rules\n\n- Rule (suite) (%s)" % (link % (1, 1)), True,
                                        True),
                                       ("Prose explains the `(suite)` marker", False, False),
                                       ("- A thing\n\n## Repo rules\n\n- Mark a line `(Suite)` once tested", False,
                                        False),
                                       ("- A thing `(suite)` (%s)" % (link % (2, 2)), True, False)):
            done = self.run_line(line)
            self.assertEqual(done.returncode, int(refused), line + "\n" + done.stdout)
            self.assertEqual("outside a \"Failure looks like\" item" in done.stdout, outside, done.stdout)


class OpenSuiteTest(unittest.TestCase):
    def test_a_suite_line_linking_an_open_incident_is_a_problem(self):  # review: open plugs are never checked
        for status, refused in (("open", True), ("plugged", False)):
            log = LogRepo(self, entry(1, status=status, plug="test tests/test_a.py::test_top"))
            log.write("REVIEW.md", "# Rules\n\n## Failure looks like\n\n- A thing (suite) ([I1](docs/INCIDENTS.md))\n")
            done = log.run("--check")
            self.assertEqual(done.returncode, int(refused), status + done.stdout)
            self.assertEqual("is marked (suite) but I1 is open" in done.stdout, refused, done.stdout)


class TemplateTest(unittest.TestCase):
    def test_a_repo_set_up_from_the_templates_passes_the_check(self):  # review: its prose mentions `(suite)`
        log = LogRepo(self)
        for template, target in (("REVIEW.md", "REVIEW.md"), ("INCIDENTS.md", "docs/INCIDENTS.md"),
                                 ("NEAR-MISSES.md", "docs/NEAR-MISSES.md")):
            with open(os.path.join(ROOT, "skills", "review-slices", "templates", template), encoding="utf-8") as h:
                log.write(target, h.read())
        done = log.run("--check")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("problem:", done.stdout)


class NoticeTest(unittest.TestCase):
    def dated(self, days):
        return (TODAY - datetime.timedelta(days=days)).isoformat()

    def test_near_misses_never_change_the_exit_code(self):
        text = ("# Near misses\n\n## I7. A heading\n\n- **Plug:** test tests/gone.py::test_x\n- F1 old — %s abc1234\n"
                "- F2 bad date — 2026-13-45 abc\nproblem: small: off\n```review-slices\nsmall: off\n```\n"
                % self.dated(400))
        for plug, code in (("test tests/test_a.py::test_top", 0), ("test tests/test_a.py::test_gone", 1)):
            log = LogRepo(self, entry(1, status="plugged", plug=plug),
                          entry(2, slice_text="2 Review (merged reviewer)"))
            for content in (None, text.encode("utf-8"), b"\xff\xfe\x00 garbage\n" + text.encode("utf-8")):
                if content is not None:
                    with open(os.path.join(log.path, "docs", "NEAR-MISSES.md"), "wb") as handle:
                        handle.write(content)
                done = log.run("--check")
                self.assertEqual(done.returncode, code, "%s %r\n%s" % (plug, content, done.stdout + done.stderr))
                self.assertNotIn("Traceback", done.stderr)

    def test_a_stale_one_sighting_near_miss_is_a_notice(self):
        old, recent = self.dated(91), self.dated(10)
        lines = {"- one old — %s abc1234 Fix" % old: True,
                 "- two sightings — %s abc1234, %s def5678 Fix" % (old, self.dated(200)): False,
                 "- one recent — %s abc1234 Blocker" % recent: False,
                 "- rejected is no sighting — %s abc1234; rejected %s def5678" % (old, recent): True,
                 "- seen again recently — %s abc1234; rejected %s def5678" % (recent, old): False,
                 "- ninety days — %s abc1234" % self.dated(90): False,
                 "- F2 promoted to a Failure looks like line — %s abc1234 Blocker" % old: False,
                 "- pinned by a check — %s abc1234 Fix; plugged: test tests/test_a.py::test_top" % old: False,
                 "Prose dated %s is no entry" % old: False}
        log = LogRepo(self, entry(1))
        log.write("docs/NEAR-MISSES.md", "# Near misses\n\n" + "\n".join(lines) + "\n")
        done = log.run("--check")
        self.assertEqual(done.returncode, 0, done.stdout)
        for line, stale in lines.items():
            self.assertEqual(("note: docs/NEAR-MISSES.md: a one-sighting near miss over 90 days old; delete it in "
                              "your next commit: %s\n" % line) in done.stdout, stale, line + "\n" + done.stdout)

    def test_a_near_miss_log_that_is_no_file_inside_the_repo_is_skipped(self):  # review: a link read outside
        outside = tempfile.mkdtemp(prefix="review-slices-outside-")
        self.addCleanup(shutil.rmtree, outside, True)
        with open(os.path.join(outside, "secret.txt"), "w", encoding="utf-8") as handle:
            handle.write("- secret line — 2020-01-01 abc1234\n")
        log = LogRepo(self, entry(1))
        os.mkfifo(os.path.join(log.path, "pipe"))
        near = os.path.join(log.path, "docs", "NEAR-MISSES.md")
        for target in (os.path.join(outside, "secret.txt"), os.path.join(log.path, "pipe"), "/dev/zero"):
            if os.path.lexists(near):
                os.remove(near)
            os.symlink(target, near)
            done = log.run("--check", timeout=30)
            self.assertEqual(done.returncode, 0, target + done.stdout)
            self.assertNotIn("secret line", done.stdout)
            self.assertIn("note: docs/NEAR-MISSES.md is not a regular file inside the repo, so it was not read",
                          done.stdout, target)

    def test_prune_due_is_a_notice(self):
        for header, due in (("", True), ("Last pruned: %s\n\n" % self.dated(10), False),
                            ("- **Last pruned:** %s\n\n" % self.dated(90), False),
                            ("Last pruned: %s\n\n" % self.dated(91), True)):
            log = LogRepo(self)
            log.write("docs/INCIDENTS.md", "# Incidents\n\n" + header + entry(1))
            done = log.run("--check")
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertEqual("note: prune due:" in done.stdout, due, header + done.stdout)


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
