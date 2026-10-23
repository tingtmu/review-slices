#!/usr/bin/env python3
"""review-slices incident log report: open incidents, counts per slice, recurrences, and whether each plug exists.

    incidents.py [--path docs/INCIDENTS.md] [--check]

Run it inside the target repo. It reads the incident log in the format of the skill's templates/INCIDENTS.md: one
`## I<n>. <title>` heading per incident, then `- **<label>:** <value>` bullets. It prints the open incidents with
their age and plug, how many incidents each slice should have caught, and the incidents with recurrences (each one
means a weak plug).

For a `plugged` incident it checks that each plug item, separated by commas, still exists:

    test <path>::<function>          the file defines that function, or a method of that name in any class
    test <path>::<Class>::<method>   (or <path>::<Class>.<method>) the class defines that method
    guard <path>                     the file exists
    rule REVIEW.md "<line>"          that text appears in REVIEW.md (whitespace is not significant)

Paths are relative to the repo root. Free text after an item, such as "(expected failures until fixed)", is
ignored. A missing plug is a problem: the hole is open again. An open incident older than 30 days is a note.
--check exits 1 on any problem, so a repo can put it in its suite; without it the report always exits 0.
Entries that still hold the template's `<...>` placeholders in their heading or date line are skipped.
Standard library only, Python 3.8+.
"""
import argparse
import ast
import collections
import datetime
import os
import re
import subprocess
import sys

OPEN_DAYS = 30
SLICES = ("0 Shown output", "1 Offline suite", "2 Review", "3 Go-ahead", "4 Acceptance")
# Lower-case names a log may use for each slice, including older wording.
SLICE_NAMES = (("shown output",), ("offline suite", "offline tests", "offline test"), ("review",),
               ("go-ahead", "go ahead"), ("acceptance",))
UNKNOWN_SLICE = "unknown"
STATUSES = ("open", "plugged")
KINDS = ("defect", "process")
REOPEN = "the hole is open again; reopen the incident"
HEADING = re.compile(r"^##\s+(I\d+)\b\.?\s*(.*?)\s*$")
OTHER_HEADING = re.compile(r"^#{1,6}\s")
BULLET = re.compile(r"^[-*]\s+\*\*([^*]+?)\s*:?\s*\*\*\s*:?\s*(.*)$")
PLACEHOLDER = re.compile(r"<[A-Za-z][^<>]*>")
NAME = r"[A-Za-z_]\w*"
TEST_ITEM = re.compile(r"test\s+([^\s:,]+)::(%s(?:(?:::|\.)%s)*)(?:\[[^\]]*\])?" % (NAME, NAME))
GUARD_ITEM = re.compile(r"guard\s+([^\s,()]+)")
RULE_ITEM = re.compile(r"rule\s+(\S+)\s+[\"“]([^\"”]+)[\"”]")
NO_PLUG = re.compile(r"^(none|not yet)\b", re.I)
Incident = collections.namedtuple("Incident", "id title date kind status slice fields")
Plug = collections.namedtuple("Plug", "kind path names text")


class IncidentError(Exception):
    """A problem the user can fix; printed without a traceback."""


def split_entries(text):
    """[(id, title, {label: value})] for each `## I<n>.` heading; wrapped bullet lines are joined with a space."""
    entries, fields, label = [], None, None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading or OTHER_HEADING.match(line):
            fields, label = None, None
            if heading:
                fields = collections.OrderedDict()
                entries.append((heading.group(1), heading.group(2), fields))
            continue
        if fields is None:
            continue
        bullet = BULLET.match(line.strip())
        if bullet:
            label = bullet.group(1).strip().lower()
            fields[label] = bullet.group(2).strip()
        elif line.strip() and label and (line[:1].isspace() or not line.lstrip().startswith(("-", "*"))):
            fields[label] = (fields[label] + " " + line.strip()).strip()
        elif not line.strip():
            label = None
    return entries


def slice_of(value):
    """The canonical slice a "Slice that should have caught it" value names, by number or by name."""
    head = value.split("Why it did not")[0].strip().lower()
    number = re.match(r"(?:slice\s*)?([0-4])\b", head)
    if number:
        return SLICES[int(number.group(1))]
    for index, names in enumerate(SLICE_NAMES):
        if any(re.search(r"\b%s\b" % re.escape(name), head) for name in names):
            return SLICES[index]
    return UNKNOWN_SLICE


