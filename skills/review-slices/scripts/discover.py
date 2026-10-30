#!/usr/bin/env python3
"""review-slices discover: list the offline checks a repo already has, as candidates for REVIEW.md's `test:` lines.

Run it from inside the target repo. It stays in the skill and is never copied into a repo.

    discover.py                        list each candidate: where it was found, its kind, the command, and whether
                                       it runs locally or is a remote check (and why), and a hint when none
                                       of them runs a security scanner; runs nothing
    discover.py --run [--timeout S]    on a clean tree, run each local candidate from the repo root (S seconds each,
                                       default 600), then print the `test:` lines to add, the checks already red,
                                       the checks that write files, and the remote checks for REVIEW.md

Sources: .github/workflows/*.yml (`run:`), .gitlab-ci.yml (`script:`), package.json scripts, Makefile and justfile
targets, pyproject.toml tool sections, tox.ini, noxfile.py, .pre-commit-config.yaml, Cargo.toml, go.mod and the
fenced shell lines of CONTRIBUTING.md, read by discover_sources.py beside this file. Read the list before --run:
it runs every local candidate.
Standard library only, Python 3.8+, git 2.31+.
"""
import argparse
import collections
import importlib.util
import os
import re
import shlex
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TIMEOUT = 600
# Security scanners (SAST). One named in any file a candidate came from (a CI step, a pre-commit hook, a Makefile
# recipe) counts as the repo already running one.
SAST = re.compile(r"(?<![\w-])(bandit|semgrep|opengrep|gosec|brakeman|codeql|bearer|njsscan|flawfinder|"
                  r"eslint-plugin-security)(?![\w-])", re.I)
# A common scanner for the language most tracked code files are in (the guard's vendored copies aside); semgrep for
# any other.
SAST_TOOLS = {".py": "bandit (`bandit -r <package> -q`)", ".go": "gosec (`gosec ./...`)"}
SEMGREP = "semgrep with rules kept in the repo (`semgrep scan --config <rules file> --error`)"
CODE = (".py", ".go", ".js", ".jsx", ".ts", ".tsx", ".rb", ".java", ".kt", ".rs", ".c", ".cc", ".cpp", ".cs", ".php",
        ".swift")


