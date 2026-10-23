#!/usr/bin/env python3
"""review-slices agent hook (skill version 0.4.0): a PreToolUse hook for Claude Code and Codex that stops an agent
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
PREFIXES = {"command", "exec", "env", "sudo", "nohup", "time", "builtin", "xargs"}
SHELLS = {"sh", "bash", "zsh", "dash"}
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"}
COMMIT_VALUE_OPTIONS = {"-m", "-F", "-C", "-c", "-t", "--message", "--file", "--reuse-message", "--reedit-message",
                        "--template", "--author", "--date", "--cleanup", "--trailer", "--fixup", "--squash",
                        "--pathspec-from-file"}
COMMIT_VALUE_SHORTS = "mFCct"
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l", "get", "list"}
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
    """TOKENS without leading variable assignments and wrappers such as env or sudo."""
    index = 0
    while index < len(tokens) and (tokens[index] in PREFIXES or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index])
                                   or (index and tokens[index - 1] in PREFIXES and tokens[index].startswith("-"))):
        index += 1
    return tokens[index:]


def git_parts(words):
    """(config keys, -C directory, subcommand, args) of a git command line."""
    keys, where, index = [], None, 1
    while index < len(words) and words[index].startswith("-"):
        word = words[index]
        if word == "-c" and index + 1 < len(words):
            keys.append(words[index + 1].split("=", 1)[0])
        elif word.startswith("--config-env="):
            keys.append(word.split("=", 2)[1])
        elif word == "-C" and index + 1 < len(words):
            where = words[index + 1]
        index += 2 if word in GIT_VALUE_OPTIONS else 1
    return keys, where, (words[index] if index < len(words) else ""), words[index + 1:]


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
    if "--amend" not in flags:
        return None
    staged = subprocess.run(("git", "diff", "--cached", "--quiet"), cwd=cwd, capture_output=True).returncode == 1
    content = flags & {"-a", "--all", "-i", "--include"} or paths or (staged and not flags & {"-o", "--only"})
    trailer = git(cwd, "log", "-1", "--no-show-signature", "--format=%(trailers:key=Review,valueonly)", "HEAD")
    if content and trailer:
        return "this amends new content into a commit whose review trailer covers other content; add a new commit"
    return None


def git_reason(words, cwd):
    keys, where, sub, args = git_parts(words)
    if any(PROTECTED_KEY.match(key) for key in keys):
        return "`-c %s` rewires the review-slices push hook" % next(key for key in keys if PROTECTED_KEY.match(key))
    cwd = os.path.join(cwd, where) if where else cwd
    if sub == "push" and "--no-verify" in args:
        return "`git push --no-verify` skips the review-slices guard"
    if sub == "commit":
        flags, paths = commit_parts(args)
        if flags & {"--no-verify", "-n"}:
            return "`git commit --no-verify` skips the repo's commit hooks"
        return amend_reason(flags, paths, cwd)
    if sub == "config" and not set(args) & CONFIG_READS:
        touched = [arg for arg in args if PROTECTED_KEY.match(arg)]
        if touched:
            return "`git config %s` rewires the review-slices push hook" % touched[0]
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
    targets = [words[index + 1] for index in range(len(words) - 1) if words[index] in REDIRECTS]
    targets += words[1:] if name in WRITERS else []
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
    cwd = payload.get("cwd") or os.getcwd()
    common = git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common or not os.path.exists(os.path.join(common, "review-slices", "bootstrap.py")):
        return None  # this clone never opted in
    guarded = guarded_paths(common, cwd)
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
    except Exception:  # never block an agent because this hook broke
        return 0
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "review-slices: %s. That is the user's override, never an agent's: ask the "
                                        "user." % reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