def parse_incident(ident, title, fields, problems, notes):
    """An Incident, or None when its date line cannot be read."""
    line = fields.get("date / kind / status", "")
    parts = [part.strip().lower() for part in line.split("·")]
    if len(parts) != 3:
        problems.append("%s: the date / kind / status line is not '<date> · <kind> · <status>': %r"
                        % (ident, line))
        return None
    try:
        date = datetime.datetime.strptime(parts[0], "%Y-%m-%d").date()
    except ValueError:
        problems.append("%s: the date %r is not YYYY-MM-DD" % (ident, parts[0]))
        return None
    if parts[2] not in STATUSES:
        problems.append("%s: the status %r is neither open nor plugged" % (ident, parts[2]))
        return None
    if parts[1] not in KINDS:
        notes.append("%s: the kind %r is neither defect nor process" % (ident, parts[1]))
    slice_name = slice_of(fields.get("slice that should have caught it", ""))
    if slice_name == UNKNOWN_SLICE:
        notes.append("%s: no slice recognised in %r" % (ident, fields.get("slice that should have caught it", "")))
    return Incident(ident, title, date, parts[1], parts[2], slice_name, fields)


def parse_log(text):
    """(incidents, problems, notes, skipped): the incidents in TEXT and what could not be read."""
    incidents, problems, notes, skipped, seen = [], [], [], 0, set()
    entries = split_entries(text)
    if not entries:
        notes.append("no `## I<n>. <title>` heading found, so there are no incidents to report")
    for ident, title, fields in entries:
        if PLACEHOLDER.search(title) or PLACEHOLDER.search(fields.get("date / kind / status", "")):
            skipped += 1
            continue
        incident = parse_incident(ident, title, fields, problems, notes)
        if incident is None:
            continue
        if ident in seen:
            problems.append("%s appears twice; give each incident its own id" % ident)
        seen.add(ident)
        incidents.append(incident)
    return incidents, problems, notes, skipped


def split_items(value):
    """VALUE split at commas outside double quotes."""
    items, current, quoted = [], [], False
    for char in value:
        if char in "\"“”":
            quoted = not quoted if char == '"' else char == "“"
        if char == "," and not quoted:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return [item.strip() for item in items if item.strip()]


def parse_plug(value):
    """(plugs, unread): the plug items in VALUE, and the items that are none of test, guard or rule."""
    if not value or NO_PLUG.match(value.strip()):
        return [], []
    plugs, unread = [], []
    for item in split_items(value.replace("`", "")):
        item = re.sub(r"^(and|or)\s+", "", item)
        test, guard, rule = TEST_ITEM.match(item), GUARD_ITEM.match(item), RULE_ITEM.match(item)
        if test:
            plugs.append(Plug("test", test.group(1), re.split(r"::|\.", test.group(2)), test.group(0)))
        elif guard:
            plugs.append(Plug("guard", guard.group(1), [], guard.group(0)))
        elif rule:
            plugs.append(Plug("rule", rule.group(1), [rule.group(2)], rule.group(0)))
        else:
            unread.append(item)
    return plugs, unread


def defines(tree, names):
    """Whether the module TREE defines NAMES: [function], a function or method; [Class, ..., method] a method."""
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    if len(names) == 1:
        if any(isinstance(node, functions) and node.name == names[0] for node in tree.body):
            return True
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        return any(isinstance(node, functions) and node.name == names[0] for cls in classes for node in cls.body)
    scope = tree.body
    for name in names[:-1]:
        found = [node for node in scope if isinstance(node, ast.ClassDef) and node.name == name]
        if not found:
            return False
        scope = found[0].body
    return any(isinstance(node, functions) and node.name == names[-1] for node in scope)


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def plug_problem(root, plug):
    """Why PLUG does not exist under ROOT, or None when it does."""
    path = os.path.join(root, plug.path)
    if not os.path.isfile(path):
        return "%s does not exist" % plug.path
    if plug.kind == "rule":
        if " ".join(plug.names[0].split()) not in " ".join(read_text(path).split()):
            return "%s does not contain %r" % (plug.path, plug.names[0])
    elif plug.kind == "test" and plug.path.endswith(".py"):
        try:
            tree = ast.parse(read_text(path), plug.path)
        except SyntaxError as error:
            return "%s does not parse as Python (line %s)" % (plug.path, error.lineno)
        if not defines(tree, plug.names):
            return "%s defines no %s" % (plug.path, ".".join(plug.names))
    elif plug.kind == "test" and not re.search(r"\b%s\b" % re.escape(plug.names[-1]), read_text(path)):
        return "%s does not mention %s" % (plug.path, plug.names[-1])
    return None


