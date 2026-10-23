"""discover.py: list the offline checks a repo already has, and try the local ones with --run."""
import os
import re
import subprocess
import sys
import time
import unittest

from support import ENV, SCRIPTS, Repo

DISCOVER = os.path.join(SCRIPTS, "discover.py")
PYTHON = sys.executable
THIS_OS = {"linux": ("ubuntu-latest", "linux"), "darwin": ("macos-latest", "macos")}.get(sys.platform)
ROW = re.compile(r"  (\S+:\d+)\s+(\w+)\s+(.*)  \[(.*)\]$")

WORKFLOW = """\
name: CI
on: [push]
env:
  LANG: C
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e .
      - name: Tests
        run: |
          cd engine
          FOO=1 pytest -q \\
            --maxfail=1
          # a comment
          echo done
      - run: ruff check .  # lint
        working-directory: src
  db:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres
    steps:
      - run: make integration
  ship:
    runs-on: ubuntu-latest
    steps:
      - name: Build
        run: cargo build --release
      - name: Push the image
        run: docker push example/app
      - run: ./scripts/smoke.sh
        env:
          TOKEN: ${{ secrets.TOKEN }}
      - run: pytest --python ${{ matrix.python }}
"""


def discover(repo, *args, cwd=None):
    env = dict(ENV, GIT_CEILING_DIRECTORIES=os.path.dirname(repo.tmp))
    return subprocess.run((PYTHON, DISCOVER) + args, cwd=cwd or repo.path, capture_output=True, text=True,
                          env=env, timeout=120)


def rows(done):
    """{command: (place, kind, where)} of discover's listing."""
    found = {}
    for line in done.stdout.splitlines():
        match = ROW.match(line)
        if match:
            found[match.group(3)] = (match.group(1), match.group(2), match.group(4))
    return found


def section(out, heading):
    """The indented lines under the section of OUT whose heading starts with HEADING."""
    lines = out.split("\n" + heading, 1)[1].split("\n\n")[0].splitlines()[1:] if "\n" + heading in out else []
    return [line.strip() for line in lines]