def load_sources():
    spec = importlib.util.spec_from_file_location("discover_sources", os.path.join(HERE, "discover_sources.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sources = load_sources()
guard = sources.guard


def where(candidate):
    if candidate.remote:
        return "remote: " + candidate.remote
    return "local" + ("; the CI matrix also runs it on %s" % ", ".join(candidate.legs) if candidate.legs else "")


def print_candidates(found):
    places = ["%s:%d" % (candidate.source, candidate.line) for candidate in found]
    width = max(len(place) for place in places)
    print("discover: %d candidate(s)" % len(found))
    for place, candidate in zip(places, found):
        print("  %-*s  %-6s  %s  [%s]" % (width, place, candidate.kind, candidate.command, where(candidate)))


def sast_hint(root, found):
    """One line suggesting a security scanner when no file a candidate came from names one; None otherwise."""
    texts = [candidate.command for candidate in found]
    texts += ["\n".join(text for _number, text in sources.read_lines(root, rel))
              for rel in sorted({candidate.source for candidate in found})]
    if any(SAST.search(text) for text in texts):
        return None
    tracked = (guard.git("-C", root, "ls-files", "-z") or "").split("\0")
    counts = collections.Counter(os.path.splitext(path)[1] for path in tracked if not path.startswith(".githooks/"))
    language = max(CODE, key=lambda extension: counts[extension])
    tool = SAST_TOOLS.get(language, SEMGREP) if counts[language] else SEMGREP
    return ("hint: no security scanner (SAST) found among these checks; %s is a common one. It is optional: add it "
            "as a `test:` line only if the user wants one." % tool)


def remote_checks(found):
    lines = ["- %s (%s:%d): %s" % (c.command, c.source, c.line, c.remote) for c in found if c.remote]
    return lines + ["- %s on %s (%s:%d): the CI matrix runs it there" % (c.command, ", ".join(c.legs), c.source, c.line)
                    for c in found if c.legs]


def status(root):
    """{path: XY} from `git status --porcelain`, read in its -z form so odd names survive."""
    done = subprocess.run(("git",) + guard.GIT_SETTINGS + ("status", "--porcelain", "-z"), cwd=root,
                          capture_output=True, text=True, errors="replace")
    if done.returncode != 0:
        raise guard.GuardError("git status failed: %s" % done.stderr.strip())
    entries, fields = {}, iter(done.stdout.split("\0"))
    for field in fields:
        if len(field) > 3:
            entries[field[3:]] = field[:2]
            if field[0] in "RC":
                next(fields, None)  # a rename's old path
    return entries


def run_one(command, root, timeout):
    """(exit code, or None on a timeout; seconds) of COMMAND run by the shell from ROOT, as run-suite runs it."""
    began = time.monotonic()
    process = subprocess.Popen(command, shell=True, cwd=root, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        return process.wait(timeout=timeout), time.monotonic() - began
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)  # the shell and everything it started
        except (AttributeError, OSError):
            process.kill()
        process.wait()
        if isinstance(error, KeyboardInterrupt):
            raise
        return None, time.monotonic() - began


def run_all(root, found, timeout):
    """Run each local command once; [(candidate, code, seconds, changed)], CHANGED the status lines it added."""
    local, seen, results, before = [], set(), [], {}
    for candidate in found:
        if not candidate.remote and candidate.command not in seen:
            seen.add(candidate.command)
            local.append(candidate)
    for number, candidate in enumerate(local, 1):
        print("discover: [%d/%d] %s" % (number, len(local), candidate.command), flush=True)
        code, seconds = run_one(candidate.command, root, timeout)
        after = status(root)
        changed = sorted("%s %s" % (xy, path) for path, xy in after.items() if before.get(path) != xy)
        before = after
        print("discover: %s after %.0fs%s" % ("timed out" if code is None else "exit %d" % code, seconds,
                                              "; it changed the tree" if changed else ""), flush=True)
        results.append((candidate, code, seconds, changed))
    return results


def tool_key(command):
    """The tool COMMAND runs: its `cd` prefix, program and subcommand, such as ('ruff', 'check') or ('npm', 'lint'),
    with environment assignments and runners (uv run, python -m, npx) set aside, so `pytest -q` and `uv run pytest`
    are one tool."""
    prefix = re.match(r"(?:cd \S+ && )*", command).group(0)
    try:
        words = shlex.split(command[len(prefix):])
    except ValueError:
        words = command[len(prefix):].split()
    while words and re.match(r"[A-Za-z_]\w*=", words[0]):
        words = words[1:]
    runner = " ".join(words[:2])
    while words and (words[0] in ("npx", "bunx") or runner in ("uv run", "poetry run", "pdm run", "pipenv run",
                                                                 "hatch run", "python -m", "python3 -m", "py -m")):
        words = words[1:] if words[0] in ("npx", "bunx") else words[2:]
        runner = " ".join(words[:2])
    if len(words) > 2 and words[0] in ("npm", "pnpm", "yarn", "bun") and words[1] == "run":
        words = words[:1] + words[2:]
    key = words[:3] if words[1:2] == ["-c"] else words[:1] + [word for word in words[1:2] if word[:1] != "-"]
    return (prefix,) + tuple(key)


def suggestions(passed):
    """`test:` lines for PASSED [(candidate, seconds)]: one per tool, the CI form first, with the others that also
    passed as a comment, so the suite runs each tool once."""
    groups = collections.OrderedDict()
    for candidate, seconds in passed:
        groups.setdefault(tool_key(candidate.command), []).append((candidate, seconds))
    lines = []
    for group in groups.values():
        group = sorted(group, key=lambda item: not item[0].source.startswith((".github/", ".gitlab-ci")))
        (best, seconds), others = group[0], group[1:]
        lines.append("test: %s    # %s, %.0fs" % (best.command, best.kind, seconds))
        if others:
            lines.append("# or, the same tool: %s" % "; ".join(candidate.command for candidate, _s in others))
    return lines


def verdicts(results, timeout):
    """{heading: [line]} for the results of run_all, in the order to print them."""
    groups = collections.OrderedDict((heading, []) for heading in (
        "Suggested `test:` lines (they passed on a clean tree and left it clean):",
        "Passed, but changed the tree, so run-suite would refuse to stamp it: ignore what it writes (see the "
        ".gitignore entries below), or use its check-only mode, then run again:",
        "Already red on a clean tree: record as an incident or a roadmap item, and leave it out of the suite:",
        "Could not start (exit 126 or 127, a missing tool or a bad command): install the tool or fix the command:",
        "Timed out after %ds: raise --timeout, or leave it out of the suite:" % timeout,
        "Suggested .gitignore entries, for files the checks wrote:"))
    pass_, wrote, red, missing, slow, ignore = groups.values()
    passed = []
    for candidate, code, seconds, changed in results:
        also = "; it changed %s" % ", ".join(changed) if changed else ""
        if code is None:
            slow.append("%s%s" % (candidate.command, also))
        elif code in (126, 127):
            missing.append("%s (exit %d)" % (candidate.command, code))
        elif code:
            red.append("%s (exit %d after %.0fs%s)" % (candidate.command, code, seconds, also))
        elif changed:
            wrote.append("%s (%s)" % (candidate.command, ", ".join(changed)))
        else:
            passed.append((candidate, seconds))
        ignore += [line[3:] for line in changed if line.startswith("?? ") and line[3:] not in ignore]
    if any(not line.startswith("?? ") for _c, _code, _s, changed in results for line in changed):
        ignore.append("(a check rewrote tracked files, which .gitignore cannot help: use its check-only mode)")
    pass_ += suggestions(passed)
    return groups


def cmd_run(root, found, timeout):
    results = run_all(root, found, timeout)
    for heading, lines in list(verdicts(results, timeout).items()) + [
            ("Remote checks, for REVIEW.md's \"Remote checks\" list:", remote_checks(found))]:
        if lines:
            print("\n%s\n  %s" % (heading, "\n  ".join(lines)))
    if not results:
        print("\ndiscover: no local candidate to run")
    if status(root):
        print("\nnote: the checks left the tree changed; `git status` shows what, and nothing was cleaned up")
    return 0


def positive(text):
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError("expected a whole number of seconds above 0, not %r" % text)
    return int(text)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")  # a non-UTF-8 path prints escaped, not as a traceback
    parser = argparse.ArgumentParser(prog="discover.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="store_true", help="run each local candidate (needs a clean tree)")
    parser.add_argument("--timeout", type=positive, default=DEFAULT_TIMEOUT, metavar="SECONDS",
                        help="stop a check after this long (default %d)" % DEFAULT_TIMEOUT)
    options = parser.parse_args(argv[1:])
    try:
        root = guard.git("rev-parse", "--show-toplevel")
        dirty = sorted(status(root)) if options.run else []
        if dirty:
            print("discover: --run needs a clean tree, so that what each check writes shows. These may be the "
                  "user's edits: ask the user to commit or stash these; never stash or commit someone else's edits."
                  "\n  " + "\n  ".join(dirty[:10]), file=sys.stderr)
            return 1
        found = [candidate for source in sources.SOURCES for candidate in source(root)]
        hint = sast_hint(root, found)
        if not found:
            print("discover: no candidate checks found; write the suite's `test:` lines by hand")
            print(hint)
            return 0
        print_candidates(found)
        if hint:
            print(hint)
        if options.run:
            return cmd_run(root, found, options.timeout)
        print("\nNothing was run. Read the list, then `discover.py --run` on a clean tree tries each local one.")
        return 0
    except (guard.GuardError, OSError, UnicodeError) as error:
        print("review-slices: %s" % error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("discover: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv))
