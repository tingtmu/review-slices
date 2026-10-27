"""review-slices calibrate: what a level costs and why, by review unit.

Imported by calibrate.py from its own directory; it stays in the skill and is never copied into a repo. It loads the
guard, so calibrate.py and these sections judge with the same one, and merged_reviewer.py, so they size a change as
`status` does.

A review unit is what gets one review: a first-parent commit carrying a `Review:` trailer, with the first-parent
commits since the previous unit closed. A pull request a forge merged, or a squash, is a unit of its own. Any other
merge whose other side brings commits (the base branch merged into a branch, then fast-forwarded) cannot be measured
from first-parent history, so its unit is left out of everything but the count; so is a unit the window's start cuts
short. Ambiguous history is left out, which can only understate. In a partial clone only the first section runs.
Standard library only, Python 3.8+, git 2.31+.
"""
import collections
import fnmatch
import importlib.util
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["GIT_NO_LAZY_FETCH"] = "1"  # git 2.44+: never fetch a missing object into the repo being calibrated
LINE_CAPS, FILE_CAPS = (10, 20, 40, 80), (1, 3, 5)
TOP_GLOBS, LISTED = 8, 3
# Never -w: it hides indentation, which is code in Python, YAML and Makefiles.
QUIET_ARGS = ("--ignore-space-at-eol", "--ignore-blank-lines")
# status finds a submodule update in a diff without renames: a moved gitlink pairs as an exact rename.
NO_RENAMES = ("--no-renames",)
PROSE = (".md", ".txt", ".rst")  # in this skill prose is the instructions: never a quiet change
MARKERS = dict([(ext, ("#",)) for ext in (".py", ".sh", ".yml", ".yaml", ".toml", ".r")]
               + [(ext, ("//", "/*", "*/", "* ")) for ext in (".js", ".ts", ".go", ".c", ".h", ".cpp", ".java", ".rs")]
               + [(".sql", ("--",))])
PRAGMAS = ("noqa", "type: ignore", "pylint:", "ruff:", "flake8:", "mypy:", "isort:", "eslint-", "@ts-", "go:", "#!",
           "coding")
# GitHub's and GitLab's merge subjects; git's own for the base branch merged into a branch never match.
FORGE_MERGE = re.compile(r"^Merge (pull request #\d+\b|branch '[^']+' into ')")
SQUASH = re.compile(r" \(#\d+\)$")  # GitHub's squash-merge subject
BURIED = re.compile(r"^Review:\s*(trivial|simple|important|critical)\b", re.I | re.M)

Unit = collections.namedtuple("Unit", "commits declared pull left_out")
FileDiff = collections.namedtuple("FileDiff", "key path binary mode lines")
Size = collections.namedtuple("Size", "lines files binary")
Measured = collections.namedtuple("Measured", "unit level row paths size quiet")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load("review_slices")
sizer = load("merged_reviewer")  # the measure and the review load table `status` uses
git = guard.git


# Review units

def side_commits(commit):
    """The commits a first-parent merge brought in on its other side(s); none for a commit with one parent."""
    return git("rev-list", *commit.others, "--not", commit.parent).split() if commit.others else []


def message_level(commit):
    """The highest review level named anywhere in COMMIT's message (a squash keeps its commits' trailers in its
    body), or None."""
    levels = [level.lower() for level in BURIED.findall(git("log", "-1", "--format=%B", commit.sha))]
    return max(levels, key=guard.rank) if levels else None


def closes_unit(sha):
    """True if the commit SHA ends a review unit: it carries a trailer, or a forge merged or squashed it."""
    parents, subject = git("log", "-1", "--format=%P%x00%s", sha).split("\0", 1)  # strip() eats \x1f
    return bool(guard.trailer_level(sha)) or bool(SQUASH.search(subject)) \
        or (len(parents.split()) > 1 and bool(FORGE_MERGE.match(subject)))


