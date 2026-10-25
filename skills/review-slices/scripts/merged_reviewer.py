#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices merged reviewer (skill version 0.7.1): may one merged reviewer take an Important push?

The guard loads this file from the commit its own copy comes from (the base branch) and calls allowed() from
`status` at Important; it is not run on its own. Without it, or if it fails, `status` says three reviewers.
calibrate.py measures with the skill's copy, so the thresholds are chosen and enforced by one measure.
"""
import fnmatch
import re
import subprocess

VERSION = "0.7.1"
# The largest push one merged reviewer may take, in weighted lines (ceil(characters / LINE_WIDTH) per added or
# deleted line, so a minified line cannot pass as one) and files; chosen from calibrate.py's data (2026-10-25).
MERGED_LINES, MERGED_FILES, LINE_WIDTH = 40, 3, 100
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


def allowed(guard, commits, uncommitted, tips):
    """(allowed, why): may one merged reviewer take this Important push? Measured over every commit the push adds
    (per commit then summed, merges left out), so several small units add up; never with uncommitted work, an
    unfetched base branch, a floor path (so no suite change), a merge with changes of its own, a submodule update
    or a binary file, whose size it cannot see."""
    if uncommitted or not commits:
        return False, "uncommitted work" if uncommitted else "no new commits"
    if not guard.base_tip()[1]:
        return False, "the base branch is not fetched"
    floor = [path for path in guard.paths_of(commits)
             if any(fnmatch.fnmatchcase(path, glob) for glob, _level in guard.FLOOR)]
    if floor:
        return False, "%s is always at least important" % floor[0]
    merges = guard.git("rev-list", "--merges", "HEAD", *(("--not",) + tuple(tips) if tips else ())).split()
    for merge in merges:
        if guard.commit_paths(merge):
            return False, "merge %s has changes of its own" % merge[:12]
    raw = guard.git("log", "--no-walk=unsorted", "--no-merges", "--root", "--format=", "--raw", "--no-abbrev",
                    "--no-renames", "--ignore-submodules=none", *commits)  # whatever .gitmodules or config say
    if any("160000" in line[1:].split()[:2] for line in raw.splitlines() if line.startswith(":")):
        return False, "a submodule update"
    lines, files, binary = patch_size(guard, read_patch(guard, "log", "--no-walk=unsorted", "--no-merges", "--root",
                                                        "--format=", *PATCH_ARGS, *commits))
    if binary:
        return False, "a binary file"
    size = "%d weighted line(s), %d file(s) in %d new commit(s)" % (lines, files, len(commits))
    if lines > MERGED_LINES or files > MERGED_FILES:
        return False, "%s: over %d or %d" % (size, MERGED_LINES, MERGED_FILES)
    return True, size
