#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices agent hook (skill version 0.10.0): a PreToolUse hook for Claude Code and Codex that stops an agent
from taking the user's overrides: skipping hooks with --no-verify, rewiring the push hook, writing pass stamps or
the bootstrap, or amending new content into a commit that carries a review trailer.

    agent_hook.py    read the hook's JSON payload on stdin; print a JSON "deny" to block, nothing to allow

It allows everything in a clone where the skill's `setup_tools.py install` never ran, and on any error, so a
missing or broken hook never blocks an agent. Shell commands are read the way a shell splits them; a command it
cannot read is checked with a few plain patterns instead. Standard library only, Python 3.8+.
"""
import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED_KEY = re.compile(r"^(hook\.review-slices(\..*)?|review-slices\..*|core\.hookspath)$", re.I)
SEPARATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", ";;"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>", ">&"}
# The operators shlex can run together into one token (`;(` is `;` then `(`), longest first.
OPERATORS = sorted(SEPARATORS | REDIRECTS | {"<", "<<", "<<<", "<&", "<>"}, key=len, reverse=True)
# Words a shell reads before the command they start (`if git ...`, `then git ...`, `{ git ...`).
KEYWORDS = {"!", "{", "}", "if", "then", "elif", "else", "fi", "do", "done", "while", "until"}
# Separators that start a new list of commands, and those after which the next command runs in the shell a `cd`
# just changed. Anywhere else (a pipeline, `||`, `&`) the next command may run where the shell was.
LIST_STARTS = {None, ";", ";;", "&", "(", ")"}
CD_FOLLOWS = {None, ";", ";;", "&&", ")"}
# Words before a `cd` that make it run only on some paths through the command.
BRANCHES = {"then", "else", "elif", "do"}
WRITERS = {"tee", "cp", "mv", "rm", "sed", "perl", "truncate", "touch", "ln", "dd", "install", "chmod", "python",
           "python3"}
# Commands that run another command, with their options that take a value, and how many plain arguments come
# before the command they run (timeout's duration).
WRAPPERS = {"command": (set(), 0), "exec": (set(), 0), "builtin": (set(), 0), "nohup": (set(), 0),
            "time": (set(), 0), "chronic": (set(), 0), "env": ({"-u", "--unset", "-C", "--chdir", "-S"}, 0),
            "sudo": ({"-u", "-g", "-C", "-D", "-h", "-p", "-U", "-r", "-t"}, 0),
            "nice": ({"-n", "--adjustment"}, 0), "ionice": ({"-c", "-n", "-p"}, 0),
            "stdbuf": ({"-i", "-o", "-e"}, 0), "timeout": ({"-s", "--signal", "-k", "--kill-after"}, 1),
            "xargs": ({"-n", "-I", "-L", "-P", "-d", "-s", "-E", "-e", "-a", "--max-args", "--replace",
                       "--max-lines", "--max-procs", "--delimiter", "--arg-file"}, 0)}
SHELLS = {"sh", "bash", "zsh", "dash"}
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"}
COMMIT_VALUE_OPTIONS = {"-m", "-F", "-C", "-c", "-t", "--message", "--file", "--reuse-message", "--reedit-message",
                        "--template", "--author", "--date", "--cleanup", "--trailer", "--fixup", "--squash",
                        "--pathspec-from-file"}
COMMIT_VALUE_SHORTS = "mFCct"
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l", "get", "list"}
CONFIG_WRITES = {"--unset", "--unset-all", "--add", "--replace-all", "--remove-section", "--rename-section", "-e",
                 "--edit", "set", "unset", "rename-section", "remove-section", "edit"}
SKIPS_HOOKS = re.compile(r"(^|\s)(--no-verify|-n)(\s|$)")
# A quoted word made only of operator characters (`-m ';)'`), which shlex hands back as if it were unquoted.
QUOTED_OPERATORS = re.compile(r"""(['"])[();<>|&]+\1""")
FALLBACK = (re.compile(r"\bgit\b[^\n;&|]*\b(push|commit)\b[^\n;&|]*--no-verify"),
            re.compile(r"(>|\btee\b|\brm\b|\bmv\b|\bcp\b)[^\n;&|]*review-slices/(suite-pass|bootstrap\.py)"))


def git(cwd, *args):
    try:
        done = subprocess.run(("git",) + args, capture_output=True, text=True, cwd=cwd)
    except OSError:  # CWD is missing or not a directory, so no repo is there
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def shell_lines(command):
    """COMMAND with unquoted newlines turned into ';' and heredoc bodies dropped, so each line is one command."""
    out, quote, index, heredocs = [], None, 0, []
    while index < len(command):
        char = command[index]
        if quote:
            if char == "\\" and quote == '"':
                out.append(command[index:index + 2])
                index += 2
                continue
            quote = None if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "\\":
            out.append(command[index:index + 2])
            index += 2
            continue
        elif command.startswith("<<", index) and not command.startswith("<<<", index):
            match = re.match(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", command[index:])
            if match:
                heredocs.append(match.group(2))
        elif char == "\n":
            out.append(";")
            index += 1
            for word in heredocs:
                end = re.search(r"^\t*%s$" % re.escape(word), command[index:], re.M)
                index = index + end.end() if end else len(command)
            heredocs = []
            continue
        out.append(char)
        index += 1
    return "".join(out)


def operators(token):
    """TOKEN as the shell operators shlex ran together into it, or [TOKEN] for a word."""
    if not token or token.strip("();<>|&"):
        return [token]  # a word; a quoted empty one too, which still takes its place as an argument
    found = []
    while token:
        found.append(next(operator for operator in OPERATORS if token.startswith(operator)))
        token = token[len(found[-1]):]
    return found


def segments(command):
    """COMMAND as its simple commands, each a list of words, with the separators between them as strings."""
    lexer = shlex.shlex(shell_lines(command.replace("\\\n", " ")), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    found, current = [], []
    for token in (operator for word in lexer for operator in operators(word)):
        if token in SEPARATORS:
            found, current = found + ([current] if current else []) + [token], []
        else:
            current = current + [token]
    return found + [current] if current else found


def command_words(tokens):
    """TOKENS without leading variable assignments, shell keywords and the wrappers that run the real command (env,
    sudo, timeout, xargs and the like), with their options."""
    index = 0
    while index < len(tokens):
        name = os.path.basename(tokens[index])
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]) or tokens[index] in KEYWORDS:
            index += 1
            continue
        if name not in WRAPPERS:
            break
        valued, positional = WRAPPERS[name]
        index += 1
        while index < len(tokens) and tokens[index].startswith("-") and tokens[index] != "-":
            index += 2 if tokens[index] in valued else 1
        index += positional
    return tokens[index:]


def git_parts(words):
    """(config settings as (key, value), -C directory, subcommand, args) of a git command line."""
    settings, where, index = [], None, 1
    while index < len(words) and words[index].startswith("-"):
        word = words[index]
        if word == "-c" and index + 1 < len(words):
            key, _sep, value = words[index + 1].partition("=")
            settings.append((key, value))
        elif word.startswith("--config-env="):
            settings.append((word.split("=", 2)[1], ""))
        elif word == "-C" and index + 1 < len(words):
            where = words[index + 1]
        index += 2 if word in GIT_VALUE_OPTIONS else 1
    return settings, where, (words[index] if index < len(words) else ""), words[index + 1:]


def commit_parts(args):
    """(flags, paths) of `git commit` ARGS, skipping option values."""
    flags, paths, index = set(), [], 0
    while index < len(args):
        word = args[index]
        if word == "--":
            return flags, paths + args[index + 1:]
        if word.startswith("--"):
            name = word.split("=", 1)[0]
            flags.add(name)
            index += 1 if name in COMMIT_VALUE_OPTIONS and "=" not in word else 0
        elif word.startswith("-") and len(word) > 1:
            for position, char in enumerate(word[1:]):
                flags.add("-" + char)
                if char in COMMIT_VALUE_SHORTS:
                    index += 1 if position == len(word) - 2 else 0
                    break
        else:
            paths.append(word)
        index += 1
    return flags, paths


def moved(places, target):
    """PLACES after changing directory to TARGET, with None for a place that cannot be worked out. A `..` after a
    symlink leads to two places, as a shell's `cd` reads it and as `git -C` or `cd -P` does."""
    target = os.path.expanduser(target)
    if target.startswith("~") or re.search(r"[$`*?[]", target):
        return {None}
    joined = [os.path.join(place or "", target) if place or os.path.isabs(target) else None for place in places]
    return ({os.path.normpath(path) for path in joined if path} | {os.path.realpath(path) for path in joined if path}
            | ({None} if None in joined else set()))


def cd_places(words, places):
    """Where the `cd` (or `pushd`, `popd`) in WORDS leaves the shell from any of PLACES; None if WORDS is no cd."""
    words = command_words(words)
    if not words or words[0] not in ("cd", "pushd", "popd"):
        return None
    args = [word for word in words[1:] if word != "--" and not re.match(r"-[LPe@]+$", word)]
    if words[0] == "popd" or (words[0] == "pushd" and not args) or args[:1] and args[0][:1] in ("-", "+"):
        return {None}  # the directory stack or $OLDPWD
    return moved(places, args[0] if args else "~")


def amend_reason(flags, paths, place):
    """On a commit that carries a review trailer, only a message amend (`--only` with no paths) is allowed: the same
    command line may stage new content first (`git add -A && git commit --amend`), so the index proves nothing.
    PLACE is the directory the amend runs in, None when a `cd` before it cannot be worked out."""
    if "--amend" not in flags or (flags & {"-o", "--only"} and not paths
                                  and not flags & {"-a", "--all", "-i", "--include"}):
        return None
    if place is None:
        return ("this amend runs in a directory the hook cannot work out (a `cd` to a variable, `-` or a command's "
                "output), so it could put new content under a review trailer; name the directory, or use `git -C`")
    trailer = git(place, "log", "-1", "--no-show-signature", "--format=%(trailers:key=Review,valueonly)", "HEAD")
    if trailer:
        return ("this amend could put new content under a review trailer that covers other content; add a new "
                "commit, or amend only the message with `git commit --amend --only`")
    return None


def setting_reason(key, value):
    """Why setting KEY to VALUE takes an override, or None: it rewires the hook, or makes an alias that skips hooks."""
    if PROTECTED_KEY.match(key):
        return "`%s` rewires the review-slices push hook" % key
    if key.lower().startswith("alias.") and SKIPS_HOOKS.search(value):
        return "the alias `%s` skips hooks" % key
    return None


def config_reason(args):
    """Why `git config ARGS` takes an override, or None for a read."""
    if set(args) & CONFIG_READS:
        return None
    plain = [arg for arg in args if not arg.startswith("-")]
    if plain and plain[0] in CONFIG_WRITES:
        plain = plain[1:]
    elif not set(args) & CONFIG_WRITES and len(plain) < 2:
        return None  # `git config <key>` prints the value
    key, value = (plain + ["", ""])[:2]
    return setting_reason(key, " ".join(plain[1:])) if key else None


def git_reason(words, places):
    settings, where, sub, args = git_parts(words)
    reasons = [setting_reason(key, value) for key, value in settings]
    if any(reasons):
        return next(reason for reason in reasons if reason)
    places = moved(places, where) if where else places
    if sub == "push" and "--no-verify" in args:
        return "`git push --no-verify` skips the review-slices guard"
    if sub == "commit":
        flags, paths = commit_parts(args)
        if flags & {"--no-verify", "-n"}:
            return "`git commit --no-verify` skips the repo's commit hooks"
        return next((reason for reason in (amend_reason(flags, paths, place) for place in sorted(places, key=str))
                     if reason), None)
    if sub == "config":
        return config_reason(args)
    return None


def protected(target, guarded, cwd):
    """Whether writing TARGET from CWD writes what the guard keeps; CWD None after a `cd` the hook cannot work out,
    where a relative TARGET is judged by the guarded layout's names (`review-slices` in a git dir, `hooks/pre-push`,
    or a bare stamp, bootstrap or hook name)."""
    if "review-slices/suite-pass" in target or "review-slices/bootstrap.py" in target:
        return True
    full = os.path.normpath(os.path.join(cwd or "", os.path.expanduser(target)))
    if cwd is None and not os.path.isabs(full):
        names = full.split(os.sep)
        in_git_dir = names[0] == "review-slices" or any(
            outer.endswith(".git") and inner == "review-slices" for outer, inner in zip(names, names[1:]))
        return (in_git_dir or names[-2:] == ["hooks", "pre-push"]
                or names in (["pre-push"], ["suite-pass"], ["bootstrap.py"], ["review-log"]))
    return any(full == path or full.startswith(path + os.sep) or full.startswith(path + ".") for path in guarded)


def words_reason(words, guarded, places):
    words = command_words(words)
    if not words:
        return None
    name = os.path.basename(words[0])
    if name in SHELLS and len(words) > 2 and words[1] in ("-c", "-lc", "-ic"):
        return command_reason(words[2], guarded, places)
    if name == "git":
        return git_reason(words, places)
    writes = name in WRITERS and (name != "sed" or any(word.startswith(("-i", "--in-place")) for word in words))
    targets = [words[index + 1] for index in range(len(words) - 1) if words[index] in REDIRECTS]
    targets += words[1:] if writes else []
    if any(protected(target, guarded, place) for target in targets for place in places):
        return "this writes the review-slices pass stamps, bootstrap or push hook"
    return None


def settled(item, before, then, after, nested):
    """Whether the command after the `cd` ITEM surely runs where it moved to (AFTER): the `cd` runs whenever the
    command list does, outside any branch, the next command runs in the same shell after it, and the directory is
    there (a failed `cd` leaves the shell where it was, and `;` or `||` goes on from there)."""
    branch = item[0] in BRANCHES or (before == ")" and not nested)  # `then cd`, or a `case` pattern's `x)`
    ran = before in LIST_STARTS or (before == "&&" and then == "&&")
    done = then in CD_FOLLOWS and all(place and os.path.isdir(place) for place in after)
    return ran and done and not branch


def command_reason(command, guarded, places):
    """Why COMMAND, started in any of PLACES, takes an override, or None. A quoted word of operator characters may be
    an argument or a separator to shlex, so a command with one is judged both ways."""
    plain = QUOTED_OPERATORS.sub("x", command)
    return list_reason(command, guarded, places) or (
        list_reason(plain, guarded, places) if plain != command else None)


def list_reason(command, guarded, places):
    """command_reason for one reading of COMMAND. A `cd` moves the commands after it; where the shell may or may not
    have moved, they are judged in both places, and a subshell's `cd` ends with it."""
    try:
        found = segments(command)
    except ValueError:
        return "this command matches an override pattern" if any(p.search(command) for p in FALLBACK) else None
    saved, start, loose = [], places, False  # START: where this list began; LOOSE: a `cd` in it may be skipped
    for index, item in enumerate(found):
        if item == "(":
            saved.append((places, start, loose))
            start, loose = places, False
        elif item == ")":
            places, start, loose = saved.pop() if saved else (places, start, loose)
        elif item in (";", ";;", "&"):
            places = places | start if loose else places
            start, loose = places, False
        elif item == "||" and loose:  # what follows runs when a command before the `cd` failed, too
            places = places | start
        elif not isinstance(item, str):
            after = cd_places(item, places)
            if after is None:
                reason = words_reason(item, guarded, places)
                if reason:
                    return reason
                continue
            before, then = found[index - 1] if index else None, (found[index + 1:] or [None])[0]
            if settled(item, before, then, after, saved):
                places, loose = after, loose or before == "&&"
            else:
                places = places | after
    return None


def guarded_paths(common, cwd):
    hooks = git(cwd, "rev-parse", "--path-format=absolute", "--git-path", "hooks") or os.path.join(common, "hooks")
    return [os.path.join(common, "review-slices"), os.path.join(hooks, "pre-push")]


def reason_for(payload):
    """Why the tool call in PAYLOAD takes an override, or None. The repo is the one the settings command found
    (REVIEW_SLICES_TOP), not the agent's current directory, which may be anywhere."""
    cwd = payload.get("cwd") or os.getcwd()
    top = os.environ.get("REVIEW_SLICES_TOP") or cwd
    common = git(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common or not os.path.exists(os.path.join(common, "review-slices", "bootstrap.py")):
        return None  # this clone never opted in
    guarded = guarded_paths(common, top)
    data = payload.get("tool_input") or {}
    path = data.get("file_path") or data.get("notebook_path")
    if path:
        return "this edits the review-slices pass stamps, bootstrap or push hook" if protected(path, guarded,
                                                                                              cwd) else None
    command = data.get("command")
    if isinstance(command, list):
        command = command[2] if len(command) > 2 and command[1] in ("-c", "-lc") else " ".join(map(shlex.quote,
                                                                                                    command))
    return command_reason(command, guarded, {cwd}) if isinstance(command, str) else None


def main():
    try:
        reason = reason_for(json.load(sys.stdin))
    except Exception as error:  # never block an agent because this hook broke, but say so
        print("review-slices agent hook: %s: %s; the action is allowed" % (type(error).__name__, error),
              file=sys.stderr)
        return 0
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "review-slices: %s. That is the user's override, never an agent's: ask the "
                                        "user." % reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
