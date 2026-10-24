"""The agent hook: block an agent's overrides in an opted-in clone, and never block anything else."""
import json
import os
import subprocess
import sys
import unittest

from support import ENV, SCRIPTS, SETUP, Repo, load_script

AGENT_HOOK = os.path.join(SCRIPTS, "agent_hook.py")
CODEX_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "codex_pre_tool_use.json")


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
                        "printf 'abc' | tee .git/hooks/pre-push",
                        "timeout 120 git push --no-verify origin main",
                        "nice git push --no-verify",
                        "env -u GIT_TRACE git push --no-verify",
                        "echo main | xargs -n 1 git push --no-verify origin",
                        "git -c alias.p='push --no-verify' p",
                        "git config alias.p 'push --no-verify'",
                        "sed -i 's/a/b/' .git/review-slices/suite-pass"):
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
                        "echo 'git push --no-verify'",
                        "echo git push --no-verify",
                        "git config core.hooksPath",
                        "git config alias.st status",
                        "sed -n 1p .git/review-slices/suite-pass",
                        "timeout 60 git push origin main"):
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

    def test_staging_and_amending_in_one_command_is_denied(self):
        self.repo.write("core/b.py")
        self.assertIsNotNone(self.decide("git add -A && git commit --amend --no-edit"))
        self.assertIsNotNone(self.decide("git commit --amend -m 'reworded'"))

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

    def test_the_settings_command_runs_the_base_branch_copy_not_an_edited_one(self):
        repo = Repo(self)
        self.assertEqual(repo.setup("install", "--apply", "--agent-hooks").returncode, 0)
        repo.commit("add the agent hook")
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.git("fetch", "-q")
        repo.write(".githooks/agent_hook.py", "import sys\nsys.exit(0)\n")
        command = load_script("setup_tools", SETUP).AGENT_COMMAND
        decided = subprocess.run(("sh", "-c", command), input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "git push --no-verify"}, "cwd": repo.path}),
            capture_output=True, text=True, cwd=repo.path, env=dict(ENV, CLAUDE_PROJECT_DIR=repo.path))
        self.assertIn('"deny"', decided.stdout)

    def test_install_replaces_an_older_agent_hook_entry(self):
        repo = Repo(self)
        old = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python3 .githooks/agent_hook.py || true"}]}]}}
        repo.write(".claude/settings.json", json.dumps(old))
        self.assertEqual(repo.setup("install", "--apply", "--agent-hooks").returncode, 0)
        with open(os.path.join(repo.path, ".claude", "settings.json"), encoding="utf-8") as handle:
            entries = json.load(handle)["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 1)

    def test_a_recorded_codex_payload_gets_the_reply_codex_honoured(self):
        with open(CODEX_FIXTURE, encoding="utf-8") as handle:
            fixture = json.load(handle)
        repo = Repo(self)
        self.assertEqual(repo.setup("install", "--apply", "--agent-hooks").returncode, 0)
        repo.commit("add the agent hook")
        repo.git("push", "-q", "--no-verify", "origin", "main")
        repo.git("fetch", "-q")
        # The reply can only come from the base branch's copy, the one Codex ran live.
        repo.write(".githooks/agent_hook.py", "import sys\nsys.exit(0)\n")
        with open(os.path.join(repo.path, ".codex", "hooks.json"), encoding="utf-8") as handle:
            command = json.load(handle)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        payload = dict(fixture["payload"], cwd=repo.path)
        # Codex sets no CLAUDE_PROJECT_DIR; the command falls back to the directory Codex runs it in.
        env = {key: value for key, value in ENV.items() if key != "CLAUDE_PROJECT_DIR"}
        decided = subprocess.run(("sh", "-c", command), input=json.dumps(payload), capture_output=True, text=True,
                                 cwd=repo.path, env=env)
        self.assertEqual(json.loads(decided.stdout), fixture["response"])

    def test_the_settings_command_judges_the_project_even_when_the_agent_is_elsewhere(self):
        repo = Repo(self)
        self.assertEqual(repo.setup("install", "--apply", "--agent-hooks").returncode, 0)
        command = load_script("setup_tools", SETUP).AGENT_COMMAND
        for agent_command in ("git -C %s push --no-verify" % repo.path, "cd %s && git push --no-verify" % repo.path):
            decided = subprocess.run(("sh", "-c", command), input=json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": agent_command}, "cwd": "/"}),
                capture_output=True, text=True, cwd=repo.path, env=dict(ENV, CLAUDE_PROJECT_DIR=repo.path))
            self.assertIn('"deny"', decided.stdout, agent_command)

    def test_settings_of_the_wrong_shape_are_reported_not_crashed_on(self):
        repo = Repo(self)
        repo.write(".claude/settings.json", '{"hooks": []}')
        done = repo.setup("install", "--agent-hooks")
        self.assertNotIn("Traceback", done.stderr)
        self.assertIn("not valid JSON", done.stdout)

    def test_a_broken_hook_allows_and_says_why(self):
        done = subprocess.run((sys.executable, AGENT_HOOK), input="[]", capture_output=True, text=True,
                              env=ENV)
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertIn("review-slices agent hook", done.stderr)

    def test_the_settings_command_allows_everything_where_the_hook_is_missing(self):
        repo = Repo(self)
        command = load_script("setup_tools", SETUP).AGENT_COMMAND
        done = subprocess.run(("sh", "-c", command), input="{}", capture_output=True, text=True, cwd=repo.path,
                              env=dict(ENV, CLAUDE_PROJECT_DIR=repo.path))
        self.assertEqual((done.returncode, done.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
