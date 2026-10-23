"""The agent hook: block an agent's overrides in an opted-in clone, and never block anything else."""
import json
import os
import subprocess
import sys
import unittest

from support import ENV, SCRIPTS, SETUP, Repo, load_script

AGENT_HOOK = os.path.join(SCRIPTS, "agent_hook.py")


class AgentHookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holder = unittest.TestCase()
        cls.repo = Repo(cls.holder)
        cls.repo.install()

    @classmethod
    def tearDownClass(cls):
        cls.holder.doCleanups()

    def decide(self, tool_input, tool="Bash", repo=None, raw=None):
        repo = repo or self.repo
        payload = raw if raw is not None else json.dumps({"tool_name": tool, "tool_input": tool_input,
                                                          "cwd": repo.path, "hook_event_name": "PreToolUse"})
        done = subprocess.run((sys.executable, AGENT_HOOK), input=payload, capture_output=True, text=True,
                              cwd=repo.path, env=ENV)
        self.assertEqual(done.returncode, 0, done.stderr)
        if not done.stdout.strip():
            return None
        return json.loads(done.stdout)["hookSpecificOutput"]["permissionDecisionReason"]

    def assert_denied(self, command, word=""):
        reason = self.decide({"command": command})
        self.assertIsNotNone(reason, "not blocked: %s" % command)
        self.assertIn(word, reason)

    def assert_allowed(self, command):
        self.assertIsNone(self.decide({"command": command}), "blocked: %s" % command)

    def test_overrides_are_denied(self):
        for command in ("git push --no-verify origin main",
                        "git status && git push origin main --no-verify",
                        "cd sub; git -C .. push --no-verify",
                        "GIT_TRACE=1 git push --no-verify",
                        "sh -c 'git push --no-verify'",
                        "git commit --no-verify -m wip",
                        "git commit -anm wip",
                        "git -c core.hooksPath=/dev/null push",
                        "git -c hook.review-slices.command=true push",
                        "git config --unset hook.review-slices.command",
                        "git config --local review-slices.base origin/other",
                        "echo x >> .git/review-slices/suite-pass",
                        "rm -rf .git/review-slices",
                        "printf 'abc' | tee .git/hooks/pre-push"):
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_ordinary_work_is_allowed(self):
        for command in ("git push origin main",
                        "git commit -m \"git push --no-verify is the user's override\"",
                        "git -c trailer.ifexists=replace commit --amend --only --no-edit --trailer 'Review: x y'",
                        "git commit -m -n",
                        "git commit -m \"$(cat <<'EOF'\nDocs: never run git push --no-verify.\nEOF\n)\"",
                        "cat > notes.md <<EOF\ngit push --no-verify\nEOF",
                        "git config --get hook.review-slices.command",
                        "git config --list",
                        "cat .git/review-slices/suite-pass",
                        "python3 .githooks/review_slices.py run-suite",
                        "git log --grep=--no-verify",
                        "echo 'git push --no-verify'"):
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_edits_to_the_stamp_file_are_denied(self):
        stamp = os.path.join(self.repo.path, ".git", "review-slices", "suite-pass")
        self.assertIsNotNone(self.decide({"file_path": stamp, "content": "x"}, tool="Write"))
        self.assertIsNone(self.decide({"file_path": os.path.join(self.repo.path, "README.md")}, tool="Edit"))

    def test_codex_style_argument_lists_are_read(self):
        self.assertIsNotNone(self.decide({"command": ["bash", "-lc", "git push --no-verify"]}))
        self.assertIsNone(self.decide({"command": ["git", "status"]}))

    def test_a_clone_that_never_opted_in_is_left_alone(self):
        repo = Repo(self)
        reason = self.decide({"command": "git push --no-verify"}, repo=repo)
        self.assertIsNone(reason)

    def test_garbage_input_is_allowed(self):
        self.assertIsNone(self.decide(None, raw="this is not json"))


class AmendTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.repo.install()
        self.repo.write("core/a.py")
        self.repo.commit("reviewed", trailer=self.repo.trailer("critical"))

    def decide(self, command):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.repo.path})
        done = subprocess.run((sys.executable, AGENT_HOOK), input=payload, capture_output=True, text=True,
                              cwd=self.repo.path, env=ENV)
        return done.stdout.strip() or None

    def test_amending_new_content_into_a_reviewed_commit_is_denied(self):
        self.repo.write("core/b.py")
        self.repo.git("add", "core/b.py")
        self.assertIsNotNone(self.decide("git commit --amend --no-edit"))
        self.assertIsNotNone(self.decide("git commit -a --amend --no-edit"))

    def test_amending_only_the_message_is_allowed(self):
        self.repo.write("core/b.py")
        self.repo.git("add", "core/b.py")
        self.assertIsNone(self.decide('git commit --amend --only --no-edit --trailer "Review: critical abc"'))

    def test_amending_a_commit_without_a_trailer_is_allowed(self):
        self.repo.commit("not reviewed yet")
        self.repo.write("src/c.py")
        self.repo.git("add", "src/c.py")
        self.assertIsNone(self.decide("git commit --amend --no-edit"))


class SettingsTest(unittest.TestCase):
    def test_install_adds_the_hook_to_both_settings_files_and_keeps_what_is_there(self):
        repo = Repo(self)
        repo.write(".claude/settings.json", json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
        done = repo.setup("install", "--apply", "--agent-hooks")
        self.assertEqual(done.returncode, 0, done.stdout)
        with open(os.path.join(repo.path, ".claude", "settings.json"), encoding="utf-8") as handle:
            claude = json.load(handle)
        self.assertEqual(claude["permissions"], {"allow": ["Bash(ls)"]})
        command = claude["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("agent_hook.py", command)
        self.assertTrue(os.path.exists(os.path.join(repo.path, ".codex", "hooks.json")))
        self.assertTrue(os.path.exists(os.path.join(repo.path, ".githooks", "agent_hook.py")))
        self.assertIn("nothing to change", repo.setup("install", "--agent-hooks").stdout)
        decided = subprocess.run(("sh", "-c", command), input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "git push --no-verify"}, "cwd": repo.path}),
            capture_output=True, text=True, cwd=repo.path, env=dict(ENV, CLAUDE_PROJECT_DIR=repo.path))
        self.assertEqual(decided.returncode, 0)
        self.assertIn('"deny"', decided.stdout)

    def test_the_settings_command_allows_everything_where_the_hook_is_missing(self):
        repo = Repo(self)
        command = load_script("setup_tools", SETUP).AGENT_COMMAND
        done = subprocess.run(("sh", "-c", command), input="{}", capture_output=True, text=True, cwd=repo.path,
                              env=dict(ENV, CLAUDE_PROJECT_DIR=repo.path))
        self.assertEqual((done.returncode, done.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
