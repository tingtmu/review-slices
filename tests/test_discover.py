"""discover.py: list the offline checks a repo already has, and try the local ones with --run."""
import os
import re
import subprocess
import sys
import time
import importlib.util
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
  images:
    runs-on: ubuntu-latest
    steps:
      - name: Build
        run: cargo build --release
      - name: Push the image
        run: docker push example/app
      - run: pytest --python ${{ matrix.python }}
  smoke:
    steps:
      - run: ./scripts/smoke.sh
        env:
          TOKEN: ${{ secrets.TOKEN }}
"""


def discover(repo, *args, cwd=None, env=None):
    env = dict(ENV, GIT_CEILING_DIRECTORIES=os.path.dirname(repo.tmp), **(env or {}))
    return subprocess.run((PYTHON, DISCOVER) + args, cwd=cwd or repo.path, capture_output=True, text=True,
                          env=env, timeout=120)


def load_discover():
    spec = importlib.util.spec_from_file_location("discover", DISCOVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_tools(repo, *names):
    """A PATH whose first directory holds NAMES as tools that just succeed."""
    folder = os.path.join(repo.tmp, "bin")
    os.makedirs(folder, exist_ok=True)
    for name in names:
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, 0o755)
    return {"PATH": folder + os.pathsep + ENV.get("PATH", "")}


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
        self.assertEqual(found["make integration"][2], "remote: its job needs services")
        self.assertEqual(found["docker push example/app"][2], "remote: deploys or publishes (Push)")
        self.assertEqual(found["./scripts/smoke.sh"][2], "remote: its job uses secrets")
        self.assertEqual(found["pytest --python ${{ matrix.python }}"][2], "remote: needs CI values or variables")

    def test_deploy_jobs_and_steps_are_never_local(self):  # review: hyphenated names, environment:, $GITHUB_ENV
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml",
                   "jobs:\n  site:\n    environment: production\n    steps:\n      - run: make deploy-prod\n"
                   "  pages:\n    steps:\n      - run: echo \"KEY=${{ secrets.KEY }}\" >> \"$GITHUB_ENV\"\n"
                   "      - run: ./scripts/build.sh\n"
                   "  misc:\n    steps:\n      - run: npx semantic-release\n      - run: npx gh-pages -d dist\n"
                   "      - run: ./scripts/upload-site.sh\n      - run: rsync -av dist/ me@example.com:/srv\n"
                   "      - run: cargo build --release\n      - run: pytest $PYTEST_ARGS\n"
                   "      - run: docker buildx build --push -t ghcr.io/acme/app .\n"
                   "      - run: npx electron-builder --publish always\n"
                   "  sync:\n    steps:\n      - run: python manage.py migrate\n"
                   "        env:\n          DB_URL: ${{ secrets['PROD_DB_URL'] }}\n")
        found = self.listing(repo)
        self.assertEqual(found["make deploy-prod"][2], "remote: its job deploys to an environment")
        self.assertEqual(found["./scripts/build.sh"][2], "remote: its job uses secrets")
        self.assertEqual(found["python manage.py migrate"][2], "remote: its job uses secrets")  # round 2
        self.assertEqual(found["./scripts/upload-site.sh"][2], "remote: uploads to a service (upload)")
        for command, word in (("npx semantic-release", "release"), ("npx gh-pages -d dist", "gh"),
                              ("rsync -av dist/ me@example.com:/srv", "rsync"),
                              ("docker buildx build --push -t ghcr.io/acme/app .", "push"),
                              ("npx electron-builder --publish always", "publish")):
            self.assertEqual(found[command][2], "remote: deploys or publishes (%s)" % word)
        self.assertEqual(found["cargo build --release"][2], "local")
        self.assertEqual(found["pytest $PYTEST_ARGS"][2], "remote: needs CI values or variables")

    def test_coverage_and_report_uploads_are_remote(self):  # acceptance trial
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml",
                   "jobs:\n  t:\n    steps:\n      - run: pytest --cov\n      - run: npx coveralls\n"
                   "      - run: ./codecov -f coverage.xml\n      - run: sonar-scanner\n"
                   "      - name: Upload the report\n        run: ./scripts/report.sh\n")
        found = self.listing(repo)
        self.assertEqual(found["pytest --cov"][2], "local")
        for command, word in (("npx coveralls", "coveralls"), ("./codecov -f coverage.xml", "codecov"),
                              ("sonar-scanner", "sonar-scanner"), ("./scripts/report.sh", "Upload")):
            self.assertEqual(found[command][2], "remote: uploads to a service (%s)" % word)

    def test_package_scripts_and_contributing_lines_that_publish_are_remote(self):  # Standards review
        repo = Repo(self)
        repo.write("package.json", '{"scripts": {"test": "jest", "posttest": "npm publish", "lint": "eslint .",'
                                   ' "build": "tsc && npm run release"}}')
        repo.write("CONTRIBUTING.md", "```sh\nnpm publish && npm test\nnpm run lint\n```\n")
        found = self.listing(repo)
        self.assertEqual(found["npm run test"][2], "remote: deploys or publishes (publish)")
        self.assertEqual(found["npm run build"][2], "remote: deploys or publishes (release)")
        self.assertEqual(found["npm publish && npm test"][2], "remote: deploys or publishes (publish)")
        self.assertEqual(found["npm run lint"][2], "local")

    def test_a_check_chained_after_setup_is_kept(self):  # #20
        repo = Repo(self)
        repo.write(".github/workflows/test.yml",
                   "on: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
                   "      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n"
                   "      - run: pip install -e .\n      - run: python -m unittest discover -s tests -q\n"
                   "      - run: pip install ruff && ruff check notesvc\n"
                   "      - run: |\n          export LANG=C; cd src && pytest -q\n          mypy .\n"
                   "      - run: echo 'a && b; c' && npm ci\n"
                   "      - run: go mod tidy && git diff --exit-code\n")
        found = self.listing(repo)
        self.assertEqual(found["ruff check notesvc"], (".github/workflows/test.yml:10", "lint", "local"))
        self.assertEqual(found["cd src && pytest -q"][0], ".github/workflows/test.yml:12")
        self.assertEqual(found["cd src && mypy ."][0], ".github/workflows/test.yml:13")
        self.assertEqual(sorted(found), ["cd src && mypy .", "cd src && pytest -q",
                                         "go mod tidy && git diff --exit-code",
                                         "python -m unittest discover -s tests -q", "ruff check notesvc"])

    def test_comments_setup_flags_and_the_jobs_own_working_directory(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml",
                   "defaults:\n  run:\n    working-directory: top\njobs:\n  a:\n    defaults:\n      run:\n"
                   "        working-directory: \"my dir\"\n    steps: # build and test\n"
                   "      - run: yarn install --frozen-lockfile\n      - run: make test\n")
        self.assertEqual(sorted(self.listing(repo)), ["cd 'my dir' && make test"])

    def test_secrets_in_the_job_env_make_every_step_remote(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml", "jobs:\n  t:\n    env:\n      KEY: ${{ secrets.KEY }}\n"
                                               "    steps:\n      - run: pytest\n")
        self.assertEqual(self.listing(repo)["pytest"][2], "remote: its job uses secrets")

    @unittest.skipIf(sys.platform == "win32", "windows-latest is this OS")
    def test_a_job_only_for_another_os_is_remote(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml", "jobs:\n  win:\n    runs-on: windows-latest\n    steps:\n"
                                               "    - run: cargo test\n")
        self.assertEqual(self.listing(repo)["cargo test"][2], "remote: runs only on windows")

    @unittest.skipIf(sys.platform == "win32", "windows-latest is this OS")
    def test_the_matrix_key_comes_from_runs_on(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml", "jobs:\n  b:\n    runs-on: ${{ matrix.platform }}\n    strategy:\n"
                                               "      matrix:\n        platform: [windows-latest]\n    steps:\n"
                                               "      - run: make lint\n")
        self.assertEqual(self.listing(repo)["make lint"][2], "remote: runs only on windows")

    @unittest.skipIf(THIS_OS is None, "needs a Linux or macOS runner label for this OS")
    def test_a_matrix_with_this_os_stays_local_and_names_the_other_legs(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml",
                   "jobs:\n  t:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        os:\n"
                   "          - %s\n          - windows-latest\n    steps:\n      - run: pytest\n" % THIS_OS[0])
        self.assertEqual(self.listing(repo)["pytest"][2], "local; the CI matrix also runs it on windows")

    def test_gitlab_script(self):
        repo = Repo(self)
        repo.write(".gitlab-ci.yml", "stages: [test]\nlint:\n  stage: test\n  script:\n    - npm ci\n"
                                     "    - npm run lint\n    - |\n      echo hi\n      make check\n"
                                     "block:\n  script: |\n    make test\n    make typecheck\n"
                                     ".template:\n  script:\n    - make template-only\n"
                                     "deploy-prod:\n  stage: test\n  script: ./go.sh\n"
                                     "pkg:\n  stage: test\n  script:\n    - npm publish\n"
                                     "    - node tag.js $NPM_TOKEN\n")
        found = self.listing(repo)
        self.assertEqual(found["npm run lint"], (".gitlab-ci.yml:6", "lint", "local"))
        self.assertEqual(found["make check"], (".gitlab-ci.yml:9", "other", "local"))
        self.assertEqual(found["make test"], (".gitlab-ci.yml:12", "test", "local"))
        self.assertEqual(found["make typecheck"], (".gitlab-ci.yml:13", "types", "local"))
        self.assertEqual(found["./go.sh"][2], "remote: deploys or publishes (deploy)")
        self.assertEqual(found["npm publish"][2], "remote: deploys or publishes (publish)")
        self.assertEqual(found["node tag.js $NPM_TOKEN"][2], "remote: needs CI values or variables")
        for absent in ("npm ci", "|", "make template-only"):
            self.assertNotIn(absent, found)

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
        repo.write("justfile", "set shell := [\"bash\"]\n@typecheck:\n    mypy .\ncheck *ARGS:\n    true\n"
                               "test filter=\"\":\n    pytest\n")
        found = self.listing(repo)
        self.assertEqual(found["make test"], ("Makefile:3", "test", "local"))
        self.assertEqual(found["make lint"], ("Makefile:3", "lint", "local"))
        self.assertEqual(found["make build"], ("Makefile:5", "build", "local"))
        self.assertEqual(found["just typecheck"], ("justfile:2", "types", "local"))
        self.assertEqual(found["just check"], ("justfile:4", "other", "local"))
        self.assertEqual(found["just test"], ("justfile:6", "test", "local"))
        self.assertNotIn("make deploy", found)

    def test_a_target_whose_recipe_deploys_is_remote(self):  # the Standards finding's class: Make and just too
        repo = Repo(self)
        repo.write("Makefile", "build:\n\tdocker build -t x .\n\tdocker push x\n\ntest: upload-coverage\n\tpytest\n"
                               "lint:\n\t${RUFF} check .\n")
        repo.write("justfile", "check:\n    cargo test\n    cargo publish\n")
        found = self.listing(repo)
        self.assertEqual(found["make build"][2], "remote: deploys or publishes (push)")
        self.assertEqual(found["make test"][2], "remote: uploads to a service (upload)")
        self.assertEqual(found["make lint"][2], "local")
        self.assertEqual(found["just check"][2], "remote: deploys or publishes (publish)")

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

    def test_a_security_scanner_is_suggested_only_when_no_check_runs_one(self):  # S1
        def hint(repo):
            done = discover(repo)
            self.assertEqual(done.returncode, 0, done.stderr)
            return [line for line in done.stdout.splitlines() if line.startswith("hint:")]

        python, go, mixed, docs = Repo(self), Repo(self), Repo(self), Repo(self)
        for repo, files in ((python, ("app/a.py", "app/b.py")), (go, ("go.mod", "main.go")),
                            (mixed, ("web/a.ts", "web/b.ts", "tools/c.py")), (docs, ("guide.md", "run.sh"))):
            for name in files:
                repo.write(name)
            repo.commit("code")
        self.assertIn("bandit", " ".join(hint(python)))
        self.assertIn("gosec", " ".join(hint(go)))
        go.write("docs/a.md")
        go.commit("docs")
        below = discover(go, cwd=os.path.join(go.path, "docs"))
        self.assertIn("gosec", below.stdout)  # counted over the whole repo, not the directory it runs in
        self.assertIn("semgrep", " ".join(hint(mixed)))
        self.assertIn("semgrep", " ".join(hint(docs)))
        python.write(".github/workflows/ci.yml", "jobs:\n  a:\n    steps:\n      - run: bandit -r src -q\n")
        self.assertEqual(hint(python), [])
        go.write(".pre-commit-config.yaml", "repos:\n  - repo: https://github.com/securego/gosec\n"
                                            "    hooks:\n      - id: gosec\n")
        self.assertEqual(hint(go), [])

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

    def test_the_reviews_publishing_commands_are_remote_in_every_non_ci_source(self):  # final adversarial review
        repo = Repo(self)
        repo.write("package.json", '{"scripts": {"test": "npm test && npm publish", "build": "tsc && npm run deploy",'
                                   ' "lint": "eslint .", "postlint": "./scripts/release-check.sh --push"}}')
        repo.write("Makefile", "test:\n\tpython -m pytest && twine upload dist/*\n")
        repo.write("justfile", "check:\n    cargo test && cargo publish\n")
        repo.write("CONTRIBUTING.md", "```sh\nnpm test && npm publish\ncargo test && cargo publish\n"
                                      "python -m pytest && twine upload dist/*\n"
                                      "./scripts/release-check.sh --push\n```\n")
        done = discover(repo)
        self.assertEqual(done.returncode, 0, done.stderr)
        found = rows(done)
        for command in ("npm run test", "npm run build", "npm run lint", "make test", "just check",
                        "npm test && npm publish", "cargo test && cargo publish",
                        "python -m pytest && twine upload dist/*", "./scripts/release-check.sh --push"):
            self.assertTrue(found[command][2].startswith("remote: "), (command, found[command]))

    @unittest.skipIf(sys.platform == "win32", "fake tools are shell scripts")
    def test_run_never_runs_a_publishing_script_recipe_or_contributing_line(self):  # Standards and final review
        repo = Repo(self)
        repo.write("package.json", '{"scripts": {"test": "touch pkg-ran && npm publish"}}')
        repo.write("Makefile", "test:\n\ttouch make-ran && cargo publish\n")
        repo.write("justfile", "lint:\n    touch just-ran && twine upload dist/*\n")
        repo.write("CONTRIBUTING.md", "```sh\ntouch doc-ran-check && npx semantic-release\n"
                                      "touch doc-ran-test && ./scripts/release-check.sh --push\n```\n")
        self.workflow(repo, "true")
        out = discover(repo, "--run", env=fake_tools(repo, "npm", "npx", "make", "just", "cargo", "twine")).stdout
        self.assertIn("[1/1] true", out)
        for marker in ("pkg-ran", "make-ran", "just-ran", "doc-ran-check", "doc-ran-test"):
            self.assertFalse(os.path.exists(os.path.join(repo.path, marker)), marker)
        self.assertIn("- npm run test (package.json:1): deploys or publishes (publish)", out)

    @unittest.skipIf(sys.platform == "win32", "fake tools are shell scripts")
    def test_one_test_line_per_tool_preferring_the_ci_form(self):  # acceptance trial
        repo = Repo(self)
        repo.write("pyproject.toml", "[tool.pytest.ini_options]\n")
        repo.write("CONTRIBUTING.md", "```sh\nuv run pytest\n```\n")
        self.workflow(repo, "pytest -q")
        out = discover(repo, "--run", env=fake_tools(repo, "pytest", "uv")).stdout
        lines = section(out, "Suggested `test:` lines")
        self.assertEqual(len(lines), 2, out)
        self.assertRegex(lines[0], r"^test: pytest -q    # test, \d+s$")
        self.assertEqual(lines[1], "# or, the same tool: pytest; uv run pytest")

    def test_tool_key_groups_one_tool_and_keeps_others_apart(self):
        key = load_discover().tool_key
        for same in (("pytest -q", "pytest", "uv run pytest", "FOO=1 python -m pytest -x"),
                     ("npm test", "npm run test"), ("ruff check .", "ruff check src")):
            self.assertEqual(len({key(command) for command in same}), 1, same)
        for apart in (("python scripts/a.py", "python scripts/b.py"), ("npm test", "npm run lint"),
                      ("npm test", "cd web && npm test"), ("ruff check .", "ruff format --check ."),
                      ("python -c 'print(1)'", "python -c 'print(2)'")):
            self.assertEqual(len({key(command) for command in apart}), 2, apart)

    def test_run_never_runs_a_deploy(self):
        repo = Repo(self)
        repo.write(".github/workflows/ci.yml", "jobs:\n  site:\n    environment: production\n    steps:\n"
                                               "      - run: touch deployed\n  t:\n    steps:\n"
                                               "      - run: touch deploy-ran\n      - run: true\n")
        repo.commit("add a workflow")
        out = discover(repo, "--run").stdout
        self.assertIn("[1/1] true", out)
        for marker in ("deployed", "deploy-ran"):
            self.assertFalse(os.path.exists(os.path.join(repo.path, marker)), marker)
        self.assertIn("- touch deployed (.github/workflows/ci.yml:5): its job deploys to an environment", out)

    @unittest.skipUnless(sys.platform.startswith("linux"), "needs a file system that allows non-UTF-8 names")
    def test_a_non_utf8_name_is_no_traceback(self):
        repo = Repo(self)
        open(os.path.join(os.fsencode(repo.path), b"f\xff"), "w").close()
        done = discover(repo, "--run")
        self.assertEqual(done.returncode, 1)
        self.assertIn("needs a clean tree", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

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
        self.assertIn("ask the user to commit or stash these; never stash or commit someone else's edits",
                      done.stderr)
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
