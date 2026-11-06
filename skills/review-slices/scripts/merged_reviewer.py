#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices review load (skill version 0.12.0): which reviewers an Important or Critical change gets.

The guard loads this file from the commit its own copy comes from (the base branch) and calls load() from `status`
at Important and Critical, then hold(), which keeps the load per review unit in the review log; it is not run on its
own. Without it, or if it fails, `status` says three reviewers, the fallback; the most it prints is the pair.
calibrate.py measures with the skill's copy, so the bands are chosen and enforced by one measure. The guard parses
REVIEW.md's `small:`, `medium:` and `critical code:` lines; the defaults below apply where they are absent.
"""
import collections
import fnmatch
import os
import re
import subprocess
import time

VERSION = "0.12.0"
# The default small band, in weighted lines (ceil(characters / LINE_WIDTH) per added or deleted line, so a minified
# line cannot pass as one) and files; chosen from calibrate.py's data (2026-10-25). No medium band by default.
MERGED_LINES, MERGED_FILES, LINE_WIDTH = 40, 3, 100
MERGED, PAIR, THREE = "one merged reviewer", "adversarial + conformance", "three reviewers"
# The review load table: level -> {size band: load}. The pair is the ceiling (0.13.0): three reviewers are only the
# guard's fallback when it cannot measure, and what the user asks for.
TABLE = {"important": {"small": MERGED, "medium": PAIR, "large": PAIR},
         "critical": {"small": PAIR, "medium": PAIR, "large": PAIR}}
CEILING = (PAIR, THREE)  # loads a unit large on its own may have printed for its measure to restart after it
# The unit's weight, logged as a suffix of the review log's `why`: level, size band, and whether a floor path or, at
# Critical, a content path is in it. A rise in any part is an escalation, since the load no longer rises with it.
WEIGHT_PARTS = (("important", "critical"), ("small", "medium", "large"), ("none", "path"))
WEIGHT = re.compile(r"; weight=(important|critical)/(small|medium|large)/(none|path)")
# An entry logged before 0.13.0 has no weight: the lowest its level and load had under the old table.
OLD_BANDS = {("important", PAIR): "medium", ("important", THREE): "large", ("critical", THREE): "medium"}
CROSS_CHECK = "; cross-check"
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
    no suite change), a merge with changes of its own, a submodule update or a binary file added, edited or
    deleted, whose size it cannot see (one moved unchanged is an exact rename: no lines)."""
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
    if name == "large":  # name the limit crossed, so "it is only a move" reads as counted (issue #26)
        on = [(limit, band_name) for band_name, limit in limits(rules).items() if limit]  # medium may be narrower
        widest = ("widest on: %s, %d lines, %d files" % ((max(on)[1],) + tuple(max(on)[0])) if on
                  else "every band is off")
        return name, why if not size else "%s: over every band (%s)" % (why, widest)
    return name, "%s, within the %s band's %d lines, %d files" % ((why, name) + tuple(limits(rules)[name]))


def line_limit(rules):
    """The most weighted lines a band of RULES that is on takes, or None with every band off."""
    return max((limit[0] for limit in limits(rules).values() if limit), default=None)


def net_lines(guard, old, new):
    """The weighted lines of the net diff OLD..NEW; a binary file or a submodule update adds none it can see."""
    return patch_size(guard, read_patch(guard, "diff", *PATCH_ARGS, old, new))[0]


def restarts(guard, rules, commits, tips):
    """The trailer commits among COMMITS after which the measure starts over: each closes a unit with no merge, of
    the standing RULES' Important or Critical level, whose trailer says that level or higher and whose net diff is
    over every band's line limit, and for which this ref's review log holds the ceiling load (the pair, or three
    reviewers before 0.13.0) printed in the unit at or before it, when the unit was already that large. So a slice that is small on its own, a unit grown past the
    band after a lighter load, a base branch reset under it, rules tightened since, another clone or a rebase never
    restart; the log can only take a restart away. No standing rules, or a guard without the helpers: none."""
    limit = line_limit(rules)
    if not rules or limit is None or not all(hasattr(guard, name) for name in ("review_units", "range_level",
                                                                              "paths_of", "rank")):
        return []
    ref = unit_ref(guard)
    logged = [entry for entry in read_log(guard, log_path(guard)) if entry.ref == ref and entry.load in CEILING]
    found = []
    for commit, unit in guard.review_units(commits, tips)[0]:  # a unit's commits newest first, so a chain ends at
        level = guard.range_level(rules, guard.paths_of(unit))[0]  # its oldest
        parents = [guard.git("rev-list", "--parents", "-n", "1", sha).split()[1:] for sha in unit]
        if (level not in TABLE or guard.rank(guard.trailer_level(commit)) < guard.rank(level)
                or any(len(found_parents) != 1 for found_parents in parents)
                or net_lines(guard, parents[-1][0], commit) <= limit):
            continue
        starts, tree = (set(unit) - {commit}) | {parents[-1][0]}, guard.git("rev-parse", commit + "^{tree}")
        if any(entry.start in starts and (guard.git("merge-base", "--is-ancestor", entry.head, commit,
                                                    check=False) is not None
                                          or guard.git("rev-parse", "--verify", "--quiet", entry.head + "^{tree}",
                                                       check=False) == tree)
               and net_lines(guard, entry.start, entry.head) > limit for entry in logged):
            found.append(commit)
    return found


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
    """(load, why): the reviewers a LEVEL change gets, from the TABLE: its size band over COMMITS since the last
    restart, if any, and, at Critical, the kind of every path in ROWS (the paths that set the level). WHY ends with
    the unit's weight."""
    content = content_path(guard, rules, level, [row.path for row in rows])
    found = [] if uncommitted else restarts(guard, rules, commits, tips)
    if found:
        kept = set(guard.rev_list("HEAD", tuple(tips) + tuple(found)))
        commits, tips = [commit for commit in commits if commit in kept], tuple(tips) + tuple(found)
    name, why = band(guard, rules, commits, uncommitted, tips)
    floor = any(fnmatch.fnmatchcase(path, glob) for path in guard.paths_of(commits) + [row.path for row in rows]
                for glob, _level in guard.FLOOR)
    weight = "; weight=%s/%s/%s" % (level, name, "path" if content or floor else "none")
    if content:
        return PAIR, "%s is not in `critical code:` globs alone%s" % (content, weight)
    return TABLE[level][name], "%s: %s%s%s" % (name, why, "; since %s, a unit large on its own" % found[-1][:12]
                                               if found else "", weight)