def unit_of(items, declared, left_out=False):
    return Unit(tuple(commit for commit, _side in items), declared, False,
                left_out or any(side for _commit, side in items))


def before_first(items, cut):
    """Commits before the window's first closed unit: one left-out unit if the window CUT it short, else (a history
    that had no trailer before) one unit each."""
    if cut and items:
        return [unit_of(items, None, left_out=True)]
    return [unit_of([item], None) for item in items]


def cut_short(oldest):
    """True if the window's first unit may have begun before OLDEST, whose parent closes none: a first-parent
    ancestor carries a trailer, or a shallow clone hides them."""
    if oldest.parent is None:
        return False
    out = git("log", "--first-parent", "--no-show-signature", "--format=%(trailers:key=Review,valueonly,unfold)",
              oldest.parent, check=False)
    return any(line.split()[0].lower() in guard.LEVELS for line in (out or "").splitlines() if line.split()) \
        or git("rev-parse", "--is-shallow-repository", check=False) == "true"


def pull_request(commit, open_unit):
    """The highest trailer on a first-parent merge's other side, if a forge merged it as a pull request and no unit
    is open before it. Any other merge may be the base branch merged into a branch: left out, which can only
    understate."""
    if open_unit or not commit.others or not FORGE_MERGE.match(commit.subject):
        return None
    levels = [level for level in map(guard.trailer_level, side_commits(commit)) if level]
    return max(levels, key=guard.rank) if levels else None


def review_units(commits):
    """COMMITS (first-parent, oldest first) as review units. A pull request merge or a squash is a unit of its own,
    declared at the highest level its side or message names; commits after the last unit closes, and before the
    first in a history that had none before, are each a unit with no declared level."""
    started = bool(commits) and bool(commits[0].parent) and closes_unit(commits[0].parent)
    cut = bool(commits) and not started and cut_short(commits[0])
    units, pending, seen = [], [], started
    for commit in commits:
        open_unit = bool(pending) and seen or cut and not seen
        pulled = pull_request(commit, open_unit)
        side = bool(side_commits(commit))
        declared = guard.trailer_level(commit.sha)
        whole = pulled or (None if side else message_level(commit))
        if pulled or (whole and declared is None) or (not side and SQUASH.search(commit.subject)):
            if whole and not seen:
                units.extend(before_first(pending, cut))
                pending, seen = [], True
            elif seen:  # on the remote before the forge made this commit: never part of a later unit
                units.extend(unit_of([item], None) for item in pending)
                pending = []
            units.append(Unit((commit,), whole, bool(pulled), False))
            continue
        pending.append((commit, side))
        if declared is None:
            continue
        if not seen and not cut:
            units.extend(before_first(pending[:-1], False))
            pending = pending[-1:]
        units.append(unit_of(pending, declared, left_out=not seen and cut))
        pending, seen = [], True
    return units + [unit_of([item], None) for item in pending]


# Size

def parse_patch(text):
    """[FileDiff] of a `--patch -U0` listing: each file's header line, path, binary and mode-change flags, and its
    added and deleted lines (with their sign). Hunk lengths come from the hunk headers, so a deleted line that starts
    with `--` is never taken for a header."""
    files, old, new = [], 0, 0
    for line in text.split("\n"):
        if old > 0 or new > 0:
            if line.startswith("\\"):
                continue  # "\ No newline at end of file"
            old, new = old - (not line.startswith("+")), new - (not line.startswith("-"))
            if line.startswith(("+", "-")):
                files[-1]["lines"].append(line)
        elif line.startswith("diff --git "):
            files.append({"key": line, "path": None, "binary": False, "mode": False, "lines": []})
        elif not files:
            continue
        elif line.startswith("@@ "):
            match = sizer.HUNK.match(line)
            if not match:
                raise guard.GuardError("unexpected hunk header in git's patch: %r" % line[:80])
            old, new = (int(count) if count is not None else 1 for count in match.groups())
        elif line.startswith("+++ b/") or (line.startswith("--- a/") and files[-1]["path"] is None):
            files[-1]["path"] = line[6:].strip('"')
        elif line.startswith("Binary files ") and line.endswith(" differ"):
            files[-1]["binary"] = True
        elif line.startswith("old mode "):
            files[-1]["mode"] = True
    return [FileDiff(item["key"], item["path"], item["binary"], item["mode"], tuple(item["lines"])) for item in files]


