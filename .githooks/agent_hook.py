#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices agent hook (skill version 0.8.0): a PreToolUse hook for Claude Code and Codex that stops an agent
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
REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
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
FALLBACK = (re.compile(r"\bgit\b[^\n;&|]*\b(push|commit)\b[^\n;&|]*--no-verify"),
            re.compile(r"(>|\btee\b|\brm\b|\bmv\b|\bcp\b)[^\n;&|]*review-slices/(suite-pass|bootstrap\.py)"))


def git(cwd, *args):
    done = subprocess.run(("git",) + args, capture_output=True, text=True, cwd=cwd)
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


def segments(command):
    """The simple commands in COMMAND, each a list of words."""
    lexer = shlex.shlex(shell_lines(command.replace("\\\n", " ")), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    found, current = [], []
    for token in lexer:
        if token in SEPARATORS:
            found, current = found + [current] if current else found, []
        else:
            current = current + [token]
    return found + [current] if current else found


def command_words(tokens):
    """TOKENS without leading variable assignments and the wrappers that run the real command (env, sudo, timeout,
    xargs and the like), with their options."""
    index = 0
    while index < len(tokens):
        name = os.path.basename(tokens[index])
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]):
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


def amend_reason(flags, paths, cwd):
    """On a commit that carries a review trailer, only a message amend (`--only` with no paths) is allowed: the same
    command line may stage new content first (`git add -A && git commit --amend`), so the index proves nothing."""
    if "--amend" not in flags:
        return None
    message_only = flags & {"-o", "--only"} and not paths and not flags & {"-a", "--all", "-i", "--include"}
    trailer = git(cwd, "log", "-1", "--no-show-signature", "--format=%(trailers:key=Review,valueonly)", "HEAD")
    if trailer and not message_only:
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


def git_reason(words, cwd):
    settings, where, sub, args = git_parts(words)
    reasons = [setting_reason(key, value) for key, value in settings]
    if any(reasons):
        return next(reason for reason in reasons if reason)
    cwd = os.path.join(cwd, where) if where else cwd
    if sub == "push" and "--no-verify" in args:
        return "`git push --no-verify` skips the review-slices guard"
    if sub == "commit":
        flags, paths = commit_parts(args)
        if flags & {"--no-verify", "-n"}:
            return "`git commit --no-verify` skips the repo's commit hooks"
        return amend_reason(flags, paths, cwd)
    if sub == "config":
        return config_reason(args)
    return None


def protected(target, guarded, cwd):
    if "review-slices/suite-pass" in target or "review-slices/bootstrap.py" in target:
        return True
    full = os.path.normpath(os.path.join(cwd, os.path.expanduser(target)))
    return any(full == path or full.startswith(path + os.sep) or full.startswith(path + ".") for path in guarded)


def words_reason(words, guarded, cwd):
    words = command_words(words)
    if not words:
        return None
    name = os.path.basename(words[0])
    if name in SHELLS and len(words) > 2 and words[1] in ("-c", "-lc", "-ic"):
        return command_reason(words[2], guarded, cwd)
    if name == "git":
        return git_reason(words, cwd)
    writes = name in WRITERS and (name != "sed" or any(word.startswith(("-i", "--in-place")) for word in words))
    targets = [words[index + 1] for index in range(len(words) - 1) if words[index] in REDIRECTS]
    targets += words[1:] if writes else []
    if any(protected(target, guarded, cwd) for target in targets):
        return "this writes the review-slices pass stamps, bootstrap or push hook"
    return None


def command_reason(command, guarded, cwd):
    try:
        found = segments(command)
    except ValueError:
        return "this command matches an override pattern" if any(p.search(command) for p in FALLBACK) else None
    return next((reason for reason in (words_reason(words, guarded, cwd) for words in found) if reason), None)


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
    return command_reason(command, guarded, cwd) if isinstance(command, str) else None


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
