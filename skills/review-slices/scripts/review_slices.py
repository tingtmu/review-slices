#!/usr/bin/env python3
"""review-slices guard (skill version 0.2.0): review levels, pass stamps and the pre-push check.

    review_slices.py level [BASE]          print the review level of all changes since BASE (commits, edits,
                                           new files) and the trailer to write
    review_slices.py check                 lint REVIEW.md's review-slices block; exit 1 on an error
    review_slices.py run-suite             run every check in the suite; on a pass, stamp the tested tree
    review_slices.py pre-push REMOTE URL   git pre-push hook: refuse a push with no fitting trailer or stamp

Configuration is the first ```review-slices fenced block in REVIEW.md at the repo root:

    test: cd engine && uv run pytest     # one check of the suite; repeat the key per check, all are required
    base: main                           # branch `level` measures from when there is no upstream (default: main)
    default: simple                      # level of a path no glob matches (default: simple)
    critical: engine/src/*/approval.py   # "<level>: <glob>", one per line; "*" also matches "/"

A path takes the highest level whose glob matches it, and REVIEW.md and .githooks/* are always at least important;
a range takes the highest level of its paths. A push is measured from what the remote already has, and its levels
come from REVIEW.md as committed there, so a change cannot lower the levels it is judged by. A change to the suite
is reported and reviewed (REVIEW.md is at least important), not blocked.
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
import time

VERSION = "0.2.0"
LEVELS = ("trivial", "simple", "important", "critical")
FLOOR = (("REVIEW.md", "important"), (".githooks/*", "important"))
STAMP_KEEP = 50
OVERRIDE = "If the user decides to push anyway, the user runs `git push --no-verify`; an agent never does."
# Settings in a user's git config that would change what the guard reads.
GIT_SETTINGS = ("-c", "core.quotePath=false", "-c", "color.ui=never", "-c", "log.showSignature=false",
                "-c", "diff.relative=false")
DIFF_PATHS = ("--name-only", "--no-renames", "--ignore-submodules=none", "--no-ext-diff", "--no-relative", "-z")
COMMENT = re.compile(r"(?:^|\s)#.*$")
PLACEHOLDER = re.compile(r"<[A-Za-z][^<>]*>")
Row = collections.namedtuple("Row", "path level pattern")


class GuardError(Exception):
    """A problem the user can fix; printed without a traceback."""


def git(*args, check=True):
    done = subprocess.run(("git",) + GIT_SETTINGS + args, capture_output=True, text=True)
    if check and done.returncode != 0:
        raise GuardError("git %s failed: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout.strip() if done.returncode == 0 else None


def rank(level):
    return LEVELS.index(level)


def parse_config(text):
    """The first review-slices block of TEXT. Problems that leave the rules usable go to "errors" and "warnings"
    for `check`; only an unusable block raises GuardError."""
    match = re.search(r"^```review-slices[ \t]*\r?\n(.*?)^```", text, re.S | re.M)
    if not match:
        raise GuardError("REVIEW.md has no ```review-slices block")
    config = {"tests": [], "base": "main", "default": "simple", "globs": [], "errors": [], "warnings": []}
    seen = set()
    for number, raw in enumerate(match.group(1).splitlines(), 1):
        line = COMMENT.sub("", raw).strip()
        if not line:
            continue
        key, sep, value = (part.strip() for part in line.partition(":"))
        if not sep or not value:
            raise GuardError("review-slices block line %d is not 'key: value': %r" % (number, raw))
        if PLACEHOLDER.search(value):
            config["errors"].append("line %d still holds a template placeholder: %s" % (number, line))
        if key in LEVELS:
            globs = [glob.strip() for glob in value.split(",") if glob.strip()]
            if len(globs) > 1:
                config["warnings"].append("line %d is read as %d globs; write one glob per line" % (number, len(globs)))
            config["globs"] += [(key, glob) for glob in globs]
        elif key == "test":
            config["tests"].append(value)
        elif key == "base" or (key == "default" and value in LEVELS):
            if key in seen:
                config["errors"].append("line %d repeats %r; the last one counts" % (number, key))
            seen.add(key)
            config[key] = value
        else:
            raise GuardError("review-slices block line %d has an unknown key or level: %r" % (number, raw))
    return config


def unreadable_rules(reason):
    """Rules for a REVIEW.md that does not parse: every path is critical and a stamp is required, but nothing is
    refused outright, so the push that fixes the file can still go after a critical review."""
    return {"tests": ["?"], "base": "main", "default": "critical", "globs": [("critical", "*")], "errors": [reason],
            "warnings": [], "unreadable": reason}


def read_config(root):
    """The working copy's rules."""
    path = os.path.join(root, "REVIEW.md")
    if not os.path.exists(path):
        raise GuardError("REVIEW.md not found at the repo root")
    with open(path, encoding="utf-8") as handle:
        return parse_config(handle.read())


