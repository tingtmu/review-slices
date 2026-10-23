#!/usr/bin/env python3
"""review-slices calibrate: show how a level table would have judged the base branch's recent changes.

Run it from inside the target repo, before the table is committed. It stays in the skill and is never copied into a
repo.

    calibrate.py [--count N] [--rules PATH] [--base REF]

It takes the last N first-parent commits of the base branch (default 50) and computes each one's review level from
its own change: a merge from its first parent, the first commit from nothing. The rules come from PATH (default: the
working copy's REVIEW.md, committed or not, so a draft table can be tried). The base is REF, else
`git config review-slices.base`, else origin/HEAD, else main. It prints the level distribution, the three most recent
examples per level with the glob that set it, a warning when the table looks too strict or too loose, and the globs
that matched nothing.
Standard library only, Python 3.8+, git 2.31+.
"""
import argparse
import collections
import fnmatch
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_COUNT = 50
EXAMPLES = 3
TOO_STRICT, TOO_LOOSE = 0.30, 0.60
Commit = collections.namedtuple("Commit", "sha short parent subject")
Judged = collections.namedtuple("Judged", "commit level row")


def load_guard():
    spec = importlib.util.spec_from_file_location("review_slices", os.path.join(HERE, "review_slices.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_guard()
git = guard.git


def resolve(name):
    return git("rev-parse", "--verify", "--quiet", name + "^{commit}", check=False)


def pick_base(given):
    """(name, sha) of the base branch: GIVEN, else review-slices.base, else origin/HEAD, else main."""
    chosen = given or git("config", "--get", "review-slices.base", check=False)
    if chosen:
        sha = resolve(chosen)
        if not sha:
            how = "--base" if given else "git config review-slices.base"
            raise guard.GuardError("the base branch %s (from %s) is not in this clone: fetch it, or pass --base REF"
                                   % (chosen, how))
        return chosen, sha
    for name in ("origin/HEAD", "main"):
        sha = resolve(name)
        if sha:
            return name, sha
    if not git("for-each-ref", "--count=1", "--format=%(refname)", check=False):
        raise guard.GuardError("this repo has no commits yet, so there is nothing to calibrate")
    raise guard.GuardError("found neither origin/HEAD nor main; pass --base REF")


def first_parent_commits(sha, count):
    """The last COUNT first-parent commits up to SHA, newest first."""
    out = git("log", "--first-parent", "--max-count=%d" % count, "--format=%H%x1f%h%x1f%P%x1f%s%x1e", sha)
    commits = []
    for record in out.split("\x1e"):
        fields = record.strip("\n").split("\x1f")
        if len(fields) == 4:
            commits.append(Commit(fields[0], fields[1], (fields[2].split() or [None])[0], fields[3]))
    return commits


def shallow_edge(commits):
    """The COMMITS at the edge of a shallow clone: git shows them with no parent, but they have one."""
    path = git("rev-parse", "--path-format=absolute", "--git-path", "shallow")
    try:
        with open(path, encoding="utf-8") as handle:
            grafted = {line.strip() for line in handle if line.strip()}
    except FileNotFoundError:
        return []
    return [commit for commit in commits if commit.parent is None and commit.sha in grafted]


def load_rules(root, path):
    """(config, label): the rules in PATH, or in the working copy's REVIEW.md."""
    label = path or "REVIEW.md (working copy)"
    path = path or os.path.join(root, "REVIEW.md")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        raise guard.GuardError("%s not found: write the draft table there, or pass --rules PATH" % path) from None
    except (OSError, UnicodeDecodeError) as error:
        raise guard.GuardError("could not read %s: %s" % (path, error)) from None
    try:
        config = guard.parse_config(text)
    except guard.GuardError as error:
        raise guard.GuardError("%s: %s" % (label, error)) from None
    for message in config["errors"] + config["warnings"]:
        print("note: %s: %s" % (label, message))
    return config, label


def judge(config, commits):
    """([Judged], paths): each commit's level from its first-parent change, and every path the commits touched."""
    judged, touched, empty = [], set(), None
    for commit in commits:
        if commit.parent is None and empty is None:
            empty = git("hash-object", "-t", "tree", "/dev/null")
        paths = guard.changed_paths(commit.parent or empty, commit.sha)
        touched.update(paths)
        level, rows = guard.range_level(config, paths)
        judged.append(Judged(commit, level, rows[0] if rows else None))
    return judged, touched


def unmatched(config, paths):
    return ["%s: %s" % (level, pattern) for level, pattern in config["globs"]
            if not any(fnmatch.fnmatchcase(path, pattern) for path in paths)]


def print_distribution(judged):
    counts = collections.Counter(item.level for item in judged)
    print("level distribution:")
    for level in guard.LEVELS:
        print("  %-9s  %3d  %3.0f%%" % (level, counts[level], 100.0 * counts[level] / len(judged)))
    share = {level: float(counts[level]) / len(judged) for level in guard.LEVELS}
    if share["critical"] > TOO_STRICT:
        print("warning: %.0f%% are critical: most changes would need three reviewers and the user's go-ahead; people "
              "will route around it. Narrow the critical globs." % (100 * share["critical"]))
    if share["trivial"] > TOO_LOOSE:
        print("warning: %.0f%% are trivial, so most changes would get no review at all. Check that the trivial globs "
              "and the default level are not too wide." % (100 * share["trivial"]))


def print_examples(judged):
    print("recent examples (newest first):")
    for level in reversed(guard.LEVELS):
        examples = [item for item in judged if item.level == level][:EXAMPLES]
        if examples:
            print("  %s:" % level)
        for item in examples:
            where = "%s  (%s)" % (item.row.path, item.row.pattern) if item.row else "(no file changed)"
            print("    %s  %s  %s" % (item.commit.short, item.commit.subject[:60], where))


def report(name, sha, label, config, count):
    commits = first_parent_commits(sha, count)
    edge = shallow_edge(commits)
    commits = [commit for commit in commits if commit not in edge]
    if not commits:
        raise guard.GuardError("this shallow clone has too little history to judge; `git fetch --deepen=%d` "
                               "brings more" % count)
    judged, touched = judge(config, commits)
    print("calibrate: %d first-parent commit(s) of %s (%s), judged by %s" % (len(judged), name, sha[:12], label))
    if edge:
        print("note: this is a shallow clone, so %d commit(s) at its edge were left out (their parents are not "
              "here); `git fetch --deepen=%d` brings more history" % (len(edge), count))
    elif len(judged) < count:
        print("note: the base branch has only %d commit(s), fewer than --count %d" % (len(judged), count))
    print_distribution(judged)
    print_examples(judged)
    never = unmatched(config, touched)
    if never:
        print("globs that matched no path in these commits (too narrow, misspelt, or for paths that rarely change):"
              "\n  " + "\n  ".join(never))
    else:
        print("every glob matched at least one path in these commits")
    return 0


def positive(text):
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError("expected a whole number above 0, not %r" % text)
    return int(text)


def main(argv):
    parser = argparse.ArgumentParser(prog="calibrate.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=positive, default=DEFAULT_COUNT, metavar="N",
                        help="how many first-parent commits to judge (default %d)" % DEFAULT_COUNT)
    parser.add_argument("--rules", metavar="PATH", help="the REVIEW.md to take the rules from")
    parser.add_argument("--base", metavar="REF", help="the base branch to read the commits from")
    options = parser.parse_args(argv[1:])
    try:
        root = git("rev-parse", "--show-toplevel")
        name, sha = pick_base(options.base)
        config, label = load_rules(root, options.rules)
        return report(name, sha, label, config, options.count)
    except guard.GuardError as error:
        print("review-slices: %s" % error, file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print("review-slices: a path in these commits is not UTF-8, which the guard cannot read yet; rename it, or "
              "pass --count or --base to leave that commit out", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
