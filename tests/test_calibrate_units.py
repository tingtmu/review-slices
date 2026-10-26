"""calibrate.py's sections after the level mix: glob attribution, units, size, quiet changes, candidates, load."""
import os
import re
import subprocess
import sys
import unittest

from support import ENV, RULES, Repo
from test_calibrate import CALIBRATE, calibrate

UNIT_RULES = RULES + "important: lib/*\n"


class UnitsTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self, rules=UNIT_RULES)

    def run_ok(self, *args):
        done = calibrate(self.repo, *(args + ("--base", "main")))
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def change(self, files, message, level=None):
        """Commit FILES ({path: text}, None removes it) as MESSAGE, with a trailer at LEVEL if given."""
        for path, text in files.items():
            if text is None:
                self.repo.remove(path)
            else:
                self.repo.write(path, text)
        return self.repo.commit(message, trailer=self.repo.trailer(level) if level else None)

    def attribution(self, out, level, label):
        match = re.search(r"\n  %s\s+%s\s+involved\s+(\d+)\s+alone\s+(\d+)(.*)" % (level, re.escape(label)), out)
        self.assertIsNotNone(match, "%s %s not in:\n%s" % (level, label, out))
        return int(match.group(1)), int(match.group(2)), match.group(3)

    def grid(self, out, lines):
        row = re.search(r"\n  <=%d\s+(.*)" % lines, out).group(1)
        return [int(cell) for cell in re.findall(r"(\d+)\s+\d+%", row)]

    def test_attribution_counts_involved_and_alone(self):
        self.repo.write("REVIEW.md", "# Review rules\n\n```review-slices\n%scritical: vendor/*\n```\n" % UNIT_RULES)
        self.repo.commit("add vendor/")
        self.change({"core/a.py": "a\n"}, "core alone")
        self.change({"core/b.py": "b\n", "vendor/c.py": "c\n"}, "two critical globs")
        self.change({"src/d.py": "d\n"}, "default")
        out = self.run_ok()
        self.assertEqual(self.attribution(out, "critical", "core/*"), (2, 1, "  (else simple 1)"))
        self.assertEqual(self.attribution(out, "critical", "vendor/*")[:2], (1, 0))
        # REVIEW.md is both a glob and a floor: each is involved, so neither is alone
        self.assertEqual(self.attribution(out, "important", "REVIEW.md")[:2], (2, 0))
        self.assertEqual(self.attribution(out, "important", "REVIEW.md (floor)")[:2], (2, 0))
        self.assertNotIn("no glob: default", out.split("glob attribution")[1])

    def test_trailers_close_units(self):
        self.change({"lib/t.py": "t\n"}, "first trailer", "important")
        self.change({"lib/a.py": "1\n2\n3\n"}, "untrailered")
        self.change({"lib/b.py": "1\n2\n"}, "closes the unit", "important")
        self.change({"lib/c.py": "c\n"}, "after the last")
        out = self.run_ok("--list-candidates", "100", "5")
        self.assertIn("review units: 4 (2 with no declared level", out)
        self.assertRegex(out, r"closes the unit\s+5 line\(s\), 2 file\(s\)")
        self.assertRegex(out, r"after the last\s+1 line\(s\), 1 file\(s\)")
        self.assertNotRegex(out, r"untrailered\s+\d+ line")

    def test_a_branch_that_merged_main_and_was_fast_forwarded_is_left_out(self):  # plan round 1's repro
        cases = ((None, None, True), ("critical", None, True), ("critical", "important", True),  # review: trailered
                 ("critical", None, False), ("critical", "important", False))
        for theirs, mine, done in cases:
            with self.subTest(theirs=theirs, mine=mine, done=done):
                self.repo = Repo(self, rules=UNIT_RULES)
                self.back_merge(theirs, mine, done)

    def back_merge(self, theirs, mine, done):
        """Someone else's commit on main (trailered THEIRS), merged into a branch whose earlier commit is trailered
        MINE, then, if DONE, one more trailered commit; main is fast-forwarded to the branch."""
        repo = self.repo
        self.change({"lib/t.py": "t\n"}, "first trailer", "important")
        repo.git("checkout", "-q", "-b", "feature")
        self.change({"lib/f.py": "f\n"}, "feature work", mine)
        repo.git("checkout", "-q", "main")
        self.change({"core/x.py": "x\n" * 30}, "someone else's work on main", theirs)
        repo.git("checkout", "-q", "feature")
        repo.git("merge", "-q", "--no-edit", "main")
        if done:
            self.change({"lib/g.py": "g\n"}, "feature done", "important")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--ff-only", "feature")
        out = self.run_ok("--list-candidates", "100", "5")
        self.assertIn("note: 1 unit(s) left out of what follows", out)
        self.assertIn("(%d unit(s) with a trailer)" % (2 if mine else 1), out)
        self.assertNotIn("feature done", out.split("review units:")[1])
        self.assertNotIn("critical", out.split("review units:")[1].split("whitespace")[0])

    def test_a_branch_that_merged_main_twice_is_left_out(self):  # an open unit, then a merge after the merge
        repo = self.repo
        self.change({"lib/t.py": "t\n"}, "first trailer", "important")
        repo.git("checkout", "-q", "-b", "feature")
        self.change({"lib/f.py": "f\n"}, "feature work")
        for number in range(2):
            repo.git("checkout", "-q", "main")
            self.change({"core/%d.py" % number: "x\n" * 30}, "their work %d" % number, "critical")
            repo.git("checkout", "-q", "feature")
            repo.git("merge", "-q", "--no-edit", "main")
        self.change({"lib/g.py": "g\n"}, "feature done", "important")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--ff-only", "feature")
        out = self.run_ok()
        self.assertIn("note: 1 unit(s) left out", out)
        self.assertNotIn("critical", out.split("review units:")[1].split("whitespace")[0])

    def test_a_unit_the_window_cuts_short_is_left_out(self):  # review: measured as its closing commit alone
        self.change({"lib/t.py": "t\n"}, "an earlier trailer", "important")
        for number in range(5):
            self.change({"lib/%d.py" % number: "x\n" * 30}, "untrailered %d" % number)
        self.change({"lib/c.py": "c\n"}, "closes the big unit", "important")
        self.change({"lib/d.py": "d\n"}, "next unit", "important")
        out = self.run_ok("--count", "6", "--list-candidates", "200", "9")
        self.assertIn("review units: 2 (0 with no declared level", out)
        self.assertIn("note: 1 unit(s) left out of what follows: cut short", out)
        self.assertNotIn("closes the big unit", out.split("review units:")[1])
        out = self.run_ok("--count", "7", "--list-candidates", "200", "9")  # the window now starts after a trailer
        self.assertRegex(out, r"closes the big unit\s+151 line\(s\), 6 file\(s\)")
        self.assertNotIn("left out", out)
        self.repo.git("push", "-q", "origin", "main")  # review: a shallow clone hid the earlier trailer
        clone = os.path.join(self.repo.tmp, "shallow")
        Repo.run_git(self.repo.tmp, "clone", "-q", "--depth", "4", "file://" + self.repo.remote, clone)
        done = subprocess.run((sys.executable, CALIBRATE, "--list-candidates", "200", "9"), cwd=clone,
                              capture_output=True, text=True, env=ENV, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("note: 1 unit(s) left out of what follows: cut short", done.stdout)
        self.assertNotIn("closes the big unit", done.stdout.split("review units:")[1])

    def test_a_pull_request_merge_takes_its_sides_highest_trailer(self):
        repo = self.repo
        repo.git("checkout", "-q", "-b", "pr")
        self.change({"lib/p.py": "p\n"}, "pr part one", "simple")
        self.change({"lib/q.py": "q\n"}, "pr part two", "critical")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #1 from someone/pr", "pr")
        self.change({"lib/v.py": "1\n"}, "release 1")  # review: a direct commit after it lost the pull request
        out = self.run_ok()
        self.assertIn("0 equal, 1 declared higher, 0 declared lower", out)
        self.assertRegex(out, r"higher: \w+  Merge pull request #1 from someone/pr  declared critical, computed")
        self.assertNotIn("left out", out)

    def test_a_back_merge_before_a_pull_request_is_left_out(self):  # review: a merge after it made it one
        repo = self.repo
        repo.git("checkout", "-q", "-b", "feature")
        self.change({"lib/f.py": "f\n"}, "feature work", "important")
        repo.git("checkout", "-q", "main")
        self.change({"core/x.py": "x\n" * 30}, "someone else's work on main", "critical")
        repo.git("checkout", "-q", "feature")
        repo.git("merge", "-q", "--no-edit", "main")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--ff-only", "feature")
        self.pull_request("p", 2)
        out = self.run_ok()
        self.assertIn("note: 2 unit(s) left out", out)  # the pull request too: a unit was open before it
        self.assertNotIn("critical", out.split("review units:")[1].split("whitespace")[0])

    def pull_request(self, name, number, level="important"):
        self.repo.git("checkout", "-q", "-b", name)
        self.change({"lib/%s.py" % name: "p\n"}, "pr %s" % name, level)
        self.repo.git("checkout", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #%d from someone/%s" % (number, name), name)

    def test_a_pull_request_closes_a_unit_like_a_trailer(self):  # review: the next unit was split
        self.pull_request("a", 1)
        self.change({"lib/d.py": "d\n" * 30}, "direct part one")
        self.change({"lib/e.py": "e\n"}, "direct part two", "important")
        out = self.run_ok("--list-candidates", "100", "5")
        self.assertRegex(out, r"direct part two\s+31 line\(s\), 2 file\(s\)")

    def test_a_window_of_pull_requests_after_direct_trailers_is_measured(self):  # review: all were left out
        self.change({"lib/t.py": "t\n"}, "an early direct trailer", "important")
        for number in range(5):
            self.pull_request("p%d" % number, number + 1)
        out = self.run_ok("--count", "3")
        self.assertIn("(3 unit(s) with a trailer)", out)
        self.assertNotIn("left out", out)

    def test_a_squash_merge_is_its_own_unit_at_its_highest_level(self):  # review: merged into the next one
        self.change({"lib/t.py": "t\n"}, "first trailer", "important")
        self.change({"lib/b.py": "b\n" * 40}, "Bump foo (#4)")
        self.change({"lib/s.py": "s\n"}, "Small fix (#5)", "important")
        self.change({"lib/q.py": "q\n"}, "Squash (#3)\n\n* one\n\nReview: critical 0123456789ab\n\n* two", "simple")
        out = self.run_ok("--list-candidates", "100", "5")
        self.assertRegex(out, r"Bump foo \(#4\)\s+40 line\(s\), 1 file\(s\)")
        self.assertRegex(out, r"Small fix \(#5\)\s+1 line\(s\), 1 file\(s\)")
        self.assertRegex(out, r"higher: \w+  Squash \(#3\)  declared critical, computed important")
        self.assertNotRegex(out.split("candidates within")[1], r"Squash \(#3\)")

    def test_a_window_that_starts_at_a_back_merge_leaves_it_out(self):  # review: measured as a pull request
        repo = self.repo
        self.change({"lib/t.py": "t\n"}, "first trailer", "important")
        repo.git("checkout", "-q", "-b", "feature")
        self.change({"lib/f.py": "f\n"}, "feature work")
        repo.git("checkout", "-q", "main")
        self.change({"core/x.py": "x\n" * 30}, "someone else's work on main", "critical")
        repo.git("checkout", "-q", "feature")
        repo.git("merge", "-q", "--no-edit", "main")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--ff-only", "feature")
        repo.git("checkout", "-q", "-b", "pr")
        self.change({"lib/p.py": "p\n"}, "pr work", "important")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #2 from someone/pr", "pr")
        out = self.run_ok("--count", "2")
        self.assertIn("note: 2 unit(s) left out", out)  # the pull request too: the cut-short unit never closed
        self.assertNotIn("critical", out.split("review units:")[1].split("whitespace")[0])

    def test_a_squash_merge_whose_trailer_is_buried_is_its_own_unit(self):
        self.change({"lib/t.py": "t\n"}, "first trailer", "important")
        self.change({"lib/a.py": "a\n"}, "before the squash")
        self.change({"lib/s1.py": "1\n", "lib/s2.py": "2\n"},
                    "Squash (#2)\n\n* part\n\nReview: important 0123456789ab\n\n* more\n\n"
                    "Co-authored-by: X <x@example.com>")
        self.change({"lib/c.py": "c\n"}, "after the squash", "important")
        out = self.run_ok("--list-candidates", "100", "5")
        self.assertIn("review units: 5 (2 with no declared level", out)  # init and the commit before the squash
        self.assertRegex(out, r"Squash \(#2\)\s+2 line\(s\), 2 file\(s\)")
        self.assertRegex(out, r"after the squash\s+1 line\(s\), 1 file\(s\)")  # review: lib/a.py was before it

    def test_a_no_ff_merge_of_an_untrailered_branch_is_left_out(self):
        repo = self.repo
        self.change({"lib/t.py": "t\n"}, "first trailer", "important")
        repo.git("checkout", "-q", "-b", "side")
        self.change({"core/x.py": "x\n"}, "side work")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "merge side", "side")
        self.change({"lib/c.py": "c\n"}, "closes after the merge", "important")
        out = self.run_ok("--list-candidates", "100", "5")
        self.assertRegex(out, r"merge side  core/x.py  \(core/\*\)")  # judged by its first-parent change
        self.assertIn("note: 1 unit(s) left out", out)
        self.assertNotIn("closes after the merge", out.split("review units:")[1])

    def test_declared_higher_and_lower_are_counted_and_listed(self):
        self.change({"lib/a.py": "a\n"}, "raised for a planned action", "critical")
        self.change({"lib/b.py": "b\n"}, "declared too low", "simple")
        self.change({"lib/c.py": "c\n"}, "just right", "important")
        out = self.run_ok()
        self.assertIn("(3 unit(s) with a trailer): 1 equal, 1 declared higher, 1 declared lower", out)
        self.assertRegex(out, r"higher: \w+  raised for a planned action  declared critical, computed important")
        self.assertRegex(out, r"lower: \w+  declared too low  declared simple, computed important")

    def test_size_weights_long_lines_and_counts_files(self):
        self.change({"lib/run.sh": "a\nb\n"}, "base", "important")
        self.change({"lib/long.py": "x" * 1000 + "\nshort\n"}, "a long line", "important")
        os.chmod(os.path.join(self.repo.path, "lib/run.sh"), 0o755)
        self.repo.commit("mode only", trailer=self.repo.trailer("important"))
        self.repo.git("mv", "lib/run.sh", "lib/go.sh")
        self.repo.commit("rename", trailer=self.repo.trailer("important"))
        self.change({"lib/b.bin": "\0\1\2\n"}, "binary", "important")
        with open(os.path.join(self.repo.path, "lib/cr.txt"), "w", encoding="utf-8", newline="") as handle:
            handle.write("a\rb\n" * 40)  # review: a lone CR is no line break to git
        self.repo.commit("lone CRs", trailer=self.repo.trailer("important"))
        out = self.run_ok("--list-candidates", "100", "5")
        self.assertRegex(out, r"a long line\s+11 line\(s\), 1 file\(s\)")
        self.assertRegex(out, r"mode only\s+0 line\(s\), 1 file\(s\)")
        self.assertRegex(out, r"rename\s+4 line\(s\), 2 file\(s\)")  # a delete plus an add
        self.assertRegex(out, r"lone CRs\s+40 line\(s\), 1 file\(s\)")
        self.assertNotRegex(out, r"binary\s+\d+ line")
        self.assertIn("(1 unit(s) with a binary file left out)", out)

    def test_quiet_units_are_whitespace_or_comments_never_indentation_pragmas_or_prose(self):
        self.change({"lib/a.py": "def f():\n    return 1  # one\n", "lib/r.md": "text\n"}, "base", "important")
        self.change({"lib/a.py": "def f():   \n    return 1  # one\n"}, "trailing space", "important")
        self.change({"lib/a.py": "# about f\ndef f():   \n    return 1  # one\n"}, "a comment", "important")
        self.change({"lib/a.py": "# about f\ndef f():   \n  return 1  # one\n"}, "indentation", "important")
        self.change({"lib/a.py": "# noqa\n# about f\ndef f():   \n  return 1  # one\n"}, "a pragma", "important")
        self.change({"lib/r.md": "text, edited\n"}, "prose", "important")
        self.change({"lib/m.c": "/* m */\n*p = 1;\n"}, "C base", "important")
        self.change({"lib/m.c": "/* m */\n *\n * more\n */\n*p = 1;\n"}, "a C block comment", "important")
        self.change({"lib/m.c": "/* m */\n *\n * more\n */\n*p = 2;\n"}, "a pointer write", "important")
        out = self.run_ok()
        # the init unit and nine more are important; only the trailing space and the two comments are quiet
        self.assertIn("important 3 of 10", out)

    def test_merged_reviewer_candidates_leave_out_floors_raises_binaries_and_big_units(self):
        self.change({"lib/small.py": "s\n"}, "small", "important")
        self.change({"lib/big.py": "b\n" * 100}, "big", "important")
        self.change({".githooks/extra.py": "e\n"}, "floor path", "important")
        self.change({"lib/raised.py": "r\n"}, "raised", "critical")
        self.change({"lib/b.bin": "\0\n"}, "binary", "important")
        out = self.run_ok("--list-candidates", "10", "1")
        self.assertIn("merged-reviewer candidates: 2 of 6 important unit(s)", out)  # init's REVIEW.md is a floor too
        self.assertEqual(self.grid(out, 10), [1, 1, 1])
        self.assertEqual(self.grid(out, 80), [1, 1, 1])
        listed = out.split("candidates within 10 line(s) and 1 file(s)")[1]
        self.assertRegex(listed, r"small\s+1 line\(s\), 1 file\(s\)")
        self.assertNotIn("big", listed)
        self.assertRegex(self.run_ok("--list-candidates", "100", "1"), r"big\s+100 line\(s\), 1 file\(s\)")

    def test_the_review_load_section_follows_the_draft_s_bands_and_kinds(self):
        self.change({"lib/small.py": "s\n"}, "small", "important")
        self.change({"lib/mid.py": "m\n" * 60}, "medium", "important")
        self.change({"lib/raised.py": "r\n"}, "raised", "critical")
        self.change({"core/x.py": "x\n"}, "small content critical", "critical")
        self.change({"engine/y.py": "y\n"}, "small code critical", "critical")
        out = self.run_ok("--list-candidates", "10", "1")  # the defaults: no medium band, every critical glob content
        self.assertRegex(out, r"important\s+4 unit\(s\)\s+small 2\s+medium 0\s+large 2\s+->\s+one merged reviewer 1, "
                              r"adversarial \+ conformance 0, three reviewers 3")  # the raised unit takes three
        self.assertIn("small critical units: 1, 0 of them in `critical code:` globs alone", out)
        draft = os.path.join(self.repo.tmp, "draft.md")
        with open(draft, "w", encoding="utf-8") as handle:
            handle.write("```review-slices\n%scritical code: engine/*\nmedium: 100 lines, 5 files\n```\n" % UNIT_RULES)
        out = self.run_ok("--rules", draft, "--list-candidates", "10", "1")
        self.assertIn("bands: small 40 lines, 3 files, medium 100 lines, 5 files", out)
        self.assertRegex(out, r"important\s+4 unit\(s\)\s+small 2\s+medium 1\s+large 1\s+->\s+one merged reviewer 1, "
                              r"adversarial \+ conformance 1, three reviewers 2")
        self.assertRegex(out, r"critical\s+2 unit\(s\)\s+small 2\s+medium 0\s+large 0\s+->\s+adversarial \+ "
                              r"conformance 1, three reviewers 1")
        self.assertIn("small critical units: 2, 1 of them in `critical code:` globs alone", out)
        self.assertRegex(out, r"small code critical\s+1 line\(s\), 1 file\(s\)\s+code")
        self.assertRegex(out, r"small content critical\s+1 line\(s\), 1 file\(s\)\s+content: core/x.py")

    def test_the_review_load_sizes_units_as_status_did(self):  # review: a net diff and a gitlink looked small
        repo = self.repo
        repo.git("checkout", "-q", "-b", "rewrite")
        for number in range(3):  # each commit rewrites the same 30 lines: status summed 150, the net diff is 30
            self.change({"lib/a.py": ("%d\n" % number) * 30}, "rewrite %d" % number)
        self.change({"lib/b.py": "b\n"}, "last", "important")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #1 from someone/rewrite", "rewrite")
        repo.git("update-index", "--add", "--cacheinfo", "160000,%s,lib/sub" % repo.out("rev-parse", "HEAD"))
        repo.git("commit", "-q", "-m", "bump a submodule", "-m", repo.trailer("important"))
        out = self.run_ok()
        self.assertRegex(out, r"important\s+3 unit\(s\)\s+small 0\s+medium 0\s+large 3\s+->\s+one merged reviewer 0")

    def test_a_partial_clone_is_never_fetched_into(self):  # review: git log -p fetched the missing blobs
        repo = self.repo
        self.change({"lib/a.py": "a\n"}, "a change", "important")
        repo.git("push", "-q", "origin", "main")
        Repo.run_git(repo.remote, "config", "uploadpack.allowFilter", "true")
        clone = os.path.join(repo.tmp, "partial")
        Repo.run_git(repo.tmp, "clone", "-q", "--no-checkout", "--filter=blob:none", "file://" + repo.remote, clone)

        def missing():
            return Repo.run_git(clone, "rev-list", "--objects", "--missing=print", "--all").stdout.count("\n?")

        before = missing()
        done = subprocess.run((sys.executable, CALIBRATE, "--rules", os.path.join(repo.path, "REVIEW.md")), cwd=clone,
                              capture_output=True, text=True, env=ENV, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("glob attribution", done.stdout)
        self.assertIn("note: this is a partial clone, so the review unit sections were skipped", done.stdout)
        self.assertGreater(before, 0)
        self.assertEqual(missing(), before)

    def test_list_candidates_wants_two_whole_numbers(self):
        for args in (("--list-candidates", "x", "1"), ("--list-candidates", "5")):
            done = calibrate(self.repo, *args)
            self.assertEqual(done.returncode, 2, args)
            self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
