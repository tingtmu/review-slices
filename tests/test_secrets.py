"""The secret scan: REVIEW.md's `secrets: gitleaks` makes status, pre-push and ci scan the commits a push adds."""
import os
import random
import re
import shutil
import stat
import string
import subprocess
import sys
import tempfile
import unittest

from support import ENV, GUARD, RULES, SCRIPTS, Repo, review_md

SCANNER = os.path.join(SCRIPTS, "secret_scan.py")
SECRETS_RULES = RULES + "secrets: gitleaks\n"
FAKE = """#!/usr/bin/env python3
import os, sys
if sys.argv[1:2] == ["version"]:
    print(os.environ.get("FAKE_GITLEAKS_VERSION", "8.30.1"))
    sys.exit(0)
sys.stderr.write(os.environ.get("FAKE_GITLEAKS_STDERR", "") + "\\n")
sys.exit(int(os.environ.get("FAKE_GITLEAKS_EXIT", "0")))
"""
REAL = shutil.which("gitleaks", path=ENV.get("PATH"))


def token():
    """A GitHub token gitleaks recognises, made at run time so no secret is committed here."""
    return "ghp_" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(36))


def path_without_gitleaks():
    return os.pathsep.join(entry for entry in ENV.get("PATH", "").split(os.pathsep)
                           if entry and not os.path.exists(os.path.join(entry, "gitleaks")))


class SecretScanCase(unittest.TestCase):
    def make_repo(self, rules=SECRETS_RULES, scanner=True, env=None):
        """A wired clone whose main has the rules, the guard and (unless told not to) the scanner. ENV is for
        install, whose doctor run checks for gitleaks."""
        repo = Repo(self, rules=rules)
        if scanner:
            with open(SCANNER, encoding="utf-8") as handle:
                repo.write(".githooks/secret_scan.py", handle.read())
            repo.commit("add the scanner")
            repo.git("push", "-q", "origin", "main")
            repo.git("fetch", "-q", "origin")
        done = repo.setup("install", "--apply", env=env)
        if scanner:  # without the scanner, doctor rightly reports it missing
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        repo.git("switch", "-q", "-c", "work")
        return repo

    def commit_change(self, repo, path="app.py", text="x = 1\n", level="simple"):
        repo.write(path, text)
        return repo.commit("change " + path, trailer=repo.trailer(level))

    def push(self, repo, env=None):
        done = repo.run_suite()
        self.assertEqual(done.returncode, 0, done.stderr)
        return repo.try_push("origin", "HEAD", env=env)

    def assert_refused(self, done, *words):
        self.assertNotEqual(done.returncode, 0, "push went through:\n" + done.stderr)
        for word in words:
            self.assertIn(word, done.stderr)

    def assert_pushed(self, done):
        self.assertEqual(done.returncode, 0, "push refused:\n" + done.stderr)


