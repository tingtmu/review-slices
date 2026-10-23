"""Throwaway git repos for the guard's tests: a bare remote and a clone, isolated from the user's git config."""
import atexit
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "review-slices", "scripts")
GUARD = os.path.join(SCRIPTS, "review_slices.py")
SETUP = os.path.join(SCRIPTS, "setup_tools.py")

RULES = """\
test: true
base: main
default: simple
critical: core/*
important: REVIEW.md
trivial: notes/*
"""

ENV = {key: value for key, value in os.environ.items()
       if not key.startswith(("GIT_", "REVIEW_SLICES_", "PRE_COMMIT"))}
HOME = tempfile.mkdtemp(prefix="review-slices-home-")
atexit.register(shutil.rmtree, HOME, True)
# An empty HOME keeps the user's ~/.gitconfig and ~/.config/git/{ignore,attributes} out, on any git version.
ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", HOME=HOME,
           XDG_CONFIG_HOME=HOME)


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_guard():
    return load_script("review_slices", GUARD)


def git_version():
    out = subprocess.run(("git", "--version"), capture_output=True, text=True, env=ENV).stdout
    return tuple(int(part) for part in re.findall(r"\d+", out)[:2])


def review_md(rules=RULES):
    return "# Review rules\n\n```review-slices\n%s```\n" % rules


class Repo:
    """A clone at `path` whose `origin` is a bare repo; main holds REVIEW.md and the guard, already pushed."""

    def __init__(self, test, rules=RULES, guard=True):
        self.tmp = tempfile.mkdtemp(prefix="review-slices-test-")
        test.addCleanup(shutil.rmtree, self.tmp, True)
        self.remote = os.path.join(self.tmp, "remote.git")
        self.path = os.path.join(self.tmp, "work")
        self.run_git(self.tmp, "init", "-q", "--bare", "-b", "main", self.remote)
        self.run_git(self.tmp, "init", "-q", "-b", "main", self.path)
        for key, value in (("user.name", "Test"), ("user.email", "test@example.com"), ("commit.gpgsign", "false"),
                           ("tag.gpgsign", "false"), ("protocol.file.allow", "always")):
            self.git("config", key, value)
        self.git("remote", "add", "origin", self.remote)
        if rules is not None:
            self.write("REVIEW.md", review_md(rules))
        if guard:
            self.write(".githooks/review_slices.py", open(GUARD, encoding="utf-8").read())
        self.write("README.md", "start\n")
        self.commit("init")
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", "origin")

    @staticmethod
    def run_git(cwd, *args, check=True, env=None, input=None):
        done = subprocess.run(("git",) + args, cwd=cwd, capture_output=True, text=True, input=input,
                              env=dict(ENV, **(env or {})))
        if check and done.returncode != 0:
            raise AssertionError("git %s failed (%d):\n%s%s" % (" ".join(args), done.returncode, done.stdout,
                                                               done.stderr))
        return done

    def git(self, *args, check=True, env=None, input=None, cwd=None):
        return self.run_git(cwd or self.path, *args, check=check, env=env, input=input)

    def out(self, *args):
        return self.git(*args).stdout.strip()

    def write(self, relpath, text="x\n"):
        full = os.path.join(self.path, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(text)

    def remove(self, relpath):
        os.remove(os.path.join(self.path, relpath))

    def commit(self, message="change", trailer=None, all_files=True):
        if all_files:
            self.git("add", "-A")
        args = ["commit", "-q", "--allow-empty", "-m", message]
        if trailer:
            args += ["-m", trailer]
        self.git(*args)
        return self.out("rev-parse", "HEAD")

    def trailer(self, level, base=None):
        return "Review: %s %s" % (level, (base or self.out("rev-parse", "origin/main"))[:12])

    def guard(self, *args, input=None, env=None, cwd=None):
        """Run the skill's guard (not the repo's copy) in this repo."""
        return subprocess.run((sys.executable, GUARD) + args, cwd=cwd or self.path, capture_output=True,
                              text=True, input=input, env=dict(ENV, **(env or {})))

    def setup(self, *args, env=None):
        return subprocess.run((sys.executable, SETUP) + args, cwd=self.path, capture_output=True, text=True,
                              env=dict(ENV, **(env or {})))

    def install(self):
        """Wire this clone's pre-push to the guard, the way the version under test installs it."""
        if os.path.exists(SETUP):
            done = self.setup("install", "--apply")
            if done.returncode != 0:
                raise AssertionError("install failed:\n%s%s" % (done.stdout, done.stderr))
            return
        self.write(".githooks/pre-push", '#!/bin/sh\nexec python3 "$(dirname "$0")/review_slices.py" pre-push "$@"\n')
        os.chmod(os.path.join(self.path, ".githooks/pre-push"), 0o755)
        self.commit("install the pre-push hook")
        self.git("push", "-q", "origin", "main")
        self.git("config", "core.hooksPath", ".githooks")

    def run_suite(self):
        return self.guard("run-suite")

    def try_push(self, *args, env=None):
        """Push, returning the finished process; never raises."""
        return self.git("push", "-q", *(args or ("origin", "HEAD")), check=False, env=env)