class ListTest(unittest.TestCase):
    def listing(self, repo):
        done = discover(repo)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Nothing was run", done.stdout)
        return rows(done)

    def test_workflow_run_lines_and_blocks(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml", WORKFLOW)
        found = self.listing(repo)
        self.assertEqual(found["cd engine && FOO=1 pytest -q --maxfail=1"],
                         (".github/workflows/ci.yml:14", "test", "local"))
        self.assertEqual(found["cd src && ruff check ."], (".github/workflows/ci.yml:18", "lint", "local"))
        self.assertEqual(found["cargo build --release"][2], "local")
        self.assertFalse([command for command in found if "pip install" in command or "echo" in command])

    def test_workflow_remote_reasons(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml", WORKFLOW)
        found = self.listing(repo)
        self.assertEqual(found["make integration"][2], "remote: needs services")
        self.assertEqual(found["docker push example/app"][2], "remote: deploys or publishes (Push)")
        self.assertEqual(found["./scripts/smoke.sh"][2], "remote: uses secrets")
        self.assertEqual(found["pytest --python ${{ matrix.python }}"][2], "remote: needs CI values")

    def test_secrets_in_the_job_env_make_every_step_remote(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml", "jobs:\n  t:\n    env:\n      KEY: ${{ secrets.KEY }}\n"
                                               "    steps:\n      - run: pytest\n")
        self.assertEqual(self.listing(repo)["pytest"][2], "remote: uses secrets")

    @unittest.skipIf(sys.platform == "win32", "windows-latest is this OS")
    def test_a_job_only_for_another_os_is_remote(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml", "jobs:\n  win:\n    runs-on: windows-latest\n    steps:\n"
                                               "    - run: cargo test\n")
        self.assertEqual(self.listing(repo)["cargo test"][2], "remote: runs only on windows")

    @unittest.skipIf(THIS_OS is None, "needs a Linux or macOS runner label for this OS")
    def test_a_matrix_with_this_os_stays_local_and_names_the_other_legs(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml",
                   "jobs:\n  t:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        os:\n"
                   "          - %s\n          - windows-latest\n    steps:\n      - run: pytest\n" % THIS_OS[0])
        self.assertEqual(self.listing(repo)["pytest"][2], "local; the CI matrix also runs it on windows")

    def test_gitlab_script(self):
        repo = Repo(self)
        repo.write(".gitlab-ci.yml", "stages: [test, deploy]\nlint:\n  stage: test\n  script:\n    - npm ci\n"
                                     "    - npm run lint\n    - |\n      echo hi\n      make check\n"
                                     "release_job:\n  stage: deploy\n  script: ./ship.sh\n")
        found = self.listing(repo)
        self.assertEqual(found["npm run lint"], (".gitlab-ci.yml:6", "lint", "local"))
        self.assertEqual(found["make check"], (".gitlab-ci.yml:9", "other", "local"))
        self.assertTrue(found["./ship.sh"][2].startswith("remote: deploys or publishes"))
        self.assertNotIn("npm ci", found)

    def test_package_json_scripts_use_the_lockfiles_runner(self):
        repo = Repo(self)
        repo.write("package.json", '{\n  "name": "x",\n  "scripts": {\n    "start": "node .",\n'
                                   '    "test": "jest",\n    "check": "tsc --noEmit",\n'
                                   '    "format:check": "prettier --check ."\n  }\n}\n')
        repo.write("pnpm-lock.yaml", "")
        found = self.listing(repo)
        self.assertEqual(found["pnpm run test"], ("package.json:5", "test", "local"))
        self.assertEqual(found["pnpm run check"][1], "types")
        self.assertEqual(found["pnpm run format:check"][1], "format")
        self.assertNotIn("pnpm run start", found)

    def test_an_invalid_package_json_is_skipped_with_a_note(self):
        repo = Repo(self)
        repo.write("package.json", "{not json")
        repo.write("go.mod", "module x\n")
        done = discover(repo)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("package.json is not valid JSON", done.stderr)
        self.assertIn("go test ./...", rows(done))

    def test_make_and_just_targets(self):
        repo = Repo(self)
        repo.write("Makefile", ".PHONY: test lint\nX := 1\ntest lint: deps\n\tpytest\nbuild:\n\tcc x.c\n"
                               "deploy:\n\t./ship\n")
        repo.write("justfile", "set shell := [\"bash\"]\n@typecheck:\n    mypy .\ncheck *ARGS:\n    true\n")
        found = self.listing(repo)
        self.assertEqual(found["make test"], ("Makefile:3", "test", "local"))
        self.assertEqual(found["make lint"], ("Makefile:3", "lint", "local"))
        self.assertEqual(found["make build"], ("Makefile:5", "build", "local"))
        self.assertEqual(found["just typecheck"], ("justfile:2", "types", "local"))
        self.assertEqual(found["just check"], ("justfile:4", "other", "local"))
        self.assertNotIn("make deploy", found)

    def test_pyproject_sections_and_marker_files(self):
        repo = Repo(self)
        repo.write("pyproject.toml", "[project]\nname = 'x'\n[tool.pytest.ini_options]\n[tool.ruff.lint]\n"
                                     "[tool.mypy]\n[tool.black]\n[tool.coverage]\n")
        repo.write("uv.lock", "")
        for name in ("tox.ini", "noxfile.py", ".pre-commit-config.yaml", "Cargo.toml", "go.mod"):
            repo.write(name, "")
        found = self.listing(repo)
        self.assertEqual(found["uv run pytest"], ("pyproject.toml:3", "test", "local"))
        self.assertEqual(found["uv run ruff check ."][1], "lint")
        self.assertEqual(found["uv run mypy ."][1], "types")
        self.assertEqual(found["uv run black --check ."][1], "format")
        for command, kind in (("tox", "test"), ("nox", "test"), ("pre-commit run --all-files", "lint"),
                              ("cargo test", "test"), ("cargo clippy -- -D warnings", "lint"),
                              ("go test ./...", "test"), ("go vet ./...", "lint")):
            self.assertEqual(found[command][1:], (kind, "local"))
        self.assertEqual(len([command for command in found if "coverage" in command]), 0)

    def test_contributing_fenced_shell_lines_that_mention_checks(self):
        repo = Repo(self)
        repo.write("CONTRIBUTING.md", "# Contributing\n\n```console\n$ uv run pytest\n1 passed\n```\n\n"
                                      "```bash\ncd web\nnpm test\nnpm start\npip install -e .[test]\n```\n\n"
                                      "```python\nprint('test')\n```\n")
        found = self.listing(repo)
        self.assertEqual(found["uv run pytest"], ("CONTRIBUTING.md:4", "test", "local"))
        self.assertEqual(found["cd web && npm test"], ("CONTRIBUTING.md:10", "test", "local"))
        self.assertEqual(sorted(found), ["cd web && npm test", "uv run pytest"])

    def test_nothing_runs_without_run(self):
        repo = Repo(self)
        repo.write("CONTRIBUTING.md", "```sh\ntouch test-ran\n```\n")
        self.assertIn("touch test-ran", self.listing(repo))
        self.assertFalse(os.path.exists(os.path.join(repo.path, "test-ran")))

    def test_outside_a_repo_is_an_error_without_a_traceback(self):
        repo = Repo(self)
        done = discover(repo, cwd=repo.tmp)
        self.assertEqual(done.returncode, 2)
        self.assertIn("not a git repository", done.stderr)
        self.assertNotIn("Traceback", done.stderr)


class RunTest(unittest.TestCase):
    def workflow(self, repo, *commands):
        steps = "".join("      - run: %s\n" % command for command in commands)
        repo.write(".github/workflows/ci.yml", "jobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n" + steps)
        repo.commit("add a workflow")

    def test_run_sorts_the_checks_by_what_happened(self):
        repo = Repo(self)
        passing, red = "%s -c \"print('test ok')\"" % PYTHON, "%s -c \"raise SystemExit(3)\"" % PYTHON
        writer = "%s -c \"open('out.log', 'w')\"" % PYTHON
        self.workflow(repo, passing, red, writer, "no-such-tool-xyz --check", "./deploy.sh")
        done = discover(repo, "--run")
        self.assertEqual(done.returncode, 0, done.stderr)
        out = done.stdout
        self.assertIn("discover: [1/4] " + passing, out)
        self.assertRegex("\n".join(section(out, "Suggested `test:` lines")), r"^test: %s    # test, \d+s$"
                         % re.escape(passing))
        self.assertRegex("\n".join(section(out, "Already red on a clean tree")), r"^%s \(exit 3 after \d+s\)$"
                         % re.escape(red))
        self.assertEqual(section(out, "Passed, but changed the tree"), [writer + " (?? out.log)"])
        self.assertEqual(section(out, "Suggested .gitignore entries"), ["out.log"])
        self.assertEqual(section(out, "Could not start"), ["no-such-tool-xyz --check (exit 127)"])
        self.assertEqual(section(out, "Remote checks"),
                         ["- ./deploy.sh (.github/workflows/ci.yml:9): deploys or publishes (deploy)"])
        self.assertIn("left the tree changed", out)

    def test_a_check_that_rewrites_a_tracked_file_is_named(self):
        repo = Repo(self)
        self.workflow(repo, "%s -c \"open('README.md', 'a').write('x')\"" % PYTHON)
        out = discover(repo, "--run").stdout
        self.assertIn("( M README.md)", out)
        self.assertIn("which .gitignore cannot help", out)

    def test_run_refuses_a_dirty_tree_and_runs_nothing(self):
        repo = Repo(self)
        self.workflow(repo, "touch test-ran")
        repo.write("stray.txt")
        done = discover(repo, "--run")
        self.assertEqual(done.returncode, 1)
        self.assertIn("needs a clean tree", done.stderr)
        self.assertIn("stray.txt", done.stderr)
        self.assertFalse(os.path.exists(os.path.join(repo.path, "test-ran")))

    def test_a_check_past_the_timeout_is_stopped(self):
        repo = Repo(self)
        self.workflow(repo, "%s -c \"import time; time.sleep(60)\"" % PYTHON)
        began = time.monotonic()
        done = discover(repo, "--run", "--timeout", "1")
        self.assertLess(time.monotonic() - began, 30)
        self.assertIn("Timed out after 1s", done.stdout)

    def test_each_command_runs_once_from_the_repo_root(self):
        repo = Repo(self)
        command = "%s -c \"import os; print('test cwd=' + os.getcwd())\"" % PYTHON
        self.workflow(repo, command)
        repo.write("CONTRIBUTING.md", "```sh\n%s\n```\n" % command)
        repo.commit("docs")
        os.makedirs(os.path.join(repo.path, "sub"))
        done = discover(repo, "--run", cwd=os.path.join(repo.path, "sub"))
        self.assertIn("[1/1]", done.stdout)
        self.assertIn("cwd=" + os.path.realpath(repo.path), done.stdout)

    def test_a_bad_timeout_is_a_usage_error(self):
        repo = Repo(self)
        done = discover(repo, "--run", "--timeout", "0")
        self.assertEqual(done.returncode, 2)
        self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
