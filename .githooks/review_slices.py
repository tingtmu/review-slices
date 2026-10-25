#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices guard (skill version 0.7.1): review levels, pass stamps and the pre-push check.

    review_slices.py status [BASE]         where this work stands: its review level and the trailer to write, the
                                           rules it is judged by, the pass stamp, the hook, and the next step
    review_slices.py level [BASE]          the same as status
    review_slices.py check                 lint REVIEW.md's review-slices block; exit 1 on an error
    review_slices.py run-suite             run every check in the suite; on a pass, stamp the tested tree
    review_slices.py pre-push REMOTE URL   git pre-push hook: refuse a push with no fitting trailer or stamp
    review_slices.py ci BASE HEAD          for a CI job: refuse when HEAD's new commits over BASE lack fitting trailers
    review_slices.py --version

Configuration is the first ```review-slices fenced block in REVIEW.md at the repo root:

    test: cd engine && uv run pytest     # one check of the suite; repeat the key per check, all are required
    base: main                           # the base branch (default: origin's default branch)
    default: simple                      # level of a path no glob matches (default: simple)
    critical: engine/src/*/approval.py   # "<level>: <glob>", one per line; "*" also matches "/"
    secrets: gitleaks                    # scan the commits a push adds (.githooks/secret_scan.py, gitleaks 8.19+)

A path takes its highest matching level; REVIEW.md, .githooks/* and .gitleaks* are at least important. A push is
judged by its new commits (neither the target ref nor the base branch has them), a merge only where it differs
from git's own merge. A trailer covers the new commits in its history no earlier trailer reaches, at their level
or higher. The standing rules (REVIEW.md where the branch left the base branch) judge a change, so it cannot lower
its own levels; a suite change is reported, not blocked. `status` says when an Important push is small enough for
one merged reviewer (MERGED_LINES, MERGED_FILES). `status`, `pre-push` and `ci` hand off to the base
branch's guard when this copy differs from it. Standard library only, Python 3.8+, git 2.32+.
"""
import collections
import datetime
import fnmatch
import functools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types

VERSION = "0.7.1"
LEVELS = ("trivial", "simple", "important", "critical")
FLOOR = (("REVIEW.md", "important"), (".githooks/*", "important"), (".gitleaks*", "important"))
GUARD_PATH = ".githooks/review_slices.py"
SCANNER_PATH = ".githooks/secret_scan.py"
HANDOFF = "REVIEW_SLICES_HANDOFF"
# The first guard version that has each command; the base branch's guard runs a command only if it has it.
SINCE = {"level": (0, 1, 0), "run-suite": (0, 1, 0), "pre-push": (0, 1, 0), "check": (0, 2, 0),
         "status": (0, 3, 0), "ci": (0, 4, 0)}
# The largest push one merged reviewer may take, in weighted lines (ceil(characters / LINE_WIDTH) per added or
# deleted line, so a minified line cannot pass as one) and files; chosen from calibrate.py's data (2026-10-25).
MERGED_LINES, MERGED_FILES, LINE_WIDTH = 40, 3, 100
MERGED = ("one merged reviewer (the adversarial, Standards and Spec lenses), or a Standards, a Spec and an "
          "adversarial reviewer")
PATCH_ARGS = ("--patch", "-U0", "--inter-hunk-context=0", "--no-renames", "--no-ext-diff", "--no-textconv",
              "--no-color", "--submodule=short", "--ignore-submodules=none", "--no-relative", "--src-prefix=a/",
              "--dst-prefix=b/")
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
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
    done = subprocess.run(("git",) + GIT_SETTINGS + args, capture_output=True, text=True, errors="surrogateescape")
    return done.stdout if done.returncode == 0 else None


def git(*args, check=True):
    """git's stripped stdout, or None if git failed (GuardError instead when CHECK). Paths that are not UTF-8 pass
    through as surrogate escapes, so they never crash a decode and go back to git unchanged."""
    done = subprocess.run(("git",) + GIT_SETTINGS + args, capture_output=True, text=True, errors="surrogateescape")
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


@functools.lru_cache(maxsize=None)
def git_version():
    return version_tuple(git("--version"))


def parse_config(text):
    """The first review-slices block of TEXT. Problems that leave the rules usable go to "errors" and "warnings"
    for `check`; only an unusable block raises GuardError."""
    match = re.search(r"^```review-slices[ \t]*\r?\n(.*?)^```", text, re.S | re.M)
    if not match:
        raise GuardError("REVIEW.md has no ```review-slices block")
    config = {"tests": [], "base": None, "default": "simple", "globs": [], "errors": [], "warnings": [],
              "secrets": None}
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
        elif key == "secrets":  # any value turns the scan on; `check` names one it does not know
            config["secrets"] = value
            config["errors"] += [] if value == "gitleaks" else ["line %d: secrets: takes gitleaks" % number]
        elif key == "base" or (key == "default" and value in LEVELS):
            if key in seen:
                config["errors"].append("line %d repeats %r; the last one counts" % (number, key))
            seen.add(key)
            config[key] = value
        else:
            raise GuardError("review-slices block line %d has an unknown key or level: %r" % (number, raw))
    return config