def log_patch(shas, extra=()):
    """The patch of SHAS' own changes, merges left out, read as merged_reviewer.py reads it."""
    if not shas:
        return ""
    return sizer.read_patch(guard, "log", "--no-walk=unsorted", "--no-merges", "--root", "--format=",
                            *(sizer.PATCH_ARGS + extra), *shas)


def unit_patch(unit, extra=()):
    """A pull request's unit is its merge's first-parent change; any other unit is its commits' own changes."""
    if unit.pull:
        merge = unit.commits[0]
        return sizer.read_patch(guard, "diff", *(sizer.PATCH_ARGS + extra), merge.parent, merge.sha)
    return log_patch([commit.sha for commit in unit.commits], extra)


def unit_paths(unit):
    if unit.pull:
        return sorted(guard.changed_paths(unit.commits[0].parent, unit.commits[0].sha))
    return guard.paths_of([commit.sha for commit in unit.commits])


def markers(path):
    name = os.path.basename(path)
    return ("#",) if name == "Makefile" else MARKERS.get(os.path.splitext(name)[1].lower(), ())


def comment_or_blank(path, line):
    text = line[1:].strip()
    if not text:
        return True
    found = markers(path)  # the space lets a lone `*` in a block comment match "* ", never `*p = 1;`
    return bool(found) and (text + " ").startswith(found) and not any(pragma in text for pragma in PRAGMAS)


def quiet(unit, paths, files, size):
    """True if every changed line is blank, differs only in trailing whitespace, or is a comment (an estimate)."""
    if size.binary or not size.lines or any(item.mode for item in files) \
            or any(path.lower().endswith(PROSE) for path in paths):
        return False
    return all(comment_or_blank(item.path or "", line) for item in parse_patch(unit_patch(unit, QUIET_ARGS))
               for line in item.lines)


def measure(config, units):
    """[Measured] for each unit that is not left out."""
    measured = []
    for unit in units:
        if unit.left_out:
            continue
        paths = unit_paths(unit)
        level, rows = guard.range_level(config, paths)
        text = unit_patch(unit)
        files, size = parse_patch(text), Size(*sizer.patch_size(guard, text))  # status's own measure
        measured.append(Measured(unit, level, rows[0] if rows else None, paths, size,
                                 quiet(unit, paths, files, size)))
    return measured


# Section 1: which globs set the levels

def entries(config):
    """(level, pattern, label) for every glob, then the guard's floors."""
    return ([(level, pattern, pattern) for level, pattern in config["globs"]]
            + [(level, pattern, pattern + " (floor)") for pattern, level in guard.FLOOR])


def top_rank(config, table, paths, skip=None):
    """The rank of PATHS' level under TABLE without its entry SKIP, the way guard.range_level ranks them."""
    ranks = [0]
    for path in paths:
        matched = [guard.rank(level) for index, (level, pattern, _label) in enumerate(table)
                   if index != skip and fnmatch.fnmatchcase(path, pattern)]
        ranks.append(max(matched) if matched else guard.rank(config["default"]))
    return max(ranks)


