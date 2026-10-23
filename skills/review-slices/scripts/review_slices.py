#!/usr/bin/env python3
"""review-slices guard (skill version 0.1.1): review levels, pass stamps and the pre-push check.

    review_slices.py level [BASE]          print the review level of all changes since BASE (commits, edits,
                                           new files) and the trailer to write
    review_slices.py run-suite             run the repo's test command; on a pass, stamp the tested tree
    review_slices.py pre-push REMOTE URL   git pre-push hook: refuse a push with no fitting trailer or stamp

Configuration is the first ```review-slices fenced block in REVIEW.md at the repo root:

    test: cd engine && uv run pytest     # the full offline suite (optional; no stamp check without it)
    base: main                           # branch `level` measures from when there is no upstream (default: main)
    default: simple                      # level of a path no glob matches (default: simple)
    critical: engine/src/*/approval.py   # "<level>: <glob>", one per line; "*" also matches "/"

A path takes the highest level whose glob matches it; a range takes the highest level of its paths. A push is
measured from what the remote already has, and judged by REVIEW.md as committed there, so a change cannot lower
its own bar.
Standard library only, Python 3.8+, git 2.31+.
"""
import collections
import datetime
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile

LEVELS = ("trivial", "simple", "important", "critical")
STAMP_KEEP = 50
OVERRIDE = "If the user decides to push anyway, the user runs `git push --no-verify`; an agent never does."
Row = collections.namedtuple("Row", "path level pattern")


class GuardError(Exception):
    """A problem the user can fix; printed without a traceback."""