class FakeGitleaksTest(SecretScanCase):
    """Each way the scan can pass or refuse, with a stand-in gitleaks."""

    def setUp(self):
        self.bin = tempfile.mkdtemp(prefix="review-slices-fake-gitleaks-")
        self.addCleanup(shutil.rmtree, self.bin, True)
        fake = os.path.join(self.bin, "gitleaks")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE.replace("/usr/bin/env python3", sys.executable, 1))
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)

    def fake(self, exit_code=0, stderr="1 commits scanned."):
        return {"PATH": self.bin + os.pathsep + ENV.get("PATH", ""), "FAKE_GITLEAKS_EXIT": str(exit_code),
                "FAKE_GITLEAKS_STDERR": stderr}

    def test_without_the_line_nothing_is_scanned(self):
        repo = self.make_repo(rules=RULES, env=self.fake())
        self.commit_change(repo)
        missing = {"PATH": path_without_gitleaks()}
        self.assertIn("secrets: not scanned", repo.guard("status", env=missing).stdout)
        self.assert_pushed(self.push(repo, env=missing))

    def test_a_clean_scan_lets_the_push_go(self):
        repo = self.make_repo(env=self.fake())
        self.commit_change(repo)
        self.assertIn("none found in 1 commit(s)", repo.guard("status", env=self.fake()).stdout)
        self.assert_pushed(self.push(repo, env=self.fake()))

    def test_a_missing_gitleaks_refuses(self):
        repo = self.make_repo(env=self.fake())
        self.commit_change(repo)
        self.assert_refused(self.push(repo, env={"PATH": path_without_gitleaks()}), "gitleaks is not installed")

    def test_a_failed_scan_refuses_in_status_and_pre_push_alike(self):
        repo = self.make_repo(env=self.fake())
        self.commit_change(repo)
        env = self.fake(exit_code=1, stderr="fatal: something broke")
        status = repo.guard("status", env=env).stdout
        self.assertIn("secrets: the secret scan failed (gitleaks exit 1)", status)
        self.assertIn("next: deal with the secret scan before review", status)
        self.assert_refused(self.push(repo, env=env), "the secret scan failed (gitleaks exit 1)")

    def test_a_scan_that_read_nothing_refuses(self):
        repo = self.make_repo(env=self.fake())
        self.commit_change(repo)
        self.assert_refused(self.push(repo, env=self.fake(stderr="0 commits scanned.")), "read no commits")

    def test_an_old_gitleaks_refuses(self):
        repo = self.make_repo(env=self.fake())
        self.commit_change(repo)
        self.assert_refused(self.push(repo, env=dict(self.fake(), FAKE_GITLEAKS_VERSION="8.18.4")),
                            "older than 8.19.0")

    def test_the_change_s_own_scanner_does_not_judge_it(self):
        repo = self.make_repo(env=self.fake())
        self.commit_change(repo, ".githooks/secret_scan.py", "def scan(*args):\n    return [], []\n", "important")
        self.assert_refused(self.push(repo, env=self.fake(exit_code=1)), "the secret scan failed")

    def test_a_broken_scanner_on_the_base_refuses_by_name(self):
        repo = self.make_repo(env=self.fake())
        repo.git("switch", "-q", "main")
        repo.write(".githooks/secret_scan.py", "def nothing():\n    pass\n")
        repo.commit("break the scanner")
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.git("fetch", "-q", "origin")
        repo.git("switch", "-q", "-C", "work")
        self.commit_change(repo)
        done = self.push(repo, env=self.fake())
        self.assert_refused(done, ".githooks/secret_scan.py at", "did not run")
        self.assertNotIn("Traceback", done.stderr)

    def test_a_base_with_the_guard_but_no_scanner_refuses(self):
        repo = self.make_repo(scanner=False, env=self.fake())
        self.commit_change(repo)
        self.assert_refused(self.push(repo, env=self.fake()), "has no .githooks/secret_scan.py", "ask the user")

    def test_a_base_that_lost_its_guard_keeps_judging_with_its_last_scanner(self):
        repo = self.make_repo(env=self.fake())
        repo.git("switch", "-q", "main")
        repo.git("rm", "-q", ".githooks/review_slices.py", ".githooks/secret_scan.py")
        repo.commit("lose the guard")
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.git("fetch", "-q", "origin")
        repo.git("switch", "-q", "-C", "work")
        repo.write(".githooks/secret_scan.py", "def scan(*args):\n    return [], []\n")
        repo.commit("a friendlier scanner", trailer=repo.trailer("important"))
        self.assert_refused(self.push(repo, env=self.fake(exit_code=1)), "the secret scan failed")

    def test_adoption_scans_with_the_push_s_own_scanner(self):
        repo = Repo(self, rules=None, guard=False)
        repo.git("config", "review-slices.base", "origin/main")
        repo.setup("install", "--apply", env=self.fake())  # exits 1: the new guard copy is not committed yet
        repo.write("REVIEW.md", review_md(SECRETS_RULES))
        with open(SCANNER, encoding="utf-8") as handle:
            repo.write(".githooks/secret_scan.py", handle.read())
        repo.commit("adopt review-slices", trailer=repo.trailer("important"))
        done = self.push(repo, env=self.fake(exit_code=1))
        self.assert_refused(done, "this checkout's guard runs", "the secret scan failed")

    def test_unreadable_rules_keep_a_declared_scan_on(self):
        broken = "```review-slices\n" + SECRETS_RULES  # the closing fence is gone
        for text, scanned in ((review_md(SECRETS_RULES + "not a rule\n"), True), (broken, True),
                              (review_md(SECRETS_RULES).replace("```review-slices", "```review-slices yaml"), True),
                              (review_md(RULES + "# secrets: gitleaks\nnot a rule\n"), False)):
            with self.subTest(text=text):
                repo = self.make_repo(env=self.fake())
                repo.git("switch", "-q", "main")
                repo.write("REVIEW.md", text)
                repo.commit("break the rules")
                repo.git("push", "-q", "--no-verify", "origin", "main")
                repo.git("fetch", "-q", "origin")
                repo.git("switch", "-q", "-C", "work")
                self.commit_change(repo)
                done = repo.try_push("origin", "HEAD", env=self.fake(exit_code=1))
                self.assertIn("does not parse", done.stderr)
                (self.assertIn if scanned else self.assertNotIn)("the secret scan failed", done.stderr)