def rules_text(commit):
    return git("show", "%s:REVIEW.md" % commit, check=False)


def rules_at(commit):
    """REVIEW.md's rules as committed at COMMIT: None if it has none, every path critical if they do not parse."""
    text = rules_text(commit)
    if text is None:
        return None
    try:
        return parse_config(text + "\n")
    except GuardError as error:
        return unreadable_rules("REVIEW.md at %s does not parse (%s), so every path counts as critical; fix it "
                                "on the base branch" % (commit[:12], error))


def path_level(config, path):
    """The highest level whose glob matches PATH, with that glob; the default level when none matches."""
    matched = [(level, pattern) for level, pattern in config["globs"] if fnmatch.fnmatchcase(path, pattern)]
    matched += [(level, "always at least " + level) for pattern, level in FLOOR if fnmatch.fnmatchcase(path, pattern)]
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
    """Paths changed from BASE to HEAD (or the working copy). A rename counts at both its old and new path, and a
    submodule update counts whatever .gitmodules or the user's config say."""
    return split_nul(git("diff", *DIFF_PATHS, base, *([head] if head else [])))


def untracked_paths():
    return split_nul(git("ls-files", "-z", "--others", "--exclude-standard", "--full-name", ":/"))


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
    value = git("log", "-1", "--no-show-signature", "--format=%(trailers:key=Review,valueonly,unfold)", commit)
    words = value.split() if value else []
    return words[0].lower() if words and words[0].lower() in LEVELS else None


def suite_change(old, new):
    """A note when NEW's suite differs from OLD's, or None."""
    if old is None or new is None or old["tests"] == new["tests"]:
        return None
    lines = ["  - " + test for test in old["tests"] if test not in new["tests"]]
    lines += ["  + " + test for test in new["tests"] if test not in old["tests"]]
    return "this change edits the suite; reviewers must confirm it is not weaker:\n" + "\n".join(lines or ["  (order)"])


def base_resolves(base):
    return bool(git("for-each-ref", "--format=%(refname)", "refs/heads/" + base, "refs/remotes/*/" + base,
                    check=False))


def lint(config):
    """(errors, warnings) about CONFIG as rules for this repo."""
    errors, warnings = list(config["errors"]), list(config["warnings"])
    tracked = split_nul(git("ls-files", "-z", "--full-name", ":/"))
    for level, pattern in config["globs"]:
        matcher = re.compile(fnmatch.translate(pattern))
        if not any(matcher.match(path) for path in tracked):
            warnings.append("%s: %s matches no tracked file" % (level, pattern))
    if not base_resolves(config["base"]):
        errors.append("base: %s is neither a local branch nor a remote-tracking branch" % config["base"])
    if not config["tests"]:
        warnings.append("no test line, so pushes need no pass stamp")
    return errors, warnings


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
            detail = error.stderr if isinstance(error.stderr, str) else (error.stderr or b"").decode(errors="replace")
            raise GuardError("could not hash the working tree: %s" % detail.strip()) from error


