#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices review load (skill version 0.9.2): which reviewers an Important or Critical change gets.

The guard loads this file from the commit its own copy comes from (the base branch) and calls load() from `status`
at Important and Critical, then hold(), which keeps the load per review unit in the review log; it is not run on its
own. Without it, or if it fails, `status` says three reviewers.
calibrate.py measures with the skill's copy, so the bands are chosen and enforced by one measure. The guard parses
REVIEW.md's `small:`, `medium:` and `critical code:` lines; the defaults below apply where they are absent.
"""
import collections
import fnmatch
import os
import re
import subprocess
import time

VERSION = "0.9.2"
# The default small band, in weighted lines (ceil(characters / LINE_WIDTH) per added or deleted line, so a minified
# line cannot pass as one) and files; chosen from calibrate.py's data (2026-10-25). No medium band by default.
MERGED_LINES, MERGED_FILES, LINE_WIDTH = 40, 3, 100
MERGED, PAIR, THREE = "one merged reviewer", "adversarial + conformance", "three reviewers"
# The review load table: level -> {size band: load}. A Critical change gets PAIR only when small and every path
# that sets its level is in `critical code:` globs alone.
TABLE = {"important": {"small": MERGED, "medium": PAIR, "large": THREE},
         "critical": {"small": PAIR, "medium": THREE, "large": THREE}}
# A file moved unchanged is one file and no lines; 100% finds only byte-identical moves (git's exact pass), whatever
# diff.renameLimit says, so a move with any edit still counts in full as a delete plus an add.
PATCH_ARGS = ("--patch", "-U0", "--inter-hunk-context=0", "--find-renames=100%", "--no-ext-diff", "--no-textconv",
              "--no-color", "--submodule=short", "--ignore-submodules=none", "--no-relative", "--src-prefix=a/",
              "--dst-prefix=b/")
LFS_POINTER = "version https://git-lfs.github.com/spec/"
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
RANK = {MERGED: 0, PAIR: 1, THREE: 2}
REWRITTEN = "history inside the unit was rewritten"
SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
# A line of the review log: what `status` printed for the unit that starts at START on REF, at HEAD.
Entry = collections.namedtuple("Entry", "time ref start head level load why")


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
    text = read_patch(guard, "log", "--no-walk=unsorted", "--no-merges", "--root", "--format=", *PATCH_ARGS, *commits)
    lines, files, binary = patch_size(guard, text)
    if binary:
        return None, "a binary file"
    renames = sum(line.startswith("rename from ") for line in text.split("\n"))  # -U0: content starts with +/-
    return (lines, files), "%d weighted line(s), %d file(s) in %d commit(s)%s" % (
        lines, files, len(commits), "; %d exact rename(s) counted as 0 lines" % renames if renames else "")


def limits(rules):
    """{band: (lines, files) or None}: RULES' `small:` and `medium:` lines (None: the defaults); off is None."""
    chosen = [(name, (rules or {}).get(name) or default) for name, default in (("small", (MERGED_LINES, MERGED_FILES)),
                                                                              ("medium", None))]
    return {name: None if limit == "off" else limit for name, limit in chosen}


def band_of(rules, size):
    """small, medium or large: the first band SIZE (lines, files) fits under RULES; None fits none."""
    for name, limit in limits(rules).items():  # small first
        if size and limit and size[0] <= limit[0] and size[1] <= limit[1]:
            return name
    return "large"


def band(guard, rules, commits, uncommitted, tips):
    """(small, medium or large, why): the size band of COMMITS under RULES. A band that is off, or that a smaller
    one already covers, takes nothing."""
    size, why = measure(guard, commits, uncommitted, tips)
    name = band_of(rules, size)
    if name == "large":
        return name, why if not size else "%s: over every band" % why
    return name, "%s, within the %s band's %d lines, %d files" % ((why, name) + tuple(limits(rules)[name]))