def print_attribution(config, judged):
    """Per first-parent commit: each glob is involved where it matched a path at the commit's level, and alone where
    no other glob or floor reached that level, with the level those commits would have without it."""
    table = entries(config)
    involved, alone = collections.Counter(), collections.defaultdict(collections.Counter)
    for item in judged:
        top = top_rank(config, table, item.paths)
        for index, (level, pattern, _label) in enumerate(table):
            if guard.rank(level) != top or not any(fnmatch.fnmatchcase(path, pattern) for path in item.paths):
                continue
            involved[index] += 1
            without = top_rank(config, table, item.paths, skip=index)
            if without < top:
                alone[index][guard.LEVELS[without]] += 1
    print("glob attribution (per first-parent commit; involved: it matched a path at the commit's level; alone: "
          "nothing else reached that level; floor: the guard's, always at least important):")
    ranked = sorted(involved, key=lambda index: (-involved[index], -sum(alone[index].values()), index))
    for index in ranked[:TOP_GLOBS]:
        level, _pattern, label = table[index]
        instead = ", ".join("%s %d" % pair for pair in sorted(alone[index].items(), key=lambda pair: -pair[1]))
        print("  %-9s  %-36s  involved %3d  alone %3d%s" % (level, label, involved[index],
                                                            sum(alone[index].values()),
                                                            "  (else %s)" % instead if instead else ""))
    if not ranked:
        print("  (no glob or floor set a level)")


# Sections 2-7: review units

def subject(measured):
    commit = measured.unit.commits[-1]
    return "%s  %s" % (commit.short, commit.subject[:50])


def print_units(units):
    undeclared = sum(1 for unit in units if unit.declared is None and not unit.left_out)
    left_out = sum(1 for unit in units if unit.left_out)
    print("review units: %d (%d with no declared level: before the first trailer, after the last unit closed, or a "
          "squash naming none)" % (len(units), undeclared))
    if left_out:
        print("note: %d unit(s) left out of what follows: cut short by the window's start, or a merge in them brought "
              "commits that first-parent history cannot attribute" % left_out)


def print_declared(measured):
    declared = [item for item in measured if item.unit.declared]
    higher = [item for item in declared if guard.rank(item.unit.declared) > guard.rank(item.level)]
    lower = [item for item in declared if guard.rank(item.unit.declared) < guard.rank(item.level)]
    print("declared vs computed by this table (%d unit(s) with a trailer): %d equal, %d declared higher, %d declared "
          "lower" % (len(declared), len(declared) - len(higher) - len(lower), len(higher), len(lower)))
    for word, items in (("higher", higher), ("lower", lower)):
        for item in items[-LISTED:][::-1]:
            print("  %s: %s  declared %s, computed %s" % (word, subject(item), item.unit.declared, item.level))


def nearest_rank(values, share):
    ordered = sorted(values)
    return ordered[max(0, int(math.ceil(share * len(ordered))) - 1)]


def print_sizes(measured):
    sized = [item for item in measured if not item.size.binary]
    print("size by level (per unit; weighted lines: ceil(characters / %d) per added or deleted line):"
          % sizer.LINE_WIDTH)
    for level in guard.LEVELS:
        items = [item for item in sized if item.level == level]
        if items:
            lines, files = [item.size.lines for item in items], [item.size.files for item in items]
            print("  %-9s  %3d unit(s)  lines median %4d, p90 %5d  files median %3d, p90 %3d"
                  % (level, len(items), nearest_rank(lines, 0.5), nearest_rank(lines, 0.9),
                     nearest_rank(files, 0.5), nearest_rank(files, 0.9)))
    if len(sized) < len(measured):
        print("  (%d unit(s) with a binary file left out)" % (len(measured) - len(sized)))


def print_quiet(measured):
    counts = ["%s %d of %d" % (level, sum(1 for item in measured if item.level == level and item.quiet),
                               sum(1 for item in measured if item.level == level)) for level in guard.LEVELS]
    print("whitespace- or comment-only units (an estimate; prose never counts): " + ", ".join(counts))


def floored(item):
    return any(fnmatch.fnmatchcase(path, pattern) for path in item.paths for pattern, _level in guard.FLOOR)


def candidates(measured):
    """Important units with no declared level above it, no floor path and no binary file."""
    return [item for item in measured if item.level == "important" and not item.size.binary
            and (item.unit.declared is None or guard.rank(item.unit.declared) <= guard.rank("important"))
            and not floored(item)]