def stamp_path():
    return os.path.join(git("rev-parse", "--path-format=absolute", "--git-common-dir"), "review-slices", "suite-pass")


def stamped_trees():
    try:
        with open(stamp_path(), encoding="utf-8") as handle:
            return {line.split()[0] for line in handle if line.strip()}
    except FileNotFoundError:
        return set()


def write_stamp(tree, seconds):
    path = stamp_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        lines = []
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join((lines + ["%s %s %.0fs" % (tree, now, seconds)])[-STAMP_KEEP:]) + "\n")


def print_lint(config, where):
    """Print CONFIG's lint messages; return them as (errors, warnings)."""
    errors, warnings = lint(config)
    for message in errors:
        print("error in %s: %s" % (where, message))
    for message in warnings:
        print("warning in %s: %s" % (where, message))
    return errors, warnings


def cmd_level(args):
    """Level of everything since BASE that a commit would carry: commits, edits and new untracked files."""
    root = git("rev-parse", "--show-toplevel")
    working = read_config(root) if os.path.exists(os.path.join(root, "REVIEW.md")) else None
    base = git("rev-parse", args[0]) if args else default_base(working or {"base": "main"})
    config = rules_at(base) or working
    if config is None:
        raise GuardError("REVIEW.md not found at the repo root or at %s" % base[:12])
    level, rows = range_level(config, sorted(set(changed_paths(base) + untracked_paths())))
    print("level: %s" % level)
    for row in rows[:20]:
        print("  %s  (%s)" % (row.path, row.pattern))
    print("trailer: Review: %s %s" % (level, base[:12]))
    note = suite_change(config, working)
    if note:
        print("note: " + note)
    shown = set()
    if working is not None:
        errors, warnings = print_lint(working, "REVIEW.md")
        shown = set(errors + warnings)
    for message in config["errors"] + config["warnings"]:
        if config is not working and message not in shown:
            print("note: REVIEW.md at %s, the rules this change is judged by (fix it on the base branch): %s"
                  % (base[:12], message))
    return 0


def cmd_check(_args):
    root = git("rev-parse", "--show-toplevel")
    errors, _warnings = print_lint(read_config(root), "REVIEW.md")
    print("check: %s" % ("%d error(s)" % len(errors) if errors else "ok"))
    return 1 if errors else 0


def cmd_run_suite(_args):
    """Run each check of the suite listed in the working copy's REVIEW.md, which is part of the tree it stamps."""
    root = git("rev-parse", "--show-toplevel")
    config = read_config(root)
    if not config["tests"]:
        raise GuardError("REVIEW.md's review-slices block names no test command")
    untracked = untracked_paths()
    if untracked:
        print("note: the stamp includes these untracked files; commit them all, or run again without them:\n  "
              + "\n  ".join(untracked[:10]), file=sys.stderr)
    before, started = worktree_tree(root), time.monotonic()
    for number, command in enumerate(config["tests"], 1):
        print("run-suite: [%d/%d] %s" % (number, len(config["tests"]), command), flush=True)
        began = time.monotonic()
        code = subprocess.run(command, shell=True, cwd=root).returncode
        if code != 0:
            print("run-suite: check %d failed (exit %d after %.0fs); no stamp written"
                  % (number, code, time.monotonic() - began), file=sys.stderr)
            return code
    after = worktree_tree(root)
    if before != after:
        moved = split_nul(git("diff-tree", "-r", "-z", "--name-only", before, after))
        print("run-suite: these files changed during the run, so no stamp was written; ignore or fix them and run "
              "again:\n  " + "\n  ".join(moved[:10]), file=sys.stderr)
        return 1
    seconds = time.monotonic() - started
    write_stamp(before, seconds)
    print("run-suite: passed in %.0fs; stamped tree %s" % (seconds, before[:12]))
    return 0