def unreadable_rules(reason, text=""):
    """Rules for a REVIEW.md that does not parse: every path is critical and a stamp is required, but nothing is
    refused outright, so the push that fixes the file can still go after a critical review. A `secrets:` line
    in its block (not a commented one) keeps the secret scan on."""
    block = re.search(r"^```review-slices[^\n]*\n(.*?)(?:^```|\Z)", text, re.S | re.M)
    secrets = bool(block and re.search(r"^[ \t]*secrets[ \t]*:", block.group(1), re.M))
    return {"tests": ["?"], "base": None, "default": "critical", "globs": [("critical", "*")], "errors": [reason],
            "warnings": [], "unreadable": reason, "secrets": "gitleaks" if secrets else None}


def read_config(root):
    """The working copy's rules."""
    path = os.path.join(root, "REVIEW.md")
    if not os.path.exists(path):
        raise GuardError("REVIEW.md not found at the repo root")
    with open(path, encoding="utf-8", errors="replace") as handle:
        return parse_config(handle.read())


def working_config(root):
    """The working copy's rules, or None if it has no REVIEW.md with a review-slices block."""
    path = os.path.join(root, "REVIEW.md")
    with open(path, encoding="utf-8", errors="replace") if os.path.exists(path) else open(os.devnull) as handle:
        text = handle.read()
    return parse_config(text) if re.search(r"^```review-slices", text, re.M) else None


def rules_text(commit):
    return git("show", "%s:REVIEW.md" % commit, check=False)


def rules_at(commit):
    """REVIEW.md's rules as committed at COMMIT: None if it has none (or a REVIEW.md with no review-slices block,
    which is some other document), every path critical if they do not parse."""
    text = rules_text(commit)
    if text is None or not re.search(r"^```review-slices", text, re.M):
        return None
    try:
        return parse_config(text + "\n")
    except GuardError as error:
        return unreadable_rules("REVIEW.md at %s does not parse (%s), so every path counts as critical; fix it "
                                "on the base branch" % (commit[:12], error), text)


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


def new_commits(head, trusted):
    """Commits HEAD has that no TRUSTED commit has, parents first. Only the target ref and the base branch are
    trusted: another branch someone pushed has not been through the base branch's rules."""
    return git("rev-list", "--reverse", "--topo-order", head, *(("--not",) + tuple(trusted) if trusted else ())).split()


@functools.lru_cache(maxsize=None)
def commit_paths(commit):
    """The paths COMMIT itself changed: against its parent, or for a merge, only where it differs from git's own
    merge of its parents (a conflict resolution, a dropped change, an edit made in the merge)."""
    parents = git("rev-list", "--parents", "-n", "1", commit).split()[1:]
    if not parents:
        return tuple(split_nul(git("diff-tree", "--root", "-r", "--no-commit-id", *DIFF_PATHS, commit)))
    if len(parents) == 1:
        return tuple(changed_paths(parents[0], commit))
    if len(parents) == 2 and git_version() >= (2, 36):
        return tuple(split_nul(git("show", "--remerge-diff", "--format=", *DIFF_PATHS, commit)))
    return tuple(merge_paths_by_side(commit, parents))


