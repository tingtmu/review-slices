"""The pre-push guard: a push needs a pass stamp and review trailers that cover its new commits."""
import os
import shutil
import subprocess
import unittest

from support import ENV, RULES, Repo, review_md


class PrePushTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.repo.install()

    def assert_refused(self, done, *words):
        self.assertNotEqual(done.returncode, 0, "push went through:\n" + done.stderr)
        for word in words:
            self.assertIn(word, done.stderr)

    def assert_pushed(self, done):
        self.assertEqual(done.returncode, 0, "push refused:\n" + done.stderr)

    def suite(self):
        self.suite_in(self.repo)

    def suite_in(self, repo):
        done = repo.run_suite()
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_refuses_an_unreviewed_critical_change(self):
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("core change")
        self.suite()
        self.assert_refused(repo.try_push(), "critical", "core/a.py")

    def test_accepts_a_covering_trailer_and_a_stamp(self):
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("core change", trailer=repo.trailer("critical"))
        self.suite()
        self.assert_pushed(repo.try_push())

    def test_refuses_without_a_pass_stamp(self):
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("core change", trailer=repo.trailer("critical"))
        self.assert_refused(repo.try_push(), "run-suite")

    def test_refuses_a_trailer_below_the_level(self):
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("core change", trailer=repo.trailer("simple"))
        self.suite()
        self.assert_refused(repo.try_push(), "critical")

    def test_work_after_the_last_trailer_needs_a_new_trailer(self):
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("reviewed", trailer=repo.trailer("critical"))
        repo.write("src/b.py")
        repo.commit("not reviewed")
        self.suite()
        self.assert_refused(repo.try_push(), "src/b.py")

    def test_trivial_work_after_a_trailer_needs_no_trailer(self):
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("reviewed", trailer=repo.trailer("critical"))
        repo.write("notes/n.md")
        repo.commit("notes")
        self.suite()
        self.assert_pushed(repo.try_push())

    def test_a_remote_this_clone_has_not_fetched_is_refused(self):
        repo = self.repo
        other = os.path.join(repo.tmp, "other")
        repo.run_git(repo.tmp, "clone", "-q", repo.remote, other)
        for args in (("-c", "user.name=O", "-c", "user.email=o@e", "commit", "-q", "--allow-empty", "-m", "x"),
                     ("push", "-q", "--no-verify", "origin", "main")):
            repo.run_git(other, *args)
        repo.write("notes/n.md")
        repo.commit("notes")
        self.suite()
        self.assert_refused(repo.try_push("--force", "origin", "HEAD"), "does not have")

    def test_a_dashed_line_in_the_message_keeps_the_trailer(self):  # H17
        repo = self.repo
        repo.write("core/a.py")
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", "title", "-m", "notes\n---\nmore notes", "-m", repo.trailer("critical"))
        self.suite()
        self.assert_pushed(repo.try_push())

    def test_a_merge_that_drops_main_s_change_needs_review(self):  # H15
        repo = self.repo
        repo.write("core/a.py", "one\n1\n2\n3\n4\ntwo\n")
        repo.commit("base", trailer=repo.trailer("critical"))
        self.suite()
        self.assert_pushed(repo.try_push("origin", "main"))
        repo.git("switch", "-q", "-c", "feature")
        repo.write("core/a.py", "one\n1\n2\n3\n4\nTWO\n")
        repo.commit("feature edit", trailer=repo.trailer("critical"))
        self.suite()
        self.assert_pushed(repo.try_push("-u", "origin", "feature"))
        repo.git("switch", "-q", "main")
        repo.write("core/a.py", "ONE\n1\n2\n3\n4\ntwo\n")
        repo.commit("main edit", trailer=repo.trailer("critical"))
        self.suite()
        self.assert_pushed(repo.try_push("origin", "main"))
        repo.git("switch", "-q", "feature")
        repo.git("merge", "-q", "--no-commit", "main")
        repo.git("checkout", "HEAD", "--", "core/a.py")
        repo.git("commit", "-q", "--no-edit")
        self.suite()
        self.assert_refused(repo.try_push("origin", "feature"), "core/a.py")

    @unittest.expectedFailure  # H2
    def test_a_clean_merge_of_main_needs_no_review(self):
        repo = self.repo
        repo.write("core/a.py", "one\n1\n2\n3\n4\ntwo\n")
        repo.commit("base", trailer=repo.trailer("critical"))
        self.suite()
        self.assert_pushed(repo.try_push("origin", "main"))
        repo.git("switch", "-q", "-c", "feature")
        repo.write("core/a.py", "one\n1\n2\n3\n4\nTWO\n")
        repo.commit("feature edit", trailer=repo.trailer("critical"))
        self.suite()
        self.assert_pushed(repo.try_push("-u", "origin", "feature"))
        repo.git("switch", "-q", "main")
        repo.write("core/a.py", "ONE\n1\n2\n3\n4\ntwo\n")
        repo.commit("main edit", trailer=repo.trailer("critical"))
        self.suite()
        self.assert_pushed(repo.try_push("origin", "main"))
        repo.git("switch", "-q", "feature")
        repo.git("merge", "-q", "--no-edit", "main")
        self.suite()
        self.assert_pushed(repo.try_push("origin", "feature"))

    @unittest.expectedFailure  # H2
    def test_merging_main_into_a_branch_does_not_ask_to_review_main(self):
        repo = self.repo
        repo.git("switch", "-q", "-c", "feature")
        repo.write("src/f.py")
        repo.commit("f1", trailer=repo.trailer("simple"))
        self.suite()
        self.assert_pushed(repo.try_push("-u", "origin", "feature"))
        repo.git("switch", "-q", "main")
        repo.write("core/a.py")
        repo.commit("a teammate's change, without a trailer")
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.git("switch", "-q", "feature")
        repo.git("merge", "-q", "--no-edit", "main")
        repo.write("src/g.py")
        repo.commit("f2", trailer=repo.trailer("simple"))
        self.suite()
        self.assert_pushed(repo.try_push("origin", "feature"))

    def test_a_tag_push_is_checked(self):  # H6
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("unreviewed")
        self.suite()
        repo.git("tag", "v1")
        self.assert_refused(repo.try_push("origin", "v1"), "critical")

    def test_an_annotated_tag_is_checked(self):
        repo = self.repo
        repo.write("core/a.py")
        repo.commit("unreviewed")
        self.suite()
        repo.git("tag", "-a", "-m", "release", "v2")
        self.assert_refused(repo.try_push("origin", "v2"), "critical")

    def test_a_tag_on_pushed_work_needs_nothing(self):
        repo = self.repo
        repo.git("tag", "v0")
        self.assert_pushed(repo.try_push("origin", "v0"))

    def test_a_push_that_deletes_review_md_is_refused(self):
        repo = self.repo
        repo.git("rm", "-q", "REVIEW.md")
        repo.commit("drop the rules", trailer=repo.trailer("critical"))
        self.assert_refused(repo.try_push(), "deletes or moves REVIEW.md")

    @unittest.expectedFailure  # 0.3.0: with core.hooksPath=.githooks, a checkout without .githooks runs no hook
    def test_a_branch_from_before_adoption_is_not_checked(self):
        repo = self.repo
        repo.git("switch", "-q", "--orphan", "old")
        repo.write("legacy.txt")
        repo.commit("an old line of work, before the rules existed")
        repo.write("core/b.py")
        repo.commit("a backport")
        done = repo.try_push("origin", "old")
        self.assert_pushed(done)
        self.assertIn("not checked", done.stderr)

    def test_a_suite_change_is_reported_on_push(self):
        repo = self.repo
        repo.write("REVIEW.md", review_md(RULES.replace("test: true", "test: echo weaker")))
        repo.commit("weaker suite", trailer=repo.trailer("important"))
        self.suite()
        done = repo.try_push()
        self.assert_pushed(done)
        self.assertIn("echo weaker", done.stderr)

    def test_a_deleted_review_md_does_not_switch_the_guard_off(self):  # H7
        repo = self.repo
        repo.git("rm", "-q", "REVIEW.md")
        repo.commit("drop the rules")
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.write("core/a.py")
        repo.commit("unreviewed")
        repo.run_suite()
        self.assert_refused(repo.try_push(), "REVIEW.md")

    def test_broken_rules_on_main_do_not_block_their_own_fix(self):  # H8
        repo = self.repo
        repo.write("REVIEW.md", review_md(RULES.replace("critical:", "Critical:")))
        repo.commit("a typo in the rules")
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.write("REVIEW.md", review_md())
        repo.commit("fix the typo", trailer=repo.trailer("critical"))
        self.suite()
        self.assert_pushed(repo.try_push())

    def test_a_signed_commit_keeps_its_trailer_under_log_show_signature(self):  # H9
        if not shutil.which("ssh-keygen"):
            self.skipTest("ssh-keygen not installed")
        repo = self.repo
        key = os.path.join(repo.tmp, "key")
        subprocess.run(("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", key), check=True,
                       env=ENV, capture_output=True)
        signers = os.path.join(repo.tmp, "allowed_signers")
        with open(key + ".pub", encoding="utf-8") as pub, open(signers, "w", encoding="utf-8") as out:
            out.write("test@example.com " + pub.read())
        for setting in (("gpg.format", "ssh"), ("user.signingkey", key), ("gpg.ssh.allowedSignersFile", signers),
                        ("log.showSignature", "true")):
            repo.git("config", *setting)
        repo.write("core/a.py")
        repo.git("add", "-A")
        repo.git("commit", "-q", "-S", "-m", "signed", "-m", repo.trailer("critical"))
        self.suite()
        self.assert_pushed(repo.try_push())

    @unittest.expectedFailure  # H16
    def test_an_existing_hook_keeps_running_beside_the_guard(self):
        repo = Repo(self)
        marker = os.path.join(repo.tmp, "lfs-ran")
        hook = repo.out("rev-parse", "--path-format=absolute", "--git-path", "hooks/pre-push")
        with open(hook, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\ncat > '%s'\n" % marker)
        os.chmod(hook, 0o755)
        repo.install()
        if os.path.exists(marker):
            os.remove(marker)  # only the push below counts
        repo.write("core/a.py")
        repo.commit("unreviewed")
        self.suite_in(repo)
        self.assert_refused(repo.try_push(), "critical")
        with open(marker, encoding="utf-8") as handle:
            self.assertIn("refs/heads/main", handle.read())

    @unittest.expectedFailure  # H10
    def test_an_edited_guard_does_not_judge_its_own_push(self):
        repo = self.repo
        path = os.path.join(repo.path, ".githooks", "review_slices.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        repo.write(".githooks/review_slices.py", source.replace("def main(argv):\n", "def main(argv):\n    return 0\n", 1))
        repo.write("core/a.py")
        repo.commit("unreviewed, with a friendlier guard")
        self.suite()
        self.assert_refused(repo.try_push(), "critical")


if __name__ == "__main__":
    unittest.main()
