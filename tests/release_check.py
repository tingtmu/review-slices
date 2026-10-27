"""REVIEW.md's version-swap check: does a release change nothing outside its notes but the version?

Run it as the base commit holds it, so a branch cannot edit the check that judges it:

    git show <base>:tests/release_check.py | python3 -I - --base <base> [--head HEAD]

OLD is the base guard's VERSION and NEW the head guard's; NEW must be higher. The notes are the root README.md and
CHANGELOG.md, matched by exact path; each may change or be added, as a plain file (mode 100644). Every other file the
release changes must be its base copy with only `VERSION = "OLD"` lines and `(skill version OLD)` swapped for NEW,
byte for byte; every other entry `git diff --raw` lists must be `M` with no mode change (`--name-status --summary`
prints no mode change line); and no file outside the notes may still hold either OLD form. Prints each problem and
exits 1, or prints one OK line and exits 0. Exit 2: git failed or an argument is wrong.
"""
import argparse
import os
import re
import subprocess
import sys

GUARD = "skills/review-slices/scripts/review_slices.py"
VERSION_LINE = re.compile(rb'^VERSION = "([^"\n]*)"$', re.M)
NOTES = ("README.md", "CHANGELOG.md")  # matched by exact path: a pathspec would also exclude a NOTES/ directory


def fail(message):
    print("release check: %s" % message, file=sys.stderr)
    sys.exit(2)


def git(*args, ok=(0,)):
    done = subprocess.run(("git",) + args, capture_output=True)
    if done.returncode not in ok:
        fail("git %s failed: %s" % (" ".join(args), done.stderr.decode(errors="replace").strip()))
    return done.stdout


def blob(commit, path):
    """The file's bytes at `commit`, or None when it has no such file."""
    done = subprocess.run(("git", "cat-file", "blob", "%s:%s" % (commit, path)), capture_output=True)
    return done.stdout if done.returncode == 0 else None


def guard_version(commit):
    text = blob(commit, GUARD)
    found = VERSION_LINE.findall(text or b"")
    if len(found) != 1:
        fail("%s:%s has no single VERSION line" % (commit, GUARD))
    return found[0].decode()


def numeric(version):
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        fail("version %r is not dotted numbers" % version)
    return tuple(int(part) for part in version.split("."))


def swapped(text, old, new):
    old, new = old.encode(), new.encode()
    text = re.sub(rb'^VERSION = "' + re.escape(old) + rb'"$', b'VERSION = "' + new + b'"', text, flags=re.M)
    return text.replace(b"(skill version " + old + b")", b"(skill version " + new + b")")


def problems(base, head, old, new):
    """Each changed path must be M, keep its mode and differ only by the swap; a note may change or be added freely
    but must stay a plain file."""
    found = []
    raw = git("diff", "--no-renames", "--raw", "-z", base, head).split(b"\0")
    for meta, name in zip(raw[0:-1:2], raw[1::2]):
        old_mode, new_mode, _, _, status = meta.decode().lstrip(":").split(" ")
        path = name.decode(errors="surrogateescape")
        if path in NOTES:
            if status not in ("M", "A") or new_mode != "100644":
                found.append("entry: %s %s -> %s %s" % (status, old_mode, new_mode, path))
            continue
        if status != "M" or old_mode != new_mode:
            found.append("entry: %s %s -> %s %s" % (status, old_mode, new_mode, path))
        before, after = blob(base, path), blob(head, path)
        if before is None or after is None or swapped(before, old, new) != after:
            found.append("differs: %s" % path)
    return found


def still_old(head, old):
    """Files outside the notes that still hold an OLD form, such as one the swap never touched."""
    forms = (b'VERSION = "%s"' % old.encode(), b"(skill version %s)" % old.encode())
    out = git("grep", "-z", "-n", "-I", "-F", "-e", forms[0], "-e", forms[1], head, ok=(0, 1))
    found = []
    for hit in filter(None, out.split(b"\n")):
        path, line, text = hit.split(b"\0", 2)
        path = path.decode(errors="surrogateescape").split(":", 1)[1]
        if path not in NOTES and (text == forms[0] or forms[1] in text):
            found.append("still %s: %s:%s" % (old, path, line.decode()))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--base", required=True, help="the review trailer's base commit")
    parser.add_argument("--head", default="HEAD", help="the release commit (default HEAD)")
    args = parser.parse_args(argv)
    os.chdir(git("rev-parse", "--show-toplevel").decode().rstrip("\n"))  # pathspecs and git grep follow the cwd
    base = git("rev-parse", "--verify", args.base + "^{commit}").decode().strip()
    head = git("rev-parse", "--verify", args.head + "^{commit}").decode().strip()
    old, new = guard_version(base), guard_version(head)
    found = problems(base, head, old, new) + still_old(head, old)
    if numeric(new) <= numeric(old):
        found.insert(0, "version: %s is not higher than the base's %s" % (new, old))
    for line in found:
        print(line)
    if found:
        return 1
    print("release check: OK, %s -> %s, only the version swapped outside README.md and CHANGELOG.md (%s..%s)"
          % (old, new, base[:12], head[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