def merge_paths_by_side(commit, parents):
    """Merge paths without --remerge-diff (git before 2.36, octopus merges). A path only one parent changed must
    match that parent; a path several parents changed counts (its resolution needs a look); so does any path the
    merge differs from every parent on."""
    base = git("merge-base", "--octopus", *parents, check=False)
    if not base:
        return changed_paths(parents[0], commit)  # unrelated histories: all the merge brought in
    sides = [set(changed_paths(base, parent)) for parent in parents]
    counted, suspects = set(), set(split_nul(git("diff-tree", "--cc", "--no-commit-id", *DIFF_PATHS, commit)))
    for index, (parent, side) in enumerate(zip(parents, sides)):
        others = set().union(*(other for position, other in enumerate(sides) if position != index))
        alone = sorted(side - others)
        if alone:
            counted = counted | set(split_nul(git("--literal-pathspecs", "diff", *DIFF_PATHS, parent, commit, "--",
                                                  *alone)))
        suspects = suspects | (side & others)
    if len(parents) == 2:  # differing from every parent is what a clean merge of both sides' edits looks like too
        suspects = {path for path in suspects if not auto_merges_to(commit, base, parents, path)}
    return sorted(counted | suspects)


def auto_merges_to(commit, base, parents, path):
    """True if git's own three-way merge of PATH from BASE and the two PARENTS, clean, gives what COMMIT has."""
    blobs = [git_raw("show", "%s:%s" % (rev, path)) for rev in (parents[0], base, parents[1], commit)]
    if None in blobs:
        return False  # added or deleted on a side: look at it
    with tempfile.TemporaryDirectory() as tmp:
        names = [os.path.join(tmp, name) for name in ("ours", "base", "theirs")]
        for name, blob in zip(names, blobs):
            with open(name, "w", encoding="utf-8", errors="surrogateescape") as handle:
                handle.write(blob)
        done = subprocess.run(("git", "merge-file", "-p", "-q") + tuple(names), capture_output=True, text=True,
                              errors="surrogateescape")
    return done.returncode == 0 and done.stdout == blobs[3]


def base_tip():
    """(name, sha): the base branch's remote-tracking ref, as this clone last fetched it, and its commit (None if it
    does not resolve). The name comes from `review-slices.base`, which `install` records, else origin's default
    branch; never from the REVIEW.md being judged, which could point the judge at itself."""
    name = (git("config", "--get", "review-slices.base", check=False)
            or git("symbolic-ref", "--short", "--quiet", "refs/remotes/origin/HEAD", check=False) or "origin/main")
    return name, git("rev-parse", "--verify", "--quiet", "refs/remotes/%s^{commit}" % name, check=False)


def standing_commit(local_sha, tips):
    """The commit whose REVIEW.md judges LOCAL_SHA: where it left the first of TIPS (the base branch first) that it
    shares history with; None if it shares none."""
    for tip in tips:
        found = tip and git("merge-base", local_sha, tip, check=False)
        if found:
            return found
    return None


@functools.lru_cache(maxsize=None)
def trailer_level(commit):
    """The level of COMMIT's last `Review:` trailer (in the message's last paragraph), or None."""
    value = git("log", "-1", "--no-show-signature", "--format=%(trailers:key=Review,valueonly,unfold)", commit)
    words = value.splitlines()[-1].split() if value else []
    return words[0].lower() if words and words[0].lower() in LEVELS else None


def suite_change(old, new):
    """A note when NEW's suite differs from OLD's, or None."""
    if old is None or new is None or old["tests"] == new["tests"]:
        return None
    lines = ["  - " + test for test in old["tests"] if test not in new["tests"]]
    lines += ["  + " + test for test in new["tests"] if test not in old["tests"]]
    return "this change edits the suite; reviewers must confirm it is not weaker:\n" + "\n".join(lines or ["  (order)"])


