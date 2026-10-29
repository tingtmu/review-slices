#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices guard (skill version 0.9.4): review levels, pass stamps and the pre-push check.

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
    critical code: engine/src/*          # critical code a small diff can be judged from (others are content)
    small: 40 lines, 3 files             # size bands of the review load, up to 80/5 and 400/20; or off
    medium: 200 lines, 10 files

A path takes its highest matching level; REVIEW.md, .githooks/* and .gitleaks* are at least important. A push is
judged by its new commits (neither the target ref nor the base branch has them), a merge only where it differs from
git's own merge. A trailer covers the new commits in its history no earlier trailer reaches, at their level or
higher. The standing rules (REVIEW.md where the branch left the base branch) judge a change, so it cannot lower its
own levels; a suite change is reported, not blocked. `status` names the review load of an Important or Critical
change (.githooks/merged_reviewer.py), held per review unit in <git-common-dir>/review-slices/review-log. `status`,
`pre-push` and `ci` hand off to the base branch's guard when this copy differs from it; `run-suite` runs the
.githooks/run_suite.py beside this copy. Standard library only, Python 3.8+, git 2.32+.
"""
import collections
import fnmatch
import functools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

VERSION = "0.9.4"
LEVELS = ("trivial", "simple", "important", "critical")
FLOOR = (("REVIEW.md", "important"), (".githooks/*", "important"), (".gitleaks*", "important"))
GUARD_PATH = ".githooks/review_slices.py"
SCANNER_PATH = ".githooks/secret_scan.py"
MERGED_PATH = ".githooks/merged_reviewer.py"
SUITE_PATH = ".githooks/run_suite.py"
HANDOFF = "REVIEW_SLICES_HANDOFF"
# The first guard version that has each command; the base branch's guard runs a command only if it has it.
SINCE = {"level": (0, 1, 0), "run-suite": (0, 1, 0), "pre-push": (0, 1, 0), "check": (0, 2, 0),
         "status": (0, 3, 0), "ci": (0, 4, 0)}
# What `next:` says a first round takes: the separate reviewers, then who may lower it (issue #26). A reduced load is
# the least, never "enough": step 3, 5 or 6 may still raise it.
THREE = ("3 separate reviewers (Standards, Spec, adversarial), each its own fresh agent",
         "fewer, or lenses combined into fewer reviewers, only with the user's go-ahead asked first, or step 4's "
         "exceptions (size was already counted)")
LEAST = "the least: more where step 3 raises the level, step 5 escalates, or step 6 after a rebase; "
SLICE2 = {"simple": ("1-2 adversarial reviewers, each its own fresh agent", "the least: more where step 3 raises "
                     "the level; none only with the user's go-ahead asked first"),
          "important": THREE, "critical": THREE}
# The reduced review loads `status` may print, and the most a REVIEW.md size band may say (lines, files).
LOADS = {"one merged reviewer": ("1 merged reviewer (the adversarial, Standards and Spec lenses), its own fresh agent",
                                 LEAST + "none only with the user's go-ahead asked first"),
         "adversarial + conformance": ("2 separate reviewers (adversarial; conformance: the Standards and Spec "
                                       "lenses), each its own fresh agent", LEAST + "fewer, or the two combined into "
                                       "one, only with the user's go-ahead asked first, or step 4's exceptions")}
CEILINGS = {"small": (80, 5), "medium": (400, 20)}
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
              "secrets": None, "small": None, "medium": None}
    seen, kinds = set(), {"code": set(), "content": set()}
    for number, raw in enumerate(match.group(1).splitlines(), 1):
        line = COMMENT.sub("", raw).strip()
        if not line:
            continue
        key, sep, value = (part.strip() for part in line.partition(":"))
        if not sep or not value:
            raise GuardError("review-slices block line %d is not 'key: value': %r" % (number, raw))
        if PLACEHOLDER.search(value):
            config["errors"].append("line %d still holds a template placeholder: %s" % (number, line))
        level, kind = (key.split(None, 1) + ["", ""])[:2]
        if level in LEVELS:  # a mistyped kind ("critical cdoe:") still counts at its level, as content
            if kind and (level, kind) != ("critical", "code"):
                config["errors"].append("line %d: %r is not a key; its globs count at %s" % (number, key, level))
            globs = [glob.strip() for glob in value.split(",") if glob.strip()]
            if len(globs) > 1:
                config["warnings"].append("line %d is read as %d globs; write one glob per line" % (number, len(globs)))
            config["globs"] += [(level, glob) for glob in globs]
            kinds["code" if kind == "code" else "content"].update(globs if level == "critical" else ())
        elif key in CEILINGS:  # a size band: a repeat reads as the stricter one, a value it cannot read as off
            limit = re.fullmatch(r"(\d{1,6}) lines?, (\d{1,6}) files?", value)  # int() refuses 4300+ digits
            wanted = (int(limit.group(1)), int(limit.group(2))) if limit else "off"
            band = tuple(map(min, wanted, CEILINGS[key])) if limit else "off"
            config["errors"] += [] if limit or value == "off" else ["line %d: %s: takes off or 'N lines, M files'; "
                                                                    "read as off" % (number, key)]
            config["warnings"] += [] if band == wanted else ["line %d: %s: is over the most it may say, so it reads "
                                                             "as %d lines, %d files" % ((number, key) + band)]
            old = config[key] or band
            config[key] = "off" if "off" in (old, band) else (min(old[0], band[0]), min(old[1], band[1]))
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
    config["code"] = kinds["code"] - kinds["content"]  # a glob also listed as content is content
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


def vendored(judge, head, path):
    """(at, source): PATH as committed where the judging guard comes from: JUDGE, or the base branch's last commit
    with a guard if it lost it; HEAD's own copy only where the base branch never had a guard. SOURCE is None if
    PATH is not there."""
    removed = judge and git("log", "-1", "--format=%H", "--diff-filter=D", judge, "--", GUARD_PATH, check=False)
    at = (judge if judge and git_raw("show", "%s:%s" % (judge, GUARD_PATH)) else removed and removed + "^") or head
    return at, git_raw("show", "%s:%s" % (at, path))


def secret_scan(config, judge, head, tips):
    """(problems, notes) from the secret scan of the commits HEAD adds over TIPS, when the rules declare one."""
    if not config.get("secrets"):
        return [], []
    at, source = vendored(judge, head, SCANNER_PATH)
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
        return subprocess.run((sys.executable, "-I", "-S", path, command) + tuple(args), input=data, text=True,
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


def review_load(rules, level, rows, uncommitted, start):
    """(load, why) from .githooks/merged_reviewer.py, loaded as the secret scanner is, over every commit this
    branch adds to the base branch (its load() may start after a unit large on its own), with the bands and kinds
    of the standing RULES only (None: the defaults), so a change cannot lighten its own review; its hold() then
    keeps the unit at the highest load printed since START (the review log). Without the measure, or if it fails,
    three reviewers; a 0.8.0 measure has no load(), so it judges Important pushes only."""
    tip = base_tip()[1]
    if not tip:  # vendored() would fall back to this branch's own copy
        return "three reviewers", "the base branch is not fetched"
    at, source = vendored(tip, "HEAD", MERGED_PATH)
    if at == "HEAD":  # the base branch never had a guard: nothing it trusts measures this push
        return "three reviewers", "the base branch has no guard yet"
    if not source:
        return "three reviewers", "%s has no %s: run the skill's setup_tools.py upgrade" % (at[:12], MERGED_PATH)
    module, guard, commits = types.ModuleType("merged_reviewer"), types.SimpleNamespace(**globals()), new_commits(
        "HEAD", (tip,))  # the whole branch, so slices are measured whole; load() may start after a large unit
    try:
        exec(compile(source, MERGED_PATH, "exec"), module.__dict__)
        if hasattr(module, "load"):
            found = module.load(guard, rules, level, rows, commits, uncommitted, (tip,))
            return module.hold(guard, start, level, found) if hasattr(module, "hold") and not uncommitted else found
        allowed, why = module.allowed(guard, commits, uncommitted, (tip,)) if level == "important" and not (
            rules or {}).get("small") else (False, "%s at %s has no load(): it measures Important changes, under "
                                                   "no small: line, only" % (MERGED_PATH, at[:12]))
        return "one merged reviewer" if allowed else "three reviewers", why
    except Exception as error:  # a broken measure means three reviewers, not a traceback
        return "three reviewers", "%s at %s did not run: %r" % (MERGED_PATH, at[:12], error)


def last_trailer(commits):
    """The last of COMMITS that carries a review trailer, or None."""
    return next((commit for commit in reversed(commits) if trailer_level(commit)), None)


def listed(paths, limit=5):
    return ", ".join(paths[:limit]) + (" and %d more" % (len(paths) - limit) if len(paths) > limit else "")


def next_step(config, level, start, commits, uncommitted, tips, load=None):
    if uncommitted:
        edited = sorted(set(changed_paths("HEAD")))
        new = [path for path in uncommitted if path not in edited]
        return ("commit this work locally (no trailer yet), then run status again.%s%s Commit only what this work "
                "changed; if a file is not this work's, ask the user, and never commit, stash or revert someone "
                "else's edits. Files a tool wrote (build output, caches) belong in .gitignore: ask the user"
                % (" Edited: %s." % listed(edited) if edited else "", " New: %s." % listed(new) if new else ""))
    if level != "trivial":
        reviewers, fewer = LOADS.get(load, SLICE2[level])
        return ("review at %s, first round on the whole unit: %s, on `git diff %s..HEAD`%s; %s; before starting "
                "them, write in your message `load: <%s>; starting: <each reviewer, its lenses>`; a second round as "
                "step 6 says; once they have reported, add the trailer to the last commit with "
                "`git -c trailer.ifexists=replace commit --amend --only --no-edit --trailer \"Review: %s %s\"`"
                % (level, reviewers, start[:12], ", then the user's go-ahead for the one-way door"
                   if level == "critical" else "", fewer, "the review: line" if load else "this load", level,
                   start[:12]))
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
    rules = standing and rules_at(standing)
    config = rules or working
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
    load = (("three reviewers", "a BASE was given, so the branch is not measured whole") if args else review_load(
        rules, level, rows, uncommitted, start)) if level in ("important", "critical") else None
    if load:
        print("review: %s (%s)" % load)
    print("new commits: %d not yet on %s or this branch's remote" % (len(commits), tip_name))
    print("standing rules: %s" % ("REVIEW.md at %s, where this branch left %s" % (standing[:12], tip_name)
                                  if rules else "this branch's own REVIEW.md (%s not fetched or without one)"
                                  % tip_name))
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
                      next_step(config, level, start, commits, uncommitted, tips, load and load[0])))
    return 0


def cmd_check(_args):
    root = git("rev-parse", "--show-toplevel")
    errors, _warnings = print_lint(read_config(root), "REVIEW.md")
    print("check: %s" % ("%d error(s)" % len(errors) if errors else "ok"))
    return 1 if errors else 0


def cmd_run_suite(args):
    """Run the suite and stamp a pass with .githooks/run_suite.py from beside this copy; it never hands off."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.path.basename(SUITE_PATH))
    module = types.ModuleType("run_suite")
    try:
        with open(path, encoding="utf-8") as handle:
            exec(compile(handle.read(), path, "exec"), module.__dict__)
        run = module.run
    except Exception as error:  # a missing or broken suite wrapper is named, not a traceback
        raise GuardError("%s did not load (%r): run the skill's setup_tools.py upgrade --apply" % (path, error))
    return run(types.SimpleNamespace(**globals()), args)


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
