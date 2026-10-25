#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices secret scan (skill version 0.8.0): gitleaks over the commits a push adds.

The guard loads this file from the commit its own copy comes from (the base branch) and calls scan() when REVIEW.md
says `secrets: gitleaks`; it is not run on its own. The config comes from that same commit, only the pushed commit's
committed .gitleaksignore lines that name a commit apply, and git settings, attributes and `gitleaks:allow` markers
that would hide a line are overridden. Anything short of a scan that read the commits and found nothing refuses the
push. gitleaks's default config skips some paths (lockfiles, node_modules/ and the like); a base branch that wants
them scanned commits a full .gitleaks.toml that does not extend the default.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

VERSION = "0.8.0"
MIN_GITLEAKS = (8, 19, 0)
MIN_GIT = (2, 36, 0)  # --diff-merges=remerge, so a secret added in a merge commit is seen
TIMEOUT = 600
SHOWN = 10
# Flags for every `git log -p` behind the scan: patch text whatever the user's or repo's settings and attributes.
LOG = ("--no-color", "--text", "--no-textconv", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/",
       "--no-relative", "--no-show-signature", "--no-abbrev-commit", "--pretty=medium", "--diff-merges=remerge")
DEFAULT_CONFIG = "[extend]\nuseDefault = true\n"
FINGERPRINT = re.compile(r"^[0-9a-f]{40}:")
INSTALL = "see https://github.com/gitleaks/gitleaks#installing"


def version_tuple(text):
    parts = [int(part) for part in re.findall(r"\d+", text or "")[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def dotted(numbers):
    return ".".join(map(str, numbers))


def ignore_lines(text):
    """(kept, dropped): .gitleaksignore lines that name a commit, and the others. A fingerprint without a commit
    (`file:rule:line`) would silence that spot for every later secret, so it never applies."""
    lines = [line.strip() for line in (text or "").splitlines()]
    entries = [line for line in lines if line and not line.startswith("#")]
    return ([line for line in entries if FINGERPRINT.match(line)],
            [line for line in entries if not FINGERPRINT.match(line)])


def preconditions(git, binary):
    """A problem that stops the scan before it runs, or None."""
    if not binary:
        return "gitleaks is not installed (REVIEW.md says `secrets: gitleaks`): ask the user to install %s+, %s" % (
            dotted(MIN_GITLEAKS), INSTALL)
    try:
        found = version_tuple(subprocess.run((binary, "version"), capture_output=True, text=True,
                                             timeout=60).stdout)
    except (OSError, subprocess.SubprocessError) as error:
        return "gitleaks did not run: %s" % error
    if found < MIN_GITLEAKS:
        return "gitleaks %s is older than %s: ask the user to upgrade it, %s" % (dotted(found), dotted(MIN_GITLEAKS),
                                                                               INSTALL)
    if version_tuple(git("--version")) < MIN_GIT:
        return "the secret scan needs git %s+ to read merge commits: ask the user to upgrade git" % dotted(MIN_GIT)
    return None


def finding_lines(report_path):
    """One line per finding, without the secret: rule, place, commit and the fingerprint the user may allow."""
    with open(report_path, encoding="utf-8") as handle:
        findings = json.load(handle)
    lines = ["%s at %s:%s in %s; fingerprint %s" % (item["RuleID"], item["File"], item["StartLine"],
                                                   item["Commit"][:12], item["Fingerprint"])
             for item in findings[:SHOWN]]
    return lines + (["and %d more" % (len(findings) - SHOWN)] if len(findings) > SHOWN else [])


def adds_lines(git, scope):
    """Whether the commits in SCOPE add any line, read the way gitleaks reads them."""
    patch = git("log", "-p", "-U0", *(LOG + ("--format=",) + tuple(scope))) or ""
    return any(line.startswith("+") and not line.startswith("+++") for line in patch.splitlines())


def verdict(git, done, report_path, scope):
    """(problems, notes) from a finished gitleaks run."""
    count = re.search(r"(\d+) commits? scanned", done.stderr)
    last = (done.stderr.strip().splitlines() or ["no output"])[-1]
    if done.returncode == 2:
        try:
            lines = finding_lines(report_path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            return ["gitleaks found secrets but its report did not read (%s): run it by hand" % error], []
        return ["gitleaks found a secret in the commits this push adds; follow the skill's \"A secret turns up\" "
                "and never print the value:\n    " + "\n    ".join(lines)], []
    if done.returncode != 0 or not count:
        return ["the secret scan failed (gitleaks exit %d): %s" % (done.returncode, last)], []
    if int(count.group(1)) == 0 and adds_lines(git, scope):
        return ["the secret scan read no commits although they add lines (gitleaks: %s)" % last], []
    return [], ["gitleaks found none in %s commit(s) scanned" % count.group(1)]


def scan(git, at, head, tips):
    """(problems, notes) for the commits HEAD adds over TIPS. AT is the commit this file came from: its
    .gitleaks.toml configures the scan. GIT is the guard's git(), which runs with its own fixed settings."""
    binary = shutil.which("gitleaks")
    problem = preconditions(git, binary)
    if problem:
        return [problem], []
    scope = (head,) + (("--not",) + tuple(tips) if tips else ())
    kept, dropped = ignore_lines(git("show", "%s:.gitleaksignore" % head, check=False))
    notes = (["the .gitleaksignore lines without a commit do not apply: %s" % ", ".join(dropped[:3])]
             if dropped else [])
    git_dir = git("rev-parse", "--absolute-git-dir")
    with tempfile.TemporaryDirectory() as tmp:
        config, ignore, report = (os.path.join(tmp, name) for name in ("config.toml", "ignore", "report.json"))
        with open(config, "w", encoding="utf-8") as handle:
            handle.write(git("show", "%s:.gitleaks.toml" % at, check=False) or DEFAULT_CONFIG)
        with open(ignore, "w", encoding="utf-8") as handle:
            handle.write("".join(line + "\n" for line in kept))
        argv = [binary, "git", "--no-banner", "--no-color", "--redact", "--exit-code", "2", "--ignore-gitleaks-allow",
                "--config", config, "--gitleaks-ignore-path", ignore, "--report-format", "json", "--report-path",
                report, "--log-opts", " ".join(LOG + scope), tmp]
        # Its source is this temp dir and git finds the repo by GIT_DIR, so gitleaks reads no .gitleaksignore
        # (not the working tree's, not one in the git dir) but the one passed to it.
        env = dict({key: value for key, value in os.environ.items() if key != "GIT_WORK_TREE"}, GIT_DIR=git_dir)
        try:
            done = subprocess.run(argv, cwd=tmp, env=env, capture_output=True, text=True, errors="replace",
                                  timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return ["the secret scan timed out after %ds" % TIMEOUT], notes
        except OSError as error:
            return ["gitleaks did not run: %s" % error], notes
        problems, more = verdict(git, done, report, scope)
    return problems, notes + more