def secret_scan(config, judge, head, tips):
    """(problems, notes) from the secret scan of the commits HEAD adds over TIPS, when the rules declare one. The
    scanner comes from where the judging guard does: JUDGE, or the base branch's last commit with a guard if it
    lost it; HEAD's own copy only where the base branch never had a guard."""
    if not config.get("secrets"):
        return [], []
    removed = judge and git("log", "-1", "--format=%H", "--diff-filter=D", judge, "--", GUARD_PATH, check=False)
    at = (judge if judge and git_raw("show", "%s:%s" % (judge, GUARD_PATH)) else removed and removed + "^") or head
    source = git_raw("show", "%s:%s" % (at, SCANNER_PATH))
    if not source:
        return ["the rules say `secrets:` but %s has no %s: %s" % (at[:12], SCANNER_PATH, "run the skill's "
                "setup_tools.py upgrade --apply and commit it" if at == head else "no push through the hook can add "
                "it to the base branch, so ask the user, whose override that is")], []
    scanner = types.ModuleType("secret_scan")
    try:
        exec(compile(source, SCANNER_PATH, "exec"), scanner.__dict__)
        return scanner.scan(git, at, head, tips)
    except Exception as error:  # a broken scanner refuses by name, not with a traceback
        return ["%s at %s did not run: %r" % (SCANNER_PATH, at[:12], error)], []


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
    if config["base"] and not base_resolves(config["base"]):
        errors.append("base: %s is neither a local branch nor a remote-tracking branch" % config["base"])
    if not config["tests"]:
        warnings.append("no test line, so pushes need no pass stamp")
    return errors, warnings


def hook_wiring():
    """How this clone's pre-push reaches the guard, or None if it does not. A config hook runs only for git 2.54+,
    so it is named as such: an older git pushing from this clone runs nothing."""
    bootstrap = os.path.join(git("rev-parse", "--path-format=absolute", "--git-common-dir"), "review-slices",
                             "bootstrap.py")
    if (git_version() >= (2, 54) and "review-slices" in (git("hook", "list", "pre-push", check=False) or "").split()
            and bootstrap in (git("config", "--get", "hook.review-slices.command", check=False) or "")):
        return "config hook review-slices (only git 2.54+ runs it)"
    hook = git("rev-parse", "--path-format=absolute", "--git-path", "hooks/pre-push")
    for path in (hook, hook + ".legacy"):
        if os.access(path, os.X_OK):
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            if bootstrap in text:
                return "hook file " + path
            if "review_slices.py" in text:
                return "hook file %s (0.1.0's: it runs the checkout's guard; run setup_tools.py install)" % path
    return None


def base_mismatch(config, tip_name):
    """A warning when the base branch the hook uses is not the one REVIEW.md names, or None."""
    if config is None or not config["base"] or tip_name.split("/", 1)[-1] == config["base"]:
        return None
    return ("the hook measures from %s, but REVIEW.md's base is %s; run setup_tools.py install, or fix REVIEW.md"
            % (tip_name, config["base"]))


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


def carried_stamp(config, tree, stamped, tries=10):
    """A stamped tree that TREE differs from only in paths an explicit `trivial:` glob matches, or None. Those are
    paths no check reads, so the suite's pass on that tree still holds; the default level says nothing about what
    checks read, so a path it covers never carries a stamp. Only the newest TRIES stamps are compared."""
    explicit = [(level, pattern) for level, pattern in config["globs"] if level == "trivial"]
    for other in list(stamped)[::-1][:tries]:
        differ = split_nul(git("diff-tree", "-r", *DIFF_PATHS, other, tree, check=False))
        rows = [Row(path, *path_level(config, path)) for path in differ]
        if rows and all(row.level == "trivial" and (row.level, row.pattern) in explicit for row in rows):
            return other
    return None


def write_stamp(tree, seconds, times=()):
    path = stamp_path()
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


def handoff(command, args, data=None, judge=None):
    """The exit code of the guard committed at JUDGE (the base branch), run instead of this copy, or None to run
    this copy. It runs when it differs from this file and has COMMAND, so an edited copy does not judge itself."""
    if os.environ.get(HANDOFF):
        return None
    judge = judge or base_tip()[1]
    source = judge and git_raw("show", "%s:%s" % (judge, GUARD_PATH))
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


