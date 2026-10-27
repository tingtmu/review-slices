#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices suite wrapper (skill version 0.9.3): `review_slices.py run-suite` runs the suite and stamps a pass.

The guard loads this file from beside itself and calls run(); it is not run on its own. run-suite never hands off
to the base branch's guard: it runs the working copy's own suite, so nothing here decides what a push needs. The
base branch's guard reads the stamps it writes (the format is the guard's: tree, time, seconds, per-check seconds).
"""
import datetime
import os
import subprocess
import sys
import time

VERSION = "0.9.3"
STAMP_KEEP = 50


def write_stamp(guard, tree, seconds, times=()):
    path = guard.stamp_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        lines = []
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w", encoding="utf-8") as handle:
        line = "%s %s %.0fs %s" % (tree, now, seconds, ",".join("%.0fs" % taken for taken in times))
        handle.write("\n".join((lines + [line.rstrip()])[-STAMP_KEEP:]) + "\n")


def run(guard, _args):
    """Run each check of the suite listed in the working copy's REVIEW.md, which is part of the tree it stamps."""
    root = guard.git("rev-parse", "--show-toplevel")
    config = guard.read_config(root)
    if not config["tests"]:
        raise guard.GuardError("REVIEW.md's review-slices block names no test command")
    wiring = guard.hook_wiring()
    if not wiring or "0.1.0" in wiring:
        print("warning: this clone's pre-push does not reach the bootstrap, so pushes are not checked by the base "
              "branch's guard; run the skill's setup_tools.py install", file=sys.stderr)
    mismatch = guard.base_mismatch(config, guard.base_tip()[0])
    if mismatch:
        print("warning: " + mismatch, file=sys.stderr)
    untracked = guard.untracked_paths()
    if untracked:
        print("note: the stamp includes these untracked files; commit them all, or run again without them:\n  "
              + "\n  ".join(untracked[:10]), file=sys.stderr)
    before, started, times = guard.worktree_tree(root), time.monotonic(), []
    for number, command in enumerate(config["tests"], 1):
        print("run-suite: [%d/%d] %s" % (number, len(config["tests"]), command), flush=True)
        began = time.monotonic()
        code = subprocess.run(command, shell=True, cwd=root).returncode
        times = times + [time.monotonic() - began]
        print("run-suite: [%d/%d] exit %d after %.0fs" % (number, len(config["tests"]), code, times[-1]), flush=True)
        if code != 0:
            print("run-suite: check %d failed; no stamp written" % number, file=sys.stderr)
            return code
    after = guard.worktree_tree(root)
    if before != after:
        moved = guard.split_nul(guard.git("diff-tree", "-r", "-z", "--name-only", before, after))
        print("run-suite: these files changed during the run, so no stamp was written; ignore or fix them and run "
              "again:\n  " + "\n  ".join(moved[:10]), file=sys.stderr)
        return 1
    seconds = time.monotonic() - started
    write_stamp(guard, before, seconds, times)
    head = guard.git("rev-parse", "--verify", "--quiet", "HEAD^{tree}", check=False)
    if head and head != before:
        differ = guard.split_nul(guard.git("diff-tree", "-r", "-z", "--name-only", head, before))
        print("run-suite: the suite passed on the working tree (stamped %s), but that is NOT HEAD's tree, so a push "
              "of HEAD has no stamp. These paths differ from HEAD:\n  %s\nCommit them if they are this work's; if "
              "they are not yours, ask the user before touching them." % (before[:12], "\n  ".join(differ[:10])),
              file=sys.stderr)
        return 0
    print("run-suite: passed in %.0fs; stamped tree %s, which is HEAD's" % (seconds, before[:12]))
    return 0