def git(*args, check=True):
    done = subprocess.run(("git", "-c", "core.quotePath=false") + args, capture_output=True, text=True)
    if check and done.returncode != 0:
        raise GuardError("git %s failed: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout.strip() if done.returncode == 0 else None


def rank(level):
    return LEVELS.index(level)


def parse_config(text):
    match = re.search(r"^```review-slices\n(.*?)^```", text, re.S | re.M)
    if not match:
        raise GuardError("REVIEW.md has no ```review-slices block")
    config = {"test": None, "base": "main", "default": "simple", "globs": []}
    for number, raw in enumerate(match.group(1).splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, sep, value = (part.strip() for part in line.partition(":"))
        if not sep or not value:
            raise GuardError("review-slices block line %d is not 'key: value': %r" % (number, raw))
        if key in LEVELS:
            config["globs"].append((key, value))
        elif key in ("test", "base"):
            config[key] = value
        elif key == "default" and value in LEVELS:
            config["default"] = value
        else:
            raise GuardError("review-slices block line %d has an unknown key or level: %r" % (number, raw))
    return config


def read_config(root):
    """The working copy's rules (for tests and tooling; the guard itself uses config_at)."""
    path = os.path.join(root, "REVIEW.md")
    if not os.path.exists(path):
        raise GuardError("REVIEW.md not found at the repo root")
    with open(path, encoding="utf-8") as handle:
        return parse_config(handle.read())


def config_at(*commits):
    """The rules in REVIEW.md as committed at the first of COMMITS that has one; None if none has."""
    for commit in commits:
        text = git("show", "%s:REVIEW.md" % commit, check=False)
        if text is not None:
            return parse_config(text + "\n")
    return None


def path_level(config, path):
    """The highest level whose glob matches PATH, with that glob; the default level when none matches."""
    matched = [(level, pattern) for level, pattern in config["globs"] if fnmatch.fnmatchcase(path, pattern)]
    if not matched:
        return config["default"], "no glob: default"
    return max(matched, key=lambda match: rank(match[0]))


def range_level(config, paths):
    if not paths:
        return "trivial", []
    rows = [Row(path, *path_level(config, path)) for path in paths]
    top = max(rank(row.level) for row in rows)
    return LEVELS[top], [row for row in rows if rank(row.level) == top]


def split_nul(out):
    return [path for path in (out or "").split("\0") if path]


def changed_paths(base, head=None):
    """Paths changed from BASE to HEAD (or the working copy); a rename counts at both its old and new path."""
    return split_nul(git("diff", "--name-only", "--no-renames", "-z", base, *([head] if head else [])))


def default_base(config, head="HEAD"):
    branch = git("symbolic-ref", "--short", "--quiet", "HEAD", check=False)
    for remote in ("@{upstream}", "@{push}", "refs/remotes/origin/%s" % branch if branch else None):
        found = remote and git("rev-parse", "--verify", "--quiet", remote, check=False)
        if found:
            return git("merge-base", found, head)
    base = git("merge-base", config["base"], head, check=False)
    if not base:
        raise GuardError("no upstream and no merge-base with %r; pass BASE explicitly" % config["base"])
    return base


def trailer_level(commit):
    """The level of COMMIT's `Review:` trailer (in the message's last paragraph), or None."""
    value = git("log", "-1", "--format=%(trailers:key=Review,valueonly,unfold)", commit)
    words = value.split() if value else []
    return words[0].lower() if words and words[0].lower() in LEVELS else None


def worktree_tree(root):
    """Hash the tree `git add -A` would commit (edits and new unignored files) without touching the real index."""
    index = git("rev-parse", "--path-format=absolute", "--git-path", "index")
    with tempfile.TemporaryDirectory() as tmp:
        temp_index = os.path.join(tmp, "index")
        if os.path.exists(index):
            shutil.copy(index, temp_index)
        env = dict(os.environ, GIT_INDEX_FILE=temp_index)
        try:
            subprocess.run(("git", "add", "-A"), cwd=root, env=env, check=True, capture_output=True)
            return subprocess.run(("git", "write-tree"), cwd=root, env=env, check=True,
                                  capture_output=True, text=True).stdout.strip()
        except subprocess.CalledProcessError as error:
            raise GuardError("could not hash the working tree: %s" % (error.stderr or b"").strip()) from error


def stamp_path():
    return os.path.join(git("rev-parse", "--path-format=absolute", "--git-common-dir"), "review-slices", "suite-pass")


def stamped_trees():
    try:
        with open(stamp_path(), encoding="utf-8") as handle:
            return {line.split()[0] for line in handle if line.strip()}
    except FileNotFoundError:
        return set()


def write_stamp(tree):
    path = stamp_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        lines = []
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join((lines + ["%s %s" % (tree, now)])[-STAMP_KEEP:]) + "\n")


def cmd_level(args):
    """Level of everything since BASE that a commit would carry: commits, edits and new untracked files."""
    root = git("rev-parse", "--show-toplevel")
    base = git("rev-parse", args[0]) if args else default_base(read_config(root))
    config = config_at(base) or read_config(root)
    untracked = split_nul(git("ls-files", "-z", "--others", "--exclude-standard", "--full-name", ":/"))
    level, rows = range_level(config, sorted(set(changed_paths(base) + untracked)))
    print("level: %s" % level)
    for row in rows[:20]:
        print("  %s  (%s)" % (row.path, row.pattern))
    print("trailer: Review: %s %s" % (level, base[:12]))
    return 0


def cmd_run_suite(_args):
    root = git("rev-parse", "--show-toplevel")
    config = config_at("HEAD") or read_config(root)
    if not config["test"]:
        raise GuardError("REVIEW.md's review-slices block names no test command")
    untracked = split_nul(git("ls-files", "-z", "--others", "--exclude-standard", "--full-name", ":/"))
    if untracked:
        print("note: the stamp includes these untracked files; commit them all, or run again without them:\n  "
              + "\n  ".join(untracked[:10]), file=sys.stderr)
    before = worktree_tree(root)
    code = subprocess.run(config["test"], shell=True, cwd=root).returncode
    after = worktree_tree(root)
    if code != 0:
        print("run-suite: the suite failed (exit %d); no stamp written" % code, file=sys.stderr)
        return code
    if before != after:
        print("run-suite: files changed during the run; no stamp written, run it again", file=sys.stderr)
        return 1
    write_stamp(before)
    print("run-suite: passed; stamped tree %s" % before[:12])
    return 0


def push_base(remote, local_sha, remote_sha):
    """(base, problem): what the remote already has that the pushed range starts from, or why it cannot be found.
    Nothing in the pushed commits can move the base: a new branch is measured against every commit the remote is
    known to have, and a clone that never fetched measures from the empty tree (the whole repo)."""
    if remote_sha.strip("0"):
        if git("cat-file", "-e", remote_sha + "^{commit}", check=False) is None:
            return None, "the remote is at %s, which this clone does not have: fetch first" % remote_sha[:12]
        return git("merge-base", remote_sha, local_sha, check=False), None
    new = git("rev-list", "--reverse", "--topo-order", local_sha, "--not", "--remotes=%s" % remote).split()
    if not new:
        return local_sha, None
    parent = git("rev-parse", "--verify", "--quiet", new[0] + "^", check=False)
    return parent or git("hash-object", "-t", "tree", "/dev/null"), None


def commits_since(base, local_sha):
    """Commits from BASE (a commit, or the empty tree) to LOCAL_SHA, oldest first."""
    is_commit = git("cat-file", "-e", base + "^{commit}", check=False) is not None
    return git("rev-list", "--reverse", "%s..%s" % (base, local_sha) if is_commit else local_sha).split()


def review_problems(config, base, local_sha):
    """Each trailer must cover the level of the paths changed since the previous trailer; only trivial work may
    follow the last one."""
    problems, start = [], base
    for commit in commits_since(base, local_sha):
        declared = trailer_level(commit)
        if not declared:
            continue
        level, rows = range_level(config, changed_paths(start, commit))
        if rank(declared) < rank(level):
            problems.append("the trailer on %s says %s, but the commits it covers change %s-level paths, for "
                            "example %s (%s)" % (commit[:12], declared, level, rows[0].path, rows[0].pattern))
        start = commit
    level, rows = range_level(config, changed_paths(start, local_sha))
    if level == "trivial":
        return problems
    if start == base:
        problems.append("the pushed range needs a review at level %s (for example %s matches %s), and no commit "
                        "in it carries `Review: %s ...` or higher" % (level, rows[0].path, rows[0].pattern, level))
    else:
        problems.append("commits after the last review trailer (%s) change %s-level paths, for example %s; "
                        "review them and add a new trailer" % (start[:12], level, rows[0].path))
    return problems


def check_ref(remote, local_sha, remote_sha, stamps):
    """Problems with pushing LOCAL_SHA over REMOTE_SHA; an empty list means the push may go."""
    base, problem = push_base(remote, local_sha, remote_sha)
    if problem:
        return [problem]
    config = config_at(base, local_sha)
    if config is None or not commits_since(base, local_sha):
        return []
    problems = []
    if config["test"] and git("rev-parse", local_sha + "^{tree}") not in stamps:
        problems.append("no pass stamp for %s: run `python3 .githooks/review_slices.py run-suite` on this "
                        "commit (the full suite, once), then push" % local_sha[:12])
    return problems + review_problems(config, base, local_sha)


def cmd_pre_push(args):
    remote = args[0] if args else "origin"
    stamps = stamped_trees()
    problems = []
    for line in sys.stdin:
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 4:
            problems.append("unexpected pre-push input line: %r" % line.strip())
            continue
        _local_ref, local_sha, remote_ref, remote_sha = fields
        if not local_sha.strip("0") or not remote_ref.startswith("refs/heads/"):
            continue  # a deletion, a tag or another non-branch ref
        problems += ["%s: %s" % (remote_ref, problem) for problem in check_ref(remote, local_sha, remote_sha, stamps)]
    if problems:
        print("review-slices refused the push:\n- " + "\n- ".join(problems) + "\n" + OVERRIDE, file=sys.stderr)
        return 1
    return 0


COMMANDS = {"level": cmd_level, "run-suite": cmd_run_suite, "pre-push": cmd_pre_push}


def main(argv):
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        return COMMANDS[argv[1]](argv[2:])
    except GuardError as error:
        print("review-slices: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