def read_patch(*args):
    """git's patch output, read as bytes: Python's newline translation would split a line at a lone CR."""
    done = subprocess.run(("git",) + GIT_SETTINGS + args, capture_output=True)
    if done.returncode != 0:
        raise GuardError("git %s failed: %s" % (args[0], done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout.decode("utf-8", "surrogateescape")


def patch_size(text):
    """(weighted lines, files, binary) of a `--patch -U0` listing. Hunk lengths come from the hunk headers, so a
    deleted line that starts with `--` is never taken for a header."""
    lines, files, binary, old, new = 0, set(), False, 0, 0
    for line in text.split("\n"):
        if old > 0 or new > 0:
            if not line.startswith("\\"):  # "\ No newline at end of file"
                old, new = old - (not line.startswith("+")), new - (not line.startswith("-"))
                lines += max(1, -(-(len(line) - 1) // LINE_WIDTH)) if line.startswith(("+", "-")) else 0
        elif line.startswith("diff --git "):
            files.add(line)
        elif line.startswith("@@ "):
            match = HUNK.match(line)
            old, new = (int(count) if count is not None else 1 for count in match.groups()) if match else (0, 0)
        elif line.startswith("Binary files ") and line.endswith(" differ"):
            binary = True
    return lines, len(files), binary


def change_size(commits):
    """(weighted lines, files, binary) of COMMITS' own changes, per commit then summed; merges are left out."""
    if not commits:
        return 0, 0, False
    return patch_size(read_patch("log", "--no-walk=unsorted", "--no-merges", "--root", "--format=", *PATCH_ARGS,
                                 *commits))


def merged_lens(commits, uncommitted, tips):
    """(allowed, why): may one merged reviewer take this Important push? Measured over every commit the push adds,
    so several small units add up; never with uncommitted work, an unfetched base branch, a floor path (so no suite
    change), a merge with changes of its own, a submodule update or a binary file, whose size it cannot see."""
    if uncommitted:
        return False, "uncommitted work"
    if not base_tip()[1]:
        return False, "the base branch is not fetched"
    floor = [path for path in paths_of(commits) if any(fnmatch.fnmatchcase(path, glob) for glob, _level in FLOOR)]
    merges = git("rev-list", "--merges", "HEAD", *(("--not",) + tuple(tips) if tips else ())).split()
    if floor:
        return False, "%s is always at least important" % floor[0]
    for merge in merges:
        if commit_paths(merge):
            return False, "merge %s has changes of its own" % merge[:12]
    raw = git("log", "--no-walk=unsorted", "--no-merges", "--root", "--format=", "--raw", "--no-abbrev", *commits)
    if any("160000" in line[1:].split()[:2] for line in raw.splitlines() if line.startswith(":")):
        return False, "a submodule update"
    lines, files, binary = change_size(commits)
    if binary:
        return False, "a binary file"
    size = "%d weighted line(s), %d file(s) in %d new commit(s)" % (lines, files, len(commits))
    if lines > MERGED_LINES or files > MERGED_FILES:
        return False, "%s: over %d or %d" % (size, MERGED_LINES, MERGED_FILES)
    return True, size


def last_trailer(commits):
    """The last of COMMITS that carries a review trailer, or None."""
    return next((commit for commit in reversed(commits) if trailer_level(commit)), None)


def listed(paths, limit=5):
    return ", ".join(paths[:limit]) + (" and %d more" % (len(paths) - limit) if len(paths) > limit else "")


def next_step(config, level, start, commits, uncommitted, tips, merged=False):
    if uncommitted:
        edited = sorted(set(changed_paths("HEAD")))
        new = [path for path in uncommitted if path not in edited]
        return ("commit this work locally (no trailer yet), then run status again.%s%s Commit only what this work "
                "changed; if a file is not this work's, ask the user, and never commit, stash or revert someone "
                "else's edits. Files a tool wrote (build output, caches) belong in .gitignore: ask the user"
                % (" Edited: %s." % listed(edited) if edited else "", " New: %s." % listed(new) if new else ""))
    if level != "trivial":
        return ("review at %s: %s, on `git diff %s..HEAD`; then add the trailer to the last commit with "
                "`git -c trailer.ifexists=replace commit --amend --only --no-edit --trailer \"Review: %s %s\"`"
                % (level, MERGED if merged else SLICE2[level], start[:12], level, start[:12]))
    problems = review_problems(config, commits, tips)
    if problems:
        return "fix the trailers: " + problems[0]
    tree, stamped = git("rev-parse", "HEAD^{tree}"), stamps()
    if config["tests"] and commits and tree not in stamped and not carried_stamp(config, tree, stamped):
        return "run the suite: python3 %s run-suite" % GUARD_PATH
    return "ask the user's go-ahead, then push" if commits else "nothing to push"


def status_tips(args):
    """The commits a push from here would be measured against, as pre-push measures them: BASE if given, else the
    base branch and this branch's push target. An upstream that is someone else's branch is not trusted."""
    if args:
        return (git("rev-parse", "--verify", args[0] + "^{commit}"),)
    push = git("rev-parse", "--verify", "--quiet", "@{push}^{commit}", check=False)
    return tuple(tip for tip in (base_tip()[1], push) if tip)


def open_unit(commits, tips):
    """(start, paths): where the open review unit starts, and every path it and the working tree change: the new
    commits no trailer reaches, plus edits and new files."""
    _units, uncovered = review_units(commits, tips)
    last = last_trailer(commits)
    paths = set(changed_paths("HEAD")) | set(untracked_paths()) | set(paths_of(uncovered))
    first = git("rev-parse", "--verify", "--quiet", commits[0] + "^", check=False) if commits else None
    return last or first or git("rev-parse", "HEAD"), sorted(paths)


def cmd_status(args):
    """Where this work stands. The level covers the open review unit: new commits since the last trailer, plus
    the edits and new files a commit would carry."""
    root = git("rev-parse", "--show-toplevel")
    working = working_config(root)
    tips, tip_name = status_tips(args), base_tip()[0]
    standing = standing_commit("HEAD", tips)
    config = (standing and rules_at(standing)) or working
    if config is None:
        raise GuardError("no REVIEW.md with a review-slices block here or where this branch left %s; to set one "
                         "up, follow the skill's \"Set up a repo\"" % tip_name)
    commits = new_commits("HEAD", tips)
    start, paths = open_unit(commits, tips)
    level, rows = range_level(config, paths)
    print("level: %s" % level)
    for row in rows[:20]:
        print("  %s  (%s)" % (row.path, row.pattern))
    print("trailer: Review: %s %s" % (level, start[:12]))
    uncommitted = sorted(set(changed_paths("HEAD")) | set(untracked_paths()))
    merged = ((False, "a BASE was given, so the push is not measured whole") if args
              else merged_lens(commits, uncommitted, tips)) if level == "important" else None
    if merged:
        print("review: %s (%s)" % ("merged lens allowed: one reviewer for the adversarial, Standards and Spec lenses"
                                   if merged[0] else "three reviewers", merged[1]))
    print("new commits: %d not yet on %s or this branch's remote" % (len(commits), tip_name))
    print("standing rules: %s" % ("REVIEW.md at %s, where this branch left %s" % (standing[:12], tip_name)
                                  if standing and rules_at(standing) else "this branch's own REVIEW.md (%s not fetched "
                                  "or without one)" % tip_name))
    stamp = stamps().get(worktree_tree(root))
    print("pass stamp: %s" % ("yes, " + stamp if stamp is not None else "none for the working tree"))
    wiring = hook_wiring()
    print("hook: %s" % (wiring or "NOT WIRED: pushes from this clone are not checked; run the skill's "
                                  "setup_tools.py install"))
    print("guard: %s, %s" % (VERSION, "the base branch's copy" if os.environ.get(HANDOFF) else "this copy"))
    mismatch = base_mismatch(working, tip_name)
    if mismatch:
        print("note: " + mismatch)
    note = suite_change(config, working)
    if note:
        print("note: " + note)
    print_rule_messages(config, working, (standing or start)[:12])
    secret, notes = secret_scan(config, base_tip()[1], "HEAD", tips) if commits else ([], [])
    print("secrets: " + ("\n  ".join(secret + notes) or ("no new commits to scan" if config.get("secrets") else
                                                       "not scanned (REVIEW.md has no secrets: line)")))
    print("next: " + ("deal with the secret scan before review: " + secret[0].splitlines()[0] if secret else
                      next_step(config, level, start, commits, uncommitted, tips, bool(merged and merged[0]))))
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
    wiring = hook_wiring()
    if not wiring or "0.1.0" in wiring:
        print("warning: this clone's pre-push does not reach the bootstrap, so pushes are not checked by the base "
              "branch's guard; run the skill's setup_tools.py install", file=sys.stderr)
    mismatch = base_mismatch(config, base_tip()[0])
    if mismatch:
        print("warning: " + mismatch, file=sys.stderr)
    untracked = untracked_paths()
    if untracked:
        print("note: the stamp includes these untracked files; commit them all, or run again without them:\n  "
              + "\n  ".join(untracked[:10]), file=sys.stderr)
    before, started, times = worktree_tree(root), time.monotonic(), []
    for number, command in enumerate(config["tests"], 1):
        print("run-suite: [%d/%d] %s" % (number, len(config["tests"]), command), flush=True)
        began = time.monotonic()
        code = subprocess.run(command, shell=True, cwd=root).returncode
        times = times + [time.monotonic() - began]
        print("run-suite: [%d/%d] exit %d after %.0fs" % (number, len(config["tests"]), code, times[-1]), flush=True)
        if code != 0:
            print("run-suite: check %d failed; no stamp written" % number, file=sys.stderr)
            return code
    after = worktree_tree(root)
    if before != after:
        moved = split_nul(git("diff-tree", "-r", "-z", "--name-only", before, after))
        print("run-suite: these files changed during the run, so no stamp was written; ignore or fix them and run "
              "again:\n  " + "\n  ".join(moved[:10]), file=sys.stderr)
        return 1
    seconds = time.monotonic() - started
    write_stamp(before, seconds, times)
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


def review_units(commits, trusted):
    """(units, uncovered): for each new commit that carries a trailer, the new commits in its own history that no
    earlier trailered commit reaches; and the new commits no trailered commit reaches. Units follow history, not
    listing order, so a trailer on one branch never covers work on another."""
    trailered = [commit for commit in commits if trailer_level(commit)]
    covered, units = set(), []
    for commit in trailered:
        history = rev_list(commit, trusted)
        earlier = [other for other in history if other != commit and trailer_level(other)]
        units.append((commit, rev_list(commit, tuple(trusted) + tuple(earlier))))
        covered = covered | set(history)
    return units, [commit for commit in commits if commit not in covered]


def rev_list(head, excluded):
    return git("rev-list", head, *(("--not",) + tuple(excluded) if excluded else ())).split()


def paths_of(commits):
    return sorted(set(path for commit in commits for path in commit_paths(commit)))


def review_problems(config, commits, trusted):
    """Each trailer must cover the highest level of its review unit; new commits no trailer reaches must be
    trivial."""
    problems = []
    units, uncovered = review_units(commits, trusted)
    for commit, unit in units:
        declared = trailer_level(commit)
        level, rows = range_level(config, paths_of(unit))
        if rank(declared) < rank(level):
            problems.append("the trailer on %s says %s, but the commits it covers change %s-level paths, for "
                            "example %s (%s)" % (commit[:12], declared, level, rows[0].path, rows[0].pattern))
    level, rows = range_level(config, paths_of(uncovered))
    if level == "trivial":
        return problems
    if not units:
        problems.append("the new commits need a review at level %s (for example %s matches %s), and none carries "
                        "`Review: %s ...` or higher" % (level, rows[0].path, rows[0].pattern, level))
    else:
        problems.append("commits no review trailer covers (%s) change %s-level paths, for example %s; review them "
                        "and add a new trailer" % (", ".join(commit[:12] for commit in uncovered[:3]), level,
                                                  rows[0].path))
    return problems


def standing_rules(local_sha, tips):
    """(rules, problem, notes): the standing rules for pushing LOCAL_SHA, from where it left the first of TIPS it
    shares history with. A push may bring REVIEW.md (adoption) but never take it away."""
    standing = standing_commit(local_sha, tips)
    config = rules_at(standing) if standing else None
    if config is not None and rules_at(local_sha) is None:
        return None, ("this push deletes or moves REVIEW.md or its review-slices block; removing the rules is the "
                      "user's decision"), []
    if config is not None:
        return config, None, []
    config = rules_at(local_sha)
    if config is not None:
        return config, None, ["the review rules are new in this push, so they judge it"]
    deleted = git("log", "-1", "--format=%h", "--no-renames", "--diff-filter=D", local_sha, "--", "REVIEW.md",
                  check=False)
    if deleted:
        return None, None, ["REVIEW.md was deleted in %s, before this push, so the push is NOT checked; restoring it "
                            "is the user's decision" % deleted]
    return None, None, ["no REVIEW.md on this ref or where it left the base branch, so the push is not checked"]


def check_ref(local_sha, remote_sha, stamped):
    """(problems, notes) for pushing LOCAL_SHA over REMOTE_SHA; no problems means the push may go."""
    remote_commit = None
    if remote_sha.strip("0"):
        remote_commit = git("rev-parse", "--verify", "--quiet", remote_sha + "^{commit}", check=False)
        if not remote_commit:
            return ["the remote is at %s, which this clone does not have: fetch first" % remote_sha[:12]], []
    tips = tuple(tip for tip in (base_tip()[1], remote_commit) if tip)
    commits = new_commits(local_sha, tips)
    if not commits:
        return [], []
    config, problem, notes = standing_rules(local_sha, tips)
    if problem or config is None:
        return [problem] if problem else [], notes
    notes = notes + [note for note in (config.get("unreadable"), suite_change(config, rules_at(local_sha))) if note]
    problems, tree = [], git("rev-parse", local_sha + "^{tree}")
    carried = config["tests"] and tree not in stamped and carried_stamp(config, tree, stamped)
    if carried:
        notes = notes + ["the pass stamp of %s carries over: only trivial paths differ" % carried[:12]]
    elif config["tests"] and tree not in stamped:
        problems.append("no pass stamp for %s: run `python3 %s run-suite` on this commit (the full suite, once), "
                        "then push" % (local_sha[:12], GUARD_PATH))
    secret, secret_notes = secret_scan(config, base_tip()[1], local_sha, tips)
    return problems + review_problems(config, commits, tips) + secret, notes + secret_notes


def cmd_pre_push(args, data=""):
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
        ref_problems, ref_notes = check_ref(local_commit, remote_sha, stamped)
        problems += ["%s: %s" % (remote_ref, problem) for problem in ref_problems]
        notes += ["%s: %s" % (remote_ref, note) for note in ref_notes]
    if notes:
        print("review-slices: " + "\nreview-slices: ".join(notes), file=sys.stderr)
    if problems:
        print("review-slices refused the push:\n- " + "\n- ".join(problems) + "\n" + OVERRIDE, file=sys.stderr)
        return 1
    return 0


def cmd_ci(args):
    """Trailer coverage of HEAD's new commits over BASE, for a CI job; no stamp, since CI runs the suite itself."""
    if len(args) != 2:
        raise GuardError("usage: review_slices.py ci BASE HEAD")
    base, head = (git("rev-parse", "--verify", "%s^{commit}" % arg) for arg in args)
    commits = new_commits(head, (base,))
    config, problem, notes = standing_rules(head, (base,))
    if config is not None:
        notes = notes + [note for note in (config.get("unreadable"), suite_change(config, rules_at(head))) if note]
    problems = [problem] if problem else (review_problems(config, commits, (base,)) if config else [])
    if config is not None and commits:
        secret, secret_notes = secret_scan(config, base, head, (base,))
        problems, notes = problems + secret, notes + secret_notes
    for note in notes:
        print("note: " + note)
    if problems:
        print("review-slices ci: refused\n- " + "\n- ".join(problems))
        return 1
    print("review-slices ci: %d new commit(s) over %s, every one covered" % (len(commits), base[:12]))
    return 0


COMMANDS = {"status": cmd_status, "level": cmd_status, "check": cmd_check, "run-suite": cmd_run_suite,
            "pre-push": cmd_pre_push, "ci": cmd_ci}


def main(argv):
    sys.stdout.reconfigure(errors="backslashreplace")  # paths that are not UTF-8 print escaped, never crash
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
        if command in ("status", "level", "ci"):
            judge = git("rev-parse", "--verify", "--quiet", args[0] + "^{commit}", check=False) \
                if command == "ci" and args else None
            code = handoff(command, args, judge=judge)
            if code is not None:
                return code
        return COMMANDS[command](args)
    except (GuardError, OSError, UnicodeError) as error:
        print("review-slices: %s" % error, file=sys.stderr)
        if command == "pre-push":
            print(OVERRIDE, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