def check_plugs(root, incident, problems, notes):
    """Add a problem for each plug item of a plugged INCIDENT that is missing or cannot be read."""
    plugs, unread = parse_plug(incident.fields.get("plug", ""))
    if incident.status != "plugged":
        if unread:
            notes.append("%s: %d plug item(s) not understood, the first %r; they are checked once it is plugged"
                         % (incident.id, len(unread), unread[0]))
        return
    if not plugs and not unread:
        problems.append("%s is plugged but names no plug; name it or reopen the incident" % incident.id)
    for item in unread:
        problems.append("%s: plug item not understood, so it cannot be checked: %r (write `test <path>::<function>`"
                        ", `guard <path>` or `rule REVIEW.md \"<line>\"`)" % (incident.id, item))
    for plug in plugs:
        reason = plug_problem(root, plug)
        if reason:
            problems.append("%s: plug `%s` is missing: %s; %s" % (incident.id, plug.text, reason, REOPEN))


def has_recurrences(incident):
    value = incident.fields.get("recurrences", "").strip()
    return bool(value) and not NO_PLUG.match(value)


def print_report(where, incidents, skipped, today):
    open_ones = [incident for incident in incidents if incident.status == "open"]
    print("incidents: %s: %d incident(s), %d open, %d plugged%s"
          % (where, len(incidents), len(open_ones), len(incidents) - len(open_ones),
             ", %d template entry skipped" % skipped if skipped else ""))
    print("open:" + ("" if open_ones else " none"))
    for incident in open_ones:
        print("  %s. %s (%d days)" % (incident.id, incident.title, (today - incident.date).days))
        print("      plug: %s" % (incident.fields.get("plug") or "none yet"))
    counts = collections.Counter(incident.slice for incident in incidents)
    print("by slice that should have caught it:")
    for name in SLICES + ((UNKNOWN_SLICE,) if counts[UNKNOWN_SLICE] else ()):
        print("  %-16s %d" % (name, counts[name]))
    recurring = [incident for incident in incidents if has_recurrences(incident)]
    print("recurrences (each means a weak plug):" + ("" if recurring else " none"))
    for incident in recurring:
        print("  %s. %s: %s" % (incident.id, incident.title, incident.fields["recurrences"]))


def repo_root():
    """The git top level of the current directory, or the current directory outside git."""
    try:
        done = subprocess.run(("git", "rev-parse", "--show-toplevel"), capture_output=True, text=True)
    except OSError:
        return os.getcwd()
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else os.getcwd()


def report(path, root, check, today=None):
    """Print the report for the log at PATH; return the exit code."""
    try:
        text = read_text(path)
    except OSError as error:
        raise IncidentError("cannot read %s: %s" % (path, error.strerror or error))
    today = today or datetime.date.today()
    incidents, problems, notes, skipped = parse_log(text)
    for incident in incidents:
        check_plugs(root, incident, problems, notes)
        age = (today - incident.date).days
        if incident.status == "open" and age > OPEN_DAYS:
            notes.append("%s has been open for %d days (over %d); plug it or say why not" % (incident.id, age, OPEN_DAYS))
    print_report(os.path.relpath(path), incidents, skipped, today)
    for message in notes:
        print("note: " + message)
    for message in problems:
        print("problem: " + message)
    print("incidents: %s" % ("%d problem(s)" % len(problems) if problems else "ok"))
    return 1 if check and problems else 0


def main(argv):
    parser = argparse.ArgumentParser(prog="incidents.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", help="the incident log (default: docs/INCIDENTS.md at the repo root)")
    parser.add_argument("--check", action="store_true", help="exit 1 if any plug is missing or unreadable")
    args = parser.parse_args(argv[1:])
    root = repo_root()
    try:
        return report(args.path or os.path.join(root, "docs", "INCIDENTS.md"), root, args.check)
    except IncidentError as error:
        print("incidents: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
