"""Lint the vendored guard scripts that a file-level noqa header hides from `ruff check .`.

Those scripts carry `# ruff: noqa`, `# flake8: noqa` and `# ruff: noqa: PGH004` so an adopting repo's linters skip
them; ruff honours all three here too (`--ignore-noqa` would also drop their reasoned per-line noqa). This blanks
the header lines, keeping line numbers, and pipes each script to ruff under this repo's ruff.toml.

    python3 tests/lint_guard.py

Exits 1 on any finding, a missing or unheaded expected script, a headed script not listed here, or fewer scripts
linted than listed; prints the count linted on success. Exit 2: ruff is not on PATH.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = "skills/review-slices/scripts"
EXPECTED = tuple("%s/%s.py" % (SCRIPTS, name) for name in (
    "agent_hook", "incidents", "merged_reviewer", "review_slices", "run_suite", "secret_scan"))
# Ruff requires a lowercase tool name but accepts mixed case in "noqa".
HEADER = re.compile(r"^[^\S\n]*#[^\S\n]*(?:ruff|flake8)[^\S\n]*:[^\S\n]*(?i:noqa)(?=[^\S\n]|:|$).*$", re.M)
BLANKET = "# ruff: noqa"


def headed(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        return bool(HEADER.search(handle.read()))


def lint(path):
    """(ran, problem): whether ruff linted PATH with its header blanked, and its findings or why not; '' if clean."""
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
            source = handle.read()
    except OSError as error:
        return False, "%s: cannot read: %s" % (path, error.strerror or error)
    if BLANKET not in source.splitlines():
        return False, "%s: no `%s` header line: lint_guard.py's list is stale" % (path, BLANKET)
    done = subprocess.run(("ruff", "check", "--no-fix", "--no-fix-only", "--output-format", "concise",
                           "--config", os.path.join(ROOT, "ruff.toml"), "--stdin-filename", path, "-"),
                          input=HEADER.sub("", source), capture_output=True, text=True, cwd=ROOT, check=False)
    return True, "" if done.returncode == 0 else (done.stdout + done.stderr).strip() or "%s: ruff exit %d" % (
        path, done.returncode)


def main():
    try:
        subprocess.run(("ruff", "--version"), capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        print("lint_guard: ruff did not run: %s" % error, file=sys.stderr)
        return 2
    problems = ["%s/%s: carries the noqa header but is not in lint_guard.py's list" % (SCRIPTS, name)
                for name in sorted(os.listdir(os.path.join(ROOT, SCRIPTS)))
                if name.endswith(".py") and "%s/%s" % (SCRIPTS, name) not in EXPECTED
                and headed("%s/%s" % (SCRIPTS, name))]
    linted = 0
    for path in EXPECTED:
        ran, found = lint(path)
        linted += ran
        if found:
            problems.append(found)
    if not EXPECTED or linted != len(EXPECTED):
        problems.append("linted %d of %d expected scripts" % (linted, len(EXPECTED)))
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("lint_guard: %d files linted, all clean" % linted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
