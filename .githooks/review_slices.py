#!/usr/bin/env python3
"""review-slices guard (skill version 0.3.0): review levels, pass stamps and the pre-push check.

    review_slices.py status [BASE]         where this work stands: its review level and the trailer to write, the
                                           rules it is judged by, the pass stamp, the hook, and the next step
    review_slices.py level [BASE]          the same as status
    review_slices.py check                 lint REVIEW.md's review-slices block; exit 1 on an error
    review_slices.py run-suite             run every check in the suite; on a pass, stamp the tested tree
    review_slices.py pre-push REMOTE URL   git pre-push hook: refuse a push with no fitting trailer or stamp
    review_slices.py --version

Configuration is the first ```review-slices fenced block in REVIEW.md at the repo root:

    test: cd engine && uv run pytest     # one check of the suite; repeat the key per check, all are required
    base: main                           # the base branch (default: main)
    default: simple                      # level of a path no glob matches (default: simple)
    critical: engine/src/*/approval.py   # "<level>: <glob>", one per line; "*" also matches "/"

A path takes the highest level whose glob matches it, and REVIEW.md and .githooks/* are always at least important;
a range takes the highest level of its paths. The standing rules judge a change: REVIEW.md as committed where its
branch left the base branch, so a change cannot lower the levels it is judged by. A change to the suite is reported
and reviewed (REVIEW.md is at least important), not blocked. `status` and `pre-push` hand off to the guard committed
on the base branch when this copy differs from it, so an edited copy does not judge its own push.
Standard library only, Python 3.8+, git 2.32+.
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

VERSION = "0.3.0"
LEVELS = ("trivial", "simple", "important", "critical")
FLOOR = (("REVIEW.md", "important"), (".githooks/*", "important"))
GUARD_PATH = ".githooks/review_slices.py"
HANDOFF = "REVIEW_SLICES_HANDOFF"
# The first guard version that has each command; the base branch's guard runs a command only if it has it.
SINCE = {"level": (0, 1, 0), "run-suite": (0, 1, 0), "pre-push": (0, 1, 0), "check": (0, 2, 0),
         "status": (0, 3, 0)}
SLICE2 = {"trivial": "no review",
          "simple": "1-2 adversarial reviewers",
          "important": "a Standards, a Spec and an adversarial reviewer",
          "critical": "a Standards, a Spec and an adversarial reviewer, then the user's go-ahead for the one-way door"}
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


def git_raw(*args):
    """git's stdout, unstripped, or None if git failed."""
    done = subprocess.run(("git",) + GIT_SETTINGS + args, capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else None


def git(*args, check=True):
    done = subprocess.run(("git",) + GIT_SETTINGS + args, capture_output=True, text=True)
    if check and done.returncode != 0:
        raise GuardError("git %s failed: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout.strip() if done.returncode == 0 else None


def rank(level):
    return LEVELS.index(level)


def version_tuple(text):
    parts = [int(part) for part in re.findall(r"\d+", text or "")[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def source_version(source):
    """The version of the guard whose source is SOURCE; 0.1.0 named it only in its docstring."""
    match = re.search(r'^VERSION = "([\d.]+)"', source, re.M) or re.search(r"skill version ([\d.]+)", source)
    return version_tuple(match.group(1)) if match else (0, 1, 0)


def git_version():
    return version_tuple(git("--version"))


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


def working_config(root):
    return read_config(root) if os.path.exists(os.path.join(root, "REVIEW.md")) else None


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


def base_tip():
    """(name, sha): the base branch's remote-tracking ref, as this clone last fetched it, and its commit (None if it
    does not resolve). The name comes from `review-slices.base`, which `install` records, else origin's default
    branch; never from the REVIEW.md being judged, which could point the judge at itself."""
    name = (git("config", "--get", "review-slices.base", check=False)
            or git("symbolic-ref", "--short", "--quiet", "refs/remotes/origin/HEAD", check=False) or "origin/main")
    return name, git("rev-parse", "--verify", "--quiet", "refs/remotes/%s^{commit}" % name, check=False)


def standing_commit(local_sha, others=()):
    """The commit whose REVIEW.md judges LOCAL_SHA: where it left the base branch, else where it left one of
    OTHERS (the ref it is pushed over); None if it shares no history with them."""
    for other in (base_tip()[1],) + tuple(others):
        found = other and git("merge-base", local_sha, other, check=False)
        if found:
            return found
    return None


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


def hook_wiring():
    """How this clone's pre-push reaches the guard, or None if it does not."""
    if git_version() >= (2, 54) and "review-slices" in (git("hook", "list", "pre-push", check=False) or "").split():
        return "config hook review-slices"
    hook = git("rev-parse", "--path-format=absolute", "--git-path", "hooks/pre-push")
    for path in (hook, hook + ".legacy"):
        if os.access(path, os.X_OK):
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            if "review-slices/bootstrap.py" in text:
                return "hook file " + path
            if "review_slices.py" in text:
                return "hook file %s (0.1.0's: it runs the checkout's guard; run setup_tools.py install)" % path
    return None


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


def stamps():
    """{tree: the rest of its stamp line} for every stamped tree."""
    try:
        with open(stamp_path(), encoding="utf-8") as handle:
            pairs = [line.split(None, 1) for line in handle if line.strip()]
    except FileNotFoundError:
        return {}
    return {pair[0]: (pair[1].strip() if len(pair) > 1 else "") for pair in pairs}


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


def handoff(command, args, data=None):
    """The exit code of the base branch's guard, run instead of this copy, or None to run this copy. The base's
    guard runs when it differs from this file and has COMMAND, so an edited copy does not judge its own push."""
    if os.environ.get(HANDOFF):
        return None
    _name, tip = base_tip()
    source = tip and git_raw("show", "%s:%s" % (tip, GUARD_PATH))
    if not source:
        return None
    with open(os.path.abspath(__file__), encoding="utf-8") as handle:
        if handle.read() == source:
            return None
    if source_version(source) < SINCE[command]:
        print("review-slices: the base branch's guard (%s) has no `%s`, so this copy (%s) runs"
              % (".".join(map(str, source_version(source))), command, VERSION), file=sys.stderr)
        return None
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "review_slices.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        return subprocess.run((sys.executable, path, command) + tuple(args), input=data, text=True,
                              env=dict(os.environ, **{HANDOFF: "1"})).returncode


def print_rule_messages(standing, working, at):
    """Lint messages for this change's REVIEW.md and the standing rules, each labelled with where to fix it."""
    inherited = set() if standing is working else set(sum(lint(standing), []))
    if working is not None:
        errors, warnings = lint(working)
        for kind, messages in (("error", errors), ("warning", warnings)):
            for message in messages:
                where = ("the standing rules at %s (fix on the base branch, not in this change)" % at
                         if message in inherited else "REVIEW.md")
                print("%s in %s: %s" % (kind, where, message))
        inherited -= set(errors + warnings)
    for message in sorted(inherited):
        print("note: in the standing rules at %s (fix on the base branch, not in this change): %s" % (at, message))


def print_lint(config, where):
    """Print CONFIG's lint messages; return them as (errors, warnings)."""
    errors, warnings = lint(config)
    for message in errors:
        print("error in %s: %s" % (where, message))
    for message in warnings:
        print("warning in %s: %s" % (where, message))
    return errors, warnings


def last_trailer(commits):
    """The last of COMMITS that carries a review trailer, or None."""
    return next((commit for commit in reversed(commits) if trailer_level(commit)), None)


def next_step(config, level, start, base, commits, uncommitted):
    if uncommitted:
        return "commit this work locally (no trailer yet), then run status again"
    if level != "trivial":
        return ("review at %s: %s, on `git diff %s..HEAD`; then add the trailer to the last commit with "
                "`git commit --amend --only --no-edit --trailer \"Review: %s %s\"`"
                % (level, SLICE2[level], start[:12], level, start[:12]))
    problems = review_problems(config, base, "HEAD")
    if problems:
        return "fix the trailers: " + problems[0]
    if config["tests"] and commits and git("rev-parse", "HEAD^{tree}") not in stamps():
        return "run the suite: python3 %s run-suite" % GUARD_PATH
    return "ask the user's go-ahead, then push" if commits else "nothing to push"


def cmd_status(args):
    """Where this work stands. The level covers the open review unit: commits since the last trailer, plus edits
    and new files a commit would carry."""
    root = git("rev-parse", "--show-toplevel")
    working = working_config(root)
    base = git("rev-parse", args[0]) if args else default_base(working or {"base": "main"})
    tip_name, _tip = base_tip()
    standing = standing_commit("HEAD")
    config = (standing and rules_at(standing)) or rules_at(base) or working
    if config is None:
        raise GuardError("REVIEW.md not found at the repo root or at %s" % base[:12])
    commits = commits_since(base, "HEAD")
    start = last_trailer(commits) or base
    uncommitted = sorted(set(changed_paths("HEAD") + untracked_paths()))
    level, rows = range_level(config, sorted(set(changed_paths(start) + untracked_paths())))
    print("level: %s" % level)
    for row in rows[:20]:
        print("  %s  (%s)" % (row.path, row.pattern))
    print("trailer: Review: %s %s" % (level, start[:12]))
    print("standing rules: %s" % ("REVIEW.md at %s, where this branch left %s" % (standing[:12], tip_name)
                                  if standing and rules_at(standing) else "this branch's own REVIEW.md (%s not fetched "
                                  "or without one)" % tip_name))
    stamp = stamps().get(worktree_tree(root))
    print("pass stamp: %s" % ("yes, " + stamp if stamp is not None else "none for the working tree"))
    wiring = hook_wiring()
    print("hook: %s" % (wiring or "NOT WIRED: pushes from this clone are not checked; run the skill's "
                                  "setup_tools.py install"))
    note = suite_change(config, working)
    if note:
        print("note: " + note)
    print_rule_messages(config, working, (standing or base)[:12])
    print("next: " + next_step(config, level, start, base, commits, uncommitted))
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
    if not hook_wiring():
        print("warning: this clone's pre-push does not reach the guard; run the skill's setup_tools.py install",
              file=sys.stderr)
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
    head = git("rev-parse", "--verify", "--quiet", "HEAD^{tree}", check=False)
    if head and head != before:
        differ = split_nul(git("diff-tree", "-r", "-z", "--name-only", head, before))
        print("run-suite: the suite passed on the working tree (stamped %s), but that is NOT HEAD's tree, so a push "
              "of HEAD has no stamp. These paths differ from HEAD:\n  %s\nCommit them if they are this work's; if "
              "they are not yours, ask the user before touching them." % (before[:12], "\n  ".join(differ[:10])),
              file=sys.stderr)
        return 0
    print("run-suite: passed in %.0fs; stamped tree %s, which is HEAD's" % (seconds, before[:12]))
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


def standing_rules(base, local_sha, remote_sha):
    """(rules, problem, notes): the standing rules for pushing LOCAL_SHA, whose new commits start after BASE. A push
    may bring REVIEW.md (adoption) but never take it away."""
    standing = standing_commit(local_sha, (remote_sha,) if remote_sha.strip("0") else ())
    config = (standing and rules_at(standing)) or rules_at(base)
    if config is not None and rules_text(local_sha) is None:
        return None, "this push deletes or moves REVIEW.md; removing the rules is the user's decision", []
    if config is not None:
        return config, None, []
    config = rules_at(local_sha)
    if config is not None:
        return config, None, ["REVIEW.md is new in this push, so its own rules judge it"]
    deleted = git("log", "-1", "--format=%h", "--no-renames", "--diff-filter=D", local_sha, "--", "REVIEW.md",
                  check=False)
    if deleted:
        return None, None, ["REVIEW.md was deleted in %s, before this push, so the push is NOT checked; restoring it "
                            "is the user's decision" % deleted]
    return None, None, ["no REVIEW.md on this ref or at the remote, so the push is not checked"]


def check_ref(remote, local_sha, remote_sha, stamped):
    """(problems, notes) for pushing LOCAL_SHA over REMOTE_SHA; no problems means the push may go."""
    base, problem = push_base(remote, local_sha, remote_sha)
    if problem:
        return [problem], []
    if not commits_since(base, local_sha):
        return [], []
    config, problem, notes = standing_rules(base, local_sha, remote_sha)
    if problem or config is None:
        return [problem] if problem else [], notes
    notes = notes + [note for note in (config.get("unreadable"), suite_change(config, rules_at(local_sha))) if note]
    problems = []
    if config["tests"] and git("rev-parse", local_sha + "^{tree}") not in stamped:
        problems.append("no pass stamp for %s: run `python3 %s run-suite` on this commit (the full suite, once), "
                        "then push" % (local_sha[:12], GUARD_PATH))
    return problems + review_problems(config, base, local_sha), notes


def cmd_pre_push(args, data=""):
    remote = args[0] if args else "origin"
    stamped = stamps()
    problems, notes = [], []
    for line in data.splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 4:
            problems.append("unexpected pre-push input line: %r" % line.strip())
            continue
        _local_ref, local_sha, remote_ref, remote_sha = fields
        if not local_sha.strip("0"):
            continue  # a deletion
        local_commit = git("rev-parse", "--verify", "--quiet", local_sha + "^{commit}", check=False)
        if remote_ref.startswith("refs/notes/") or not local_commit:
            notes.append("%s: not a commit history (notes, or a tag of a tree or blob), so not checked" % remote_ref)
            continue
        ref_problems, ref_notes = check_ref(remote, local_commit, remote_sha, stamped)
        problems += ["%s: %s" % (remote_ref, problem) for problem in ref_problems]
        notes += ["%s: %s" % (remote_ref, note) for note in ref_notes]
    if notes:
        print("review-slices: " + "\nreview-slices: ".join(notes), file=sys.stderr)
    if problems:
        print("review-slices refused the push:\n- " + "\n- ".join(problems) + "\n" + OVERRIDE, file=sys.stderr)
        return 1
    return 0


COMMANDS = {"status": cmd_status, "level": cmd_status, "check": cmd_check, "run-suite": cmd_run_suite,
            "pre-push": cmd_pre_push}


def main(argv):
    if argv[1:] == ["--version"]:
        print(VERSION)
        return 0
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(__doc__, file=sys.stderr)
        return 2
    command, args = argv[1], argv[2:]
    try:
        if command == "pre-push":
            data = sys.stdin.read()
            code = handoff(command, args, data)
            return cmd_pre_push(args, data) if code is None else code
        if command in ("status", "level"):
            code = handoff(command, args)
            if code is not None:
                return code
        return COMMANDS[command](args)
    except GuardError as error:
        print("review-slices: %s" % error, file=sys.stderr)
        if command == "pre-push":
            print(OVERRIDE, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