def print_candidates(measured, listing):
    found = candidates(measured)
    important = sum(1 for item in measured if item.level == "important")
    print("merged-reviewer candidates: %d of %d important unit(s) (per review unit; a push of several units adds "
          "them up, so this overstates pushes that carry several):" % (len(found), important))
    print("  %-10s" % "lines" + "".join("  files <=%-6d" % files for files in FILE_CAPS))
    for lines in LINE_CAPS:
        cells = [sum(1 for item in found if item.size.lines <= lines and item.size.files <= files)
                 for files in FILE_CAPS]
        print("  <=%-8d" % lines + "".join("  %3d %4.0f%%    " % (cell, 100.0 * cell / (important or 1))
                                            for cell in cells))
    if listing:
        lines, files = listing
        print("candidates within %d line(s) and %d file(s), newest first:" % (lines, files))
        for item in reversed(found):
            if item.size.lines <= lines and item.size.files <= files:
                print("  %s  %d line(s), %d file(s)" % (subject(item), item.size.lines, item.size.files))


def status_size(item):
    """(weighted lines, files) of a unit as `status` measured it before the push, each commit summed; None where it
    would be large: a floor path, a binary file added, edited or deleted, a submodule update, or a merge with changes
    of its own. A pull request is sized from its branch's commits, not its net diff; a squash's commits are gone, so
    its diff stands."""
    shas = side_commits(item.unit.commits[0]) if item.unit.pull else [commit.sha for commit in item.unit.commits]
    merges = [sha for sha in shas if len(git("rev-list", "--parents", "-n", "1", sha).split()) > 2]
    if floored(item) or any(guard.commit_paths(sha) for sha in merges):
        return None
    text = log_patch(shas) if item.unit.pull else None
    size = Size(*sizer.patch_size(guard, text)) if text is not None else item.size
    plain = log_patch(shas, NO_RENAMES) if item.unit.pull else unit_patch(item.unit, NO_RENAMES)
    gitlink = re.search(r"^[-+]Subproject commit ", plain, re.M)
    return None if size.binary or gitlink else (size.lines, size.files)


def unit_load(config, item):
    """(band, load, content path or None) of a measured unit, as `status` would give it (status_size); a unit
    declared above its computed level was raised, so it takes three."""
    name = sizer.band_of(config, status_size(item))
    content = sizer.content_path(guard, config, item.level, [row.path for row in guard.range_level(config,
                                                                                                    item.paths)[1]])
    raised = item.unit.declared and guard.rank(item.unit.declared) > guard.rank(item.level)
    return name, sizer.THREE if content or raised else sizer.TABLE[item.level][name], content


def share(name, count, total):
    return "%s %d (%.0f%%)" % (name, count, 100.0 * count / total)


def print_load(config, measured, listing):
    """Section 6: the review load each Important and Critical unit would get under CONFIG's bands and kinds."""
    bands = ", ".join("%s %s" % (name, "%d lines, %d files" % limit if limit else "none")
                      for name, limit in sizer.limits(config).items())
    print("review load (per unit; a branch of several units adds them up, and a squash is sized by its diff, so this "
          "overstates the lighter loads; bands: %s):" % bands)
    loads = [(item, unit_load(config, item)) for item in measured if item.level in sizer.TABLE]
    for level, table in sizer.TABLE.items():
        mine = [found for item, found in loads if item.level == level]
        if not mine:
            continue
        bands, given = collections.Counter(found[0] for found in mine), collections.Counter(found[1] for found in mine)
        print("  %-9s  %3d unit(s)  %s  ->  %s" % (
            level, len(mine), "  ".join(share(name, bands[name], len(mine)) for name in ("small", "medium", "large")),
            ", ".join(share(load, given[load], len(mine)) for load in (sizer.MERGED, sizer.PAIR, sizer.THREE)
                      if load in table.values())))
    small = [(item, found) for item, found in loads if item.level == "critical" and found[0] == "small"]
    print("small critical units: %d, %d of them in `critical code:` globs alone" % (
        len(small), sum(1 for _item, found in small if not found[2])))
    for item, found in reversed(small if listing else []):
        print("  %s  %d line(s), %d file(s)  %s" % (subject(item), item.size.lines, item.size.files,
                                                    "code" if not found[2] else "content: " + found[2]))


