#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices review load (skill version 0.8.0): which reviewers an Important or Critical change gets.

The guard loads this file from the commit its own copy comes from (the base branch) and calls load() from `status`
at Important and Critical; it is not run on its own. Without it, or if it fails, `status` says three reviewers.
calibrate.py measures with the skill's copy, so the bands are chosen and enforced by one measure. The guard parses
REVIEW.md's `small:`, `medium:` and `critical code:` lines; the defaults below apply where they are absent.
"""
import fnmatch
import re
import subprocess

VERSION = "0.8.0"
# The default small band, in weighted lines (ceil(characters / LINE_WIDTH) per added or deleted line, so a minified
# line cannot pass as one) and files; chosen from calibrate.py's data (2026-10-25). No medium band by default.
MERGED_LINES, MERGED_FILES, LINE_WIDTH = 40, 3, 100
MERGED, PAIR, THREE = "one merged reviewer", "adversarial + conformance", "three reviewers"
# The review load table: level -> {size band: load}. A Critical change gets PAIR only when small and every path
# that sets its level is in `critical code:` globs alone.
TABLE = {"important": {"small": MERGED, "medium": PAIR, "large": THREE},
         "critical": {"small": PAIR, "medium": THREE, "large": THREE}}
PATCH_ARGS = ("--patch", "-U0", "--inter-hunk-context=0", "--no-renames", "--no-ext-diff", "--no-textconv",
              "--no-color", "--submodule=short", "--ignore-submodules=none", "--no-relative", "--src-prefix=a/",
              "--dst-prefix=b/")
LFS_POINTER = "version https://git-lfs.github.com/spec/"
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def read_patch(guard, *args):
    """git's patch output, read as bytes: Python's newline translation would split a line at a lone CR."""
    done = subprocess.run(("git",) + guard.GIT_SETTINGS + args, capture_output=True)
    if done.returncode != 0:
        raise guard.GuardError("git %s failed: %s" % (args[0], done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout.decode("utf-8", "surrogateescape")


def patch_size(guard, text):
    """(weighted lines, files, binary) of a `--patch -U0` listing; a Git LFS pointer counts as binary. Hunk lengths
    come from the hunk headers, so a deleted line that starts with `--` is never taken for a header."""
    lines, files, binary, old, new = 0, set(), False, 0, 0
    for line in text.split("\n"):
        if old > 0 or new > 0:
            if not line.startswith("\\"):  # "\ No newline at end of file"
                old, new = old - (not line.startswith("+")), new - (not line.startswith("-"))
                lines += max(1, -(-(len(line) - 1) // LINE_WIDTH)) if line.startswith(("+", "-")) else 0
                binary = binary or line[1:].startswith(LFS_POINTER)  # the file's size is not in the patch
        elif line.startswith("diff --git "):
            files.add(line)
        elif line.startswith("@@ "):
            match = HUNK.match(line)
            if not match:
                raise guard.GuardError("unexpected hunk header in git's patch: %r" % line[:80])
            old, new = (int(count) if count is not None else 1 for count in match.groups())
        elif line.startswith("Binary files ") and line.endswith(" differ"):
            binary = True
    return lines, len(files), binary


def measure(guard, commits, uncommitted, tips):
    """((weighted lines, files) or None, why) of COMMITS (per commit then summed, merges left out), so several small
    units add up; None, so no band below large, with uncommitted work, an unfetched base branch, a floor path (so
    no suite change), a merge with changes of its own, a submodule update or a binary file, whose size it cannot
    see."""
    if uncommitted or not commits:
        return None, "uncommitted work" if uncommitted else "no new commits"
    if not guard.base_tip()[1]:
        return None, "the base branch is not fetched"
    floor = [path for path in guard.paths_of(commits)
             if any(fnmatch.fnmatchcase(path, glob) for glob, _level in guard.FLOOR)]
    if floor:
        return None, "%s is a floor path" % floor[0]
    merges = guard.git("rev-list", "--merges", "HEAD", *(("--not",) + tuple(tips) if tips else ())).split()
    for merge in merges:
        if guard.commit_paths(merge):
            return None, "merge %s has changes of its own" % merge[:12]
    raw = guard.git("log", "--no-walk=unsorted", "--no-merges", "--root", "--format=", "--raw", "--no-abbrev",
                    "--no-renames", "--ignore-submodules=none", *commits)  # whatever .gitmodules or config say
    if any("160000" in line[1:].split()[:2] for line in raw.splitlines() if line.startswith(":")):
        return None, "a submodule update"
    lines, files, binary = patch_size(guard, read_patch(guard, "log", "--no-walk=unsorted", "--no-merges", "--root",
                                                        "--format=", *PATCH_ARGS, *commits))
    if binary:
        return None, "a binary file"
    return (lines, files), "%d weighted line(s), %d file(s) in %d commit(s)" % (lines, files, len(commits))


def band(guard, rules, commits, uncommitted, tips):
    """(small, medium or large, why): the size band of COMMITS under RULES' `small:` and `medium:` lines (None:
    the defaults). A band that is off, or that a smaller one already covers, takes nothing."""
    size, why = measure(guard, commits, uncommitted, tips)
    for name, default in (("small", (MERGED_LINES, MERGED_FILES)), ("medium", None)):
        limit = (rules or {}).get(name) or default
        if size and limit not in (None, "off") and size[0] <= limit[0] and size[1] <= limit[1]:
            return name, "%s, within the %s band's %d lines, %d files" % ((why, name) + tuple(limit))
    return "large", why if not size else "%s: over every band" % why


def kind(guard, rules, path):
    """code if every critical glob of RULES that PATH matches is a `critical code:` glob and PATH is no floor
    path; content otherwise (a `critical:` glob, a critical default, unreadable rules)."""
    globs = [glob for level, glob in (rules or {}).get("globs", ()) if level == "critical"
             and fnmatch.fnmatchcase(path, glob)]
    floor = any(fnmatch.fnmatchcase(path, glob) for glob, _level in guard.FLOOR)
    return "code" if globs and not floor and set(globs) <= set((rules or {}).get("code", ())) else "content"


def load(guard, rules, level, rows, commits, uncommitted, tips):
    """(load, why): the reviewers a LEVEL change gets, from the TABLE: its size band over COMMITS and, at Critical,
    the kind of every path in ROWS (the paths that set the level)."""
    if level == "critical":
        content = [row.path for row in rows if kind(guard, rules, row.path) != "code"]
        if content:
            return THREE, "%s is not in `critical code:` globs alone" % content[0]
    name, why = band(guard, rules, commits, uncommitted, tips)
    return TABLE[level][name], "%s: %s" % (name, why)


def allowed(guard, commits, uncommitted, tips):
    """(allowed, why): 0.8.0's question, kept for callers that ask it: may one merged reviewer take this Important
    push under the default bands?"""
    name, why = band(guard, None, commits, uncommitted, tips)
    return name == "small", why