def kind(guard, rules, path):
    """code if every critical glob of RULES that PATH matches is a `critical code:` glob and PATH is no floor
    path; content otherwise (a `critical:` glob, a critical default, unreadable rules)."""
    globs = [glob for level, glob in (rules or {}).get("globs", ()) if level == "critical"
             and fnmatch.fnmatchcase(path, glob)]
    floor = any(fnmatch.fnmatchcase(path, glob) for glob, _level in guard.FLOOR)
    return "code" if globs and not floor and set(globs) <= set((rules or {}).get("code", ())) else "content"


def content_path(guard, rules, level, paths):
    """At Critical, the first of PATHS (those that set the level) that is content, else None."""
    return next((path for path in paths if kind(guard, rules, path) != "code"), None) if level == "critical" else None


def load(guard, rules, level, rows, commits, uncommitted, tips):
    """(load, why): the reviewers a LEVEL change gets, from the TABLE: its size band over COMMITS and, at Critical,
    the kind of every path in ROWS (the paths that set the level)."""
    content = content_path(guard, rules, level, [row.path for row in rows])
    if content:
        return THREE, "%s is not in `critical code:` globs alone" % content
    name, why = band(guard, rules, commits, uncommitted, tips)
    return TABLE[level][name], "%s: %s" % (name, why)


def allowed(guard, commits, uncommitted, tips):
    """(allowed, why): 0.8.0's question, kept for callers that ask it: may one merged reviewer take this Important
    push under the default bands?"""
    name, why = band(guard, None, commits, uncommitted, tips)
    return name == "small", why


def log_path(guard):
    """The review log, beside the pass stamps: one line per load `status` printed for committed work."""
    return os.path.join(os.path.dirname(guard.stamp_path()), "review-log")


def unit_ref(guard):
    """The branch HEAD is on, or on a detached HEAD this worktree's git dir: with its start, a unit's key, since
    every branch cut from one base commit starts there and worktrees share the log."""
    return guard.git("symbolic-ref", "-q", "HEAD", check=False) or guard.git("rev-parse", "--absolute-git-dir")


def read_log(guard, path):
    """[Entry] of the review log at PATH; a line it cannot read is an error, never skipped (I2)."""
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return []
    entries = []
    for number, line in enumerate(lines, 1):
        fields = line.split("\t")
        entry = Entry(*fields) if len(fields) == len(Entry._fields) else None
        if not entry or not SHA.match(entry.start) or not SHA.match(entry.head) or entry.load not in RANK:
            raise guard.GuardError("%s line %d is not a review log line: fix or delete it" % (path, number))
        entries.append(entry)
    return entries


def hold(guard, start, level, found):
    """(load, why): FOUND, the load measured for the unit that starts at START, or what the review log holds for
    it: the highest load `status` printed since the unit began, and three reviewers once a commit one was printed
    at has left HEAD's history (amend, squash, rebase). Logs what it returns when it differs from the last line."""
    path, ref, head = log_path(guard), unit_ref(guard), guard.git("rev-parse", "HEAD")
    mine = [entry for entry in read_log(guard, path) if (entry.ref, entry.start) == (ref, start)]
    gone = next((entry for entry in mine if guard.git("merge-base", "--is-ancestor", entry.head, "HEAD",
                                                      check=False) is None), None)
    top = max((entry for entry in mine if not entry.why.startswith(REWRITTEN)), key=lambda entry: RANK[entry.load],
              default=None)  # the first printed, if several; a rewrite is judged again each time, never held
    if gone:
        found = THREE, "%s after status printed %s at %s" % (REWRITTEN, gone.load, gone.head[:12])
    elif top and RANK[top.load] > RANK[found[0]]:
        found = top.load, "held: status printed it for this unit at %s (%s); now %s" % (top.time, top.why, found[1])
    if not mine or (mine[-1].head, mine[-1].load) != (head, found[0]):
        fields = (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), ref, start, head, level) + tuple(found)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", errors="surrogateescape") as handle:
            handle.write("\t".join(re.sub(r"[\t\r\n]", " ", field) for field in fields) + "\n")
    return found