def weight(entry):
    """(level, band, flag) of a review log ENTRY: its last `weight=` suffix (a `held:` line quotes an older why
    first), or for an entry from before 0.13.0 the lowest weight its level and load had."""
    found = WEIGHT.findall(entry.why)
    if found:
        return found[-1]
    return entry.level, OLD_BANDS.get((entry.level, entry.load), "small"), "none"


def rise(old, new):
    """The parts of weight NEW above every weight in OLD, as `band medium -> large`; empty if none rose."""
    return ["%s %s -> %s" % (part, max((seen[index] for seen in old), key=order.index), new[index])
            for index, (part, order) in enumerate(zip(("level", "band", "path"), WEIGHT_PARTS))
            if all(order.index(new[index]) > order.index(seen[index]) for seen in old)] if old else []


def escalation(guard, start):
    """A git fact that escalates the unit that starts at START, from the review log, or None: history inside it
    was rewritten since `status` last logged it, or its weight rose above every weight logged for it before. It
    reads only the line hold() logged for HEAD, so it shows at every `status` until a new commit."""
    head = guard.git("rev-parse", "HEAD")
    ref = unit_ref(guard)
    mine = [entry for entry in read_log(guard, log_path(guard)) if (entry.ref, entry.start) == (ref, start)]
    if not mine or mine[-1].head != head:
        return None
    prior = [entry for entry in mine if entry.head != head]
    if prior and guard.git("merge-base", "--is-ancestor", prior[-1].head, head, check=False) is None:
        fact = "history inside the unit was rewritten after status logged it at %s" % prior[-1].head[:12]
    else:
        parts = rise([weight(entry) for entry in prior], weight(mine[-1]))
        fact = "the unit's weight rose (%s)" % ", ".join(parts) if parts else None
    return fact and "%s: a fresh adversarial + conformance pair on the whole unit, `git diff %s..HEAD`, as its " \
                    "round two, or the user decides" % (fact, start[:12])


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


def hold(guard, start, level, found, rules=None):
    """(load, why): FOUND, the load measured for the unit that starts at START, or what the review log holds for
    it: the highest load `status` printed since the unit began, and the pair once a commit one was printed at has
    left HEAD's history (amend, squash, rebase). With `cross-check: on` in RULES, the pair's why ends with
    `; cross-check`. Logs what it returns when it differs from the last line."""
    path, ref, head = log_path(guard), unit_ref(guard), guard.git("rev-parse", "HEAD")
    mine = [entry for entry in read_log(guard, path) if (entry.ref, entry.start) == (ref, start)]
    gone = next((entry for entry in mine if guard.git("merge-base", "--is-ancestor", entry.head, "HEAD",
                                                      check=False) is None), None)
    top = max((entry for entry in mine if not entry.why.startswith(REWRITTEN)), key=lambda entry: RANK[entry.load],
              default=None)  # the first printed, if several; a rewrite is judged again each time, never held
    if gone:
        tail = found[1][found[1].rfind("; weight="):] if WEIGHT.search(found[1]) else ""
        found = PAIR, "%s after status printed %s at %s%s" % (REWRITTEN, gone.load, gone.head[:12], tail)
    elif top and RANK[top.load] > RANK[found[0]]:
        found = top.load, "held: status printed it for this unit at %s (%s); now %s" % (top.time, top.why, found[1])
    if found[0] == PAIR and (rules or {}).get("cross-check") == "on" and not found[1].endswith(CROSS_CHECK):
        found = PAIR, found[1] + CROSS_CHECK
    if not mine or (mine[-1].head, mine[-1].load) != (head, found[0]):
        fields = (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), ref, start, head, level) + tuple(found)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", errors="surrogateescape") as handle:
            handle.write("\t".join(re.sub(r"[\t\r\n]", " ", field) for field in fields) + "\n")
    return found