def push_base(remote, local_sha, remote_sha):
    """(base, problem): what the remote already has that the pushed range starts from, or why it cannot be found.
    Nothing in the pushed commits can move the base: a new ref is measured against every commit the remote is
    known to have, and a clone that never fetched measures from the empty tree (the whole repo)."""
    if remote_sha.strip("0"):
        remote_commit = git("rev-parse", "--verify", "--quiet", remote_sha + "^{commit}", check=False)
        if not remote_commit:
            return None, "the remote is at %s, which this clone does not have: fetch first" % remote_sha[:12]
        return git("merge-base", remote_commit, local_sha, check=False), None
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


def standing_rules(base, local_sha):
    """(rules, problem, notes): the rules a push from BASE to LOCAL_SHA is judged by. A push may bring REVIEW.md
    (adoption) but never take it away."""
    config, head = rules_at(base), rules_text(local_sha)
    if config is not None and head is None:
        return None, "this push deletes or moves REVIEW.md; removing the rules is the user's decision", []
    if config is not None:
        return config, None, []
    config = rules_at(local_sha)
    if config is not None:
        return config, None, ["REVIEW.md is new in this push, so its own rules judge it"]
    deleted = git("log", "-1", "--format=%h", "--no-renames", "--diff-filter=D", local_sha, "--", "REVIEW.md",
                  check=False)
    if deleted:
        return None, "REVIEW.md was deleted or moved in %s, so nothing would check this push: restore it" % deleted, []
    return None, None, ["no REVIEW.md on this ref or at the remote, so the push is not checked"]


def check_ref(remote, local_sha, remote_sha, stamps):
    """(problems, notes) for pushing LOCAL_SHA over REMOTE_SHA; no problems means the push may go."""
    base, problem = push_base(remote, local_sha, remote_sha)
    if problem:
        return [problem], []
    if not commits_since(base, local_sha):
        return [], []
    config, problem, notes = standing_rules(base, local_sha)
    if problem or config is None:
        return [problem] if problem else [], notes
    notes = notes + [note for note in (config.get("unreadable"), suite_change(config, rules_at(local_sha))) if note]
    problems = []
    if config["tests"] and git("rev-parse", local_sha + "^{tree}") not in stamps:
        problems.append("no pass stamp for %s: run `python3 .githooks/review_slices.py run-suite` on this "
                        "commit (the full suite, once), then push" % local_sha[:12])
    return problems + review_problems(config, base, local_sha), notes


def cmd_pre_push(args):
    remote = args[0] if args else "origin"
    stamps = stamped_trees()
    problems, notes = [], []
    for line in sys.stdin:
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 4:
            problems.append("unexpected pre-push input line: %r" % line.strip())
            continue
        _local_ref, local_sha, remote_ref, remote_sha = fields
        if not local_sha.strip("0") or not remote_ref.startswith(("refs/heads/", "refs/tags/")):
            continue  # a deletion, or a ref that is neither a branch nor a tag
        local_commit = git("rev-parse", "--verify", "--quiet", local_sha + "^{commit}", check=False)
        if not local_commit:
            continue  # a tag of a tree or a blob
        ref_problems, ref_notes = check_ref(remote, local_commit, remote_sha, stamps)
        problems += ["%s: %s" % (remote_ref, problem) for problem in ref_problems]
        notes += ["%s: %s" % (remote_ref, note) for note in ref_notes]
    if notes:
        print("review-slices: " + "\nreview-slices: ".join(notes), file=sys.stderr)
    if problems:
        print("review-slices refused the push:\n- " + "\n- ".join(problems) + "\n" + OVERRIDE, file=sys.stderr)
        return 1
    return 0


COMMANDS = {"level": cmd_level, "check": cmd_check, "run-suite": cmd_run_suite, "pre-push": cmd_pre_push}


def main(argv):
    if argv[1:] == ["--version"]:
        print(VERSION)
        return 0
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        return COMMANDS[argv[1]](argv[2:])
    except GuardError as error:
        print("review-slices: %s" % error, file=sys.stderr)
        if argv[1] == "pre-push":
            print(OVERRIDE, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