class RealGitleaksTest(SecretScanCase):
    """The scan against the real gitleaks: what it must catch, and what it must not flag."""

    def setUp(self):
        if not REAL:
            if os.environ.get("REQUIRE_GITLEAKS") == "1":
                self.fail("REQUIRE_GITLEAKS=1, but gitleaks is not on PATH")
            self.skipTest("gitleaks is not installed")

    def push_main(self, repo, path, text):
        """A change on main that is already published, pushed past the hook as another clone would."""
        repo.git("switch", "-q", "main")
        repo.write(path, text)
        repo.commit("main moves")
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.git("fetch", "-q", "origin")
        repo.git("switch", "-q", "work")

    def ci(self, repo, base, head):
        return subprocess.run((sys.executable, GUARD, "ci", base, head), cwd=repo.path, capture_output=True,
                              text=True, env=ENV)

    def test_a_secret_added_then_removed_is_refused_and_never_printed(self):
        repo = self.make_repo()
        published, leaked = token(), token()
        self.push_main(repo, "old.py", "old = %r\n" % published)
        self.commit_change(repo, "leak.py", "key = %r\n" % leaked)
        repo.remove("leak.py")
        repo.commit("remove it", trailer=repo.trailer("simple"))
        done = self.push(repo)
        self.assert_refused(done, "github-pat at leak.py:1")
        self.assertNotIn("old.py", done.stderr)
        status = repo.guard("status").stdout
        self.assertIn("github-pat at leak.py:1", status)
        output = done.stdout + done.stderr + status
        self.assertNotIn(leaked, output)
        self.assertNotIn(leaked[4:20], output)

    def test_a_secret_in_a_conflict_resolution_is_refused(self):
        repo = self.make_repo()
        self.commit_change(repo, "a.txt", "work\n")
        self.push_main(repo, "a.txt", "main\n")
        repo.git("merge", "-q", "origin/main", check=False)
        repo.write("a.txt", "resolved = %r\n" % token())
        repo.git("add", "a.txt")
        repo.git("commit", "-q", "--no-edit", "-m", "merge main", "-m", repo.trailer("simple"))
        self.assert_refused(self.push(repo), "a.txt")

    def test_merging_main_s_published_secret_is_not_flagged(self):
        repo = self.make_repo()
        self.commit_change(repo, "f.txt", "work\n")
        self.push_main(repo, "main.py", "published = %r\n" % token())
        repo.git("merge", "-q", "--no-edit", "origin/main")
        repo.git("config", "format.pretty", "oneline")  # a clean push is read whatever log's format
        self.assert_pushed(self.push(repo))

    def test_settings_attributes_and_markers_do_not_hide_a_secret(self):
        repo = self.make_repo()
        for key, value in (("color.ui", "always"), ("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"),
                           ("log.abbrevCommit", "true")):
            repo.git("config", key, value)
        repo.write(".gitattributes", "leak.py -diff\n")
        repo.write(".git/info/attributes", "leak.py -diff\n")  # read even where no working tree is
        self.commit_change(repo, "leak.py", "key = %r  # gitleaks:allow\n" % token())
        with open(os.path.join(repo.path, ".git", "info", "exclude"), "a", encoding="utf-8") as handle:
            handle.write(".gitleaks.toml\n.gitleaksignore\n")
        repo.write(".gitleaks.toml", '[extend]\nuseDefault = true\n[allowlist]\npaths = [".*"]\n')
        first = self.push(repo)
        self.assert_refused(first, "github-pat at leak.py:1")
        fingerprint = re.search(r"fingerprint (\S+)", first.stderr).group(1)
        self.assertRegex(fingerprint, r"^[0-9a-f]{40}:")
        repo.write(".gitleaksignore", fingerprint + "\n")
        repo.write(".git/.gitleaksignore", fingerprint + "\n")
        self.assert_refused(repo.try_push("origin", "HEAD"), "github-pat at leak.py:1")

    def test_only_a_committed_fingerprint_with_its_commit_allows_a_finding(self):
        repo = self.make_repo()
        base = repo.out("rev-parse", "origin/main")
        head = self.commit_change(repo, "leak.py", "key = %r\n" % token())
        done = self.ci(repo, base, head)
        self.assertEqual(done.returncode, 1, done.stdout)
        fingerprint = re.search(r"fingerprint (\S+)", done.stdout).group(1)
        self.assertTrue(fingerprint.startswith(head + ":"), fingerprint)
        head = self.commit_change(repo, ".gitleaksignore", fingerprint.split(":", 1)[1] + "\n", "important")
        done = self.ci(repo, base, head)
        self.assertIn("github-pat at leak.py:1", done.stdout)
        self.assertIn("lines without a commit do not apply", done.stdout)
        head = self.commit_change(repo, ".gitleaksignore", "# a test value, not a key\n%s\n" % fingerprint,
                                  "important")
        done = self.ci(repo, base, head)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("none found", done.stdout)


if __name__ == "__main__":
    unittest.main()