def trailer_start(sha):
    """The base sha a commit's last `Review:` trailer names (12 or more hex digits), or None."""
    value = git("log", "-1", "--no-show-signature", "--format=%(trailers:key=Review,valueonly,unfold)", sha)
    words = value.splitlines()[-1].split() if value else []
    return words[1].lower() if len(words) > 1 and re.match(r"^[0-9a-fA-F]{12,40}$", words[1]) else None


def logged_load(logged, sha):
    """The last line of the logged unit a trailer commit SHA closed, or None: the unit whose start its trailer names
    and whose last logged head has its tree (the trailer amend keeps the tree), so `status` measured what was
    reviewed. A unit with commits after its last `status` is not logged."""
    start, tree = trailer_start(sha), git("rev-parse", sha + "^{tree}")
    for (_ref, logged_start), entries in logged.items():
        head = entries[-1].head
        if start and logged_start.startswith(start) and git(
                "rev-parse", "--verify", "--quiet", head + "^{tree}", check=False) == tree:
            return entries[-1]
    return None


def print_logged(measured):
    """Section 7: the load `status` printed for each Important and Critical unit, from this clone's review log."""
    try:
        entries = sizer.read_log(guard, sizer.log_path(guard))
    except guard.GuardError as error:
        print("logged loads: skipped: %s" % error)
        return
    logged = collections.defaultdict(list)
    for entry in entries:
        logged[(entry.ref, entry.start)].append(entry)
    print("logged loads (what `status` printed in this clone; a unit counts when every trailer in it is logged):")
    for level in sizer.TABLE:
        mine = [item for item in measured if item.level == level]
        found = []
        for item in mine:
            closing = item.unit.commits[-1]
            shas = [sha for sha in side_commits(closing) if guard.trailer_level(sha)] if item.unit.pull else (
                [closing.sha] if guard.trailer_level(closing.sha) else [])  # a squash's trailer commits are gone
            lines = [logged_load(logged, sha) for sha in shas]
            if lines and all(lines):
                found.append(max(lines, key=lambda line: sizer.RANK[line.load]))
        if not mine:
            continue
        given = collections.Counter(line.load for line in found)
        print("  %-9s  %3d unit(s), %d logged: %s; held %d, history rewritten %d" % (
            level, len(mine), len(found), ", ".join("%s %d" % (load, given[load]) for load in sizer.RANK),
            sum(1 for line in found if line.why.startswith("held: ")),
            sum(1 for line in found if line.why.startswith(sizer.REWRITTEN))))


def partial_clone():
    """True if a remote of this clone is a promisor (`clone --filter` marks it so; older git also sets
    extensions.partialClone): reading a file's contents may fetch it."""
    promisors = git("config", "--type=bool", "--get-regexp", r"^remote\..*\.promisor$", check=False) or ""
    return bool(git("config", "--get", "extensions.partialClone", check=False)) \
        or any(line.endswith(" true") for line in promisors.splitlines())


def print_sections(config, judged, listing=None):
    """Sections 1-7 after calibrate's own output: JUDGED is its first-parent commits, newest first."""
    print_attribution(config, judged)
    if partial_clone():
        print("note: this is a partial clone, so the review unit sections were skipped: they read file contents, "
              "which git would fetch into it")
        return
    units = review_units([item.commit for item in reversed(judged)])
    measured = measure(config, units)
    print_units(units)
    print_declared(measured)
    print_sizes(measured)
    print_quiet(measured)
    print_candidates(measured, listing)
    print_load(config, measured, listing)
    print_logged(measured)
