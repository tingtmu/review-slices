#!/usr/bin/env python3
# Vendored into repos by the review-slices skill and linted where it is written, so a host repo's tools skip it:
# ruff: noqa
# flake8: noqa
# ruff: noqa: PGH004
# pylint: skip-file
# mypy: ignore-errors
# isort: skip_file
"""review-slices incident log report: open incidents, counts per slice, recurrences, and whether each plug exists.

    incidents.py [--path docs/INCIDENTS.md] [--check]   run inside the target repo; --check exits 1 on a problem

The log is in the format of the skill's templates/INCIDENTS.md: `## I<n>. <title>` headings, then `- **<label>:**`
bullets; entries whose date is still the template's `<...>` are skipped. For a `plugged` incident, each plug item
(separated by commas, semicolons, "and" or "or"; a trailing parenthetical is ignored) must exist:

    test <path>::<function>          the file defines it as a function or as a method of any class; with
    test <path>::<Class>::<method>   <path>::<Class>.<method>, that class defines it. Neither may be marked to never
                                     fail (expectedFailure, skip, xfail, skipTest, an always-true skipIf)
    guard <path>                     the file exists
    rule REVIEW.md "<line>"          REVIEW.md holds that text (backticks and whitespace runs are ignored); a
                                     `small:` or `medium:` line must be a line of its review-slices block, not a comment

Paths are relative to the repo root and stay inside it. A missing plug is a problem: the hole is open again. An
open incident older than 30 days is a note.

A miss through a reduced review load is a Slice field at 2 Review, or a recurrence, that names the load in
parentheses: `2 Review (merged reviewer)`, `2 Review (adversarial + conformance)`. Two or more misses through one
load are a problem until every incident they belong to is plugged with a working test, unless REVIEW.md's
review-slices block turns off the bands the load comes from: `small: off` for the merged reviewer; `medium: off` for
adversarial + conformance, and `small: off` too while the block has a `critical code:` line. Standard library only,
Python 3.8+.
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
# Reduced review loads a Slice 2 miss may name, as in "2 Review (merged reviewer)"; counted so a band can be narrowed.
MERGED, PAIR = "merged reviewer", "adversarial + conformance"
REDUCED_LOADS = (MERGED, PAIR)
# The bands each load comes from, which a second miss turns off until a test plug exists. The pair also comes from
# the small band at Critical while REVIEW.md has a `critical code:` line.
LOAD_BANDS = {MERGED: ("small",), PAIR: ("medium",)}
STATUSES = ("open", "plugged")
KINDS = ("defect", "process")
REOPEN = "the hole is open again; reopen the incident"
HEADING = re.compile(r"^##\s+(I\d+)\b\.?\s*(.*?)\s*$")
NEAR_HEADING = re.compile(r"^#{1,6}\s*(?:I|incident\s*)\d+\b", re.I)
FENCE = re.compile(r"^\s*(```|~~~)")
OTHER_HEADING = re.compile(r"^#{1,6}\s")
BULLET = re.compile(r"^[-*]\s+\*\*([^*]+?)\s*:?\s*\*\*\s*:?\s*(.*)$")
NESTED_BULLET = re.compile(r"^\s+[-*]\s+")
PLACEHOLDER = re.compile(r"<[A-Za-z][^<>]*>")
NAME = r"[A-Za-z_]\w*"
TEST_ITEM = re.compile(r"test\s+([^\s:,]+)::(%s(?:(?:::|\.)%s)*)(?:\[[^\]]*\])?" % (NAME, NAME))
GUARD_ITEM = re.compile(r"guard\s+([^\s,()]+)")
RULE_ITEM = re.compile(r"rule\s+(\S+)\s+[\"“]([^\"”]*)[\"”]")
RULE_FILE = "REVIEW.md"
# Text allowed after a plug item: nothing, or a parenthetical, then an optional full stop.
AFTER_ITEM = re.compile(r"^\s*(\([^()]*\))?\s*\.?\s*$")
# A separator between plug items, outside quotes and parentheses.
SEPARATOR = re.compile(r",|;|\s+and\s+|\s+or\s+")
BAND_RULE = re.compile(r"^(small|medium)\s*:")  # a band plug: a line the guard reads, never prose or a comment
NO_PLUG = re.compile(r"^(none|not yet)\b", re.I)
NO_RECURRENCE = re.compile(r"^(none|no|n/a|not yet)\b|^[-—\s]*$", re.I)
# Markers that keep a test from failing while its defect is back; skipIf and skipUnless only with a literal condition.
NEVER_FAILS = ("expectedFailure", "skip", "xfail", "skipTest")
CONDITIONAL = {"skipif": True, "skipunless": False}
Incident = collections.namedtuple("Incident", "id title date kind status slice fields")
Plug = collections.namedtuple("Plug", "kind path names text")


class IncidentError(Exception):
    """A problem the user can fix; printed without a traceback."""


def unfenced(text):
    """TEXT's lines, with lines inside fenced code blocks blanked."""
    lines, fenced = [], False
    for line in text.splitlines():
        fence = bool(FENCE.match(line))
        lines.append("" if fenced or fence else line)
        fenced = fenced != fence
    return lines


def split_entries(text):
    """[(id, title, {label: value})] for each `## I<n>.` heading; wrapped bullet lines are joined with a space."""
    entries, fields, label = [], None, None
    for line in unfenced(text):
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
        elif line.strip() and label and NESTED_BULLET.match(line):
            fields[label] = (fields[label] + ", " + NESTED_BULLET.sub("", line).strip()).strip(", ")
        elif line.strip() and label and (line[:1].isspace() or not line.lstrip().startswith(("-", "*"))):
            fields[label] = (fields[label] + " " + line.strip()).strip()
        elif not line.strip():
            label = None
    return entries


def near_headings(text):
    """Lines that look like an incident heading but are not `## I<n>. <title>`."""
    return [line.strip() for line in unfenced(text) if NEAR_HEADING.match(line) and not HEADING.match(line)]


def slice_of(value):
    """The canonical slice that the start of a "Slice that should have caught it" value names, by number or name."""
    head = re.sub(r"^slice\s*", "", value.strip().lower())
    number = re.match(r"([0-4])\b", head)
    if number:
        return SLICES[int(number.group(1))]
    for index, names in enumerate(SLICE_NAMES):
        if any(re.match(r"%s\b" % re.escape(name), head) for name in names):
            return SLICES[index]
    return UNKNOWN_SLICE


def parse_incident(ident, title, fields):
    """(incident, problems, notes): the Incident, or None when its date line cannot be read, and why."""
    line = fields.get("date / kind / status", "")
    parts = [part.strip().lower() for part in line.split("·")]
    if len(parts) != 3:
        return None, ["%s: the date / kind / status line is not '<date> · <kind> · <status>': %r"
                      % (ident, line)], []
    try:
        date = datetime.datetime.strptime(parts[0], "%Y-%m-%d").date()
    except ValueError:
        return None, ["%s: the date %r is not YYYY-MM-DD" % (ident, parts[0])], []
    if parts[2] not in STATUSES:
        return None, ["%s: the status %r is neither open nor plugged" % (ident, parts[2])], []
    slice_text = fields.get("slice that should have caught it", "")
    slice_name = slice_of(slice_text)
    notes = (["%s: the kind %r is neither defect nor process" % (ident, parts[1])] if parts[1] not in KINDS else [])
    notes += ["%s: no slice recognised in %r" % (ident, slice_text)] if slice_name == UNKNOWN_SLICE else []
    return Incident(ident, title, date, parts[1], parts[2], slice_name, fields), [], notes


def is_template(fields):
    """Whether an entry's date is still the template's `<...>` placeholder."""
    return bool(PLACEHOLDER.search(fields.get("date / kind / status", "").split("·")[0]))


def parse_log(text):
    """(incidents, problems, notes, skipped): the incidents in TEXT and what could not be read."""
    entries = split_entries(text)
    real = [entry for entry in entries if not is_template(entry[2])]
    problems = ["%r looks like an incident heading but is not `## I<n>. <title>`, so it was not read" % line
                for line in near_headings(text)]
    notes = [] if entries else ["no `## I<n>. <title>` heading found, so there are no incidents to report"]
    incidents = []
    for ident, title, fields in real:
        incident, entry_problems, entry_notes = parse_incident(ident, title, fields)
        seen = any(found.id == ident for found in incidents)
        twice = ["%s appears twice; give each incident its own id" % ident] if incident and seen else []
        problems, notes = problems + entry_problems + twice, notes + entry_notes
        incidents = incidents + [incident] if incident else incidents
    return incidents, problems, notes, len(entries) - len(real)


def split_items(value):
    """VALUE split at commas, semicolons, "and" and "or" outside double quotes, parentheses and brackets."""
    items, start, depth, quoted, index = [], 0, 0, False, 0
    while index < len(value):
        char = value[index]
        if char in "\"“”":
            quoted = not quoted if char == '"' else char == "“"
        elif not quoted and char in "()[]":
            depth = max(0, depth + (1 if char in "([" else -1))
        separator = None if quoted or depth else SEPARATOR.match(value, index)
        if separator:
            items.append(value[start:index])
            start = index = separator.end()
            continue
        index += 1
    items.append(value[start:])
    return [item.strip() for item in items if item.strip()]


def parse_item(item):
    """A Plug for ITEM, or None when it is not a test, guard or rule followed by at most a parenthetical."""
    for kind, pattern in (("test", TEST_ITEM), ("guard", GUARD_ITEM), ("rule", RULE_ITEM)):
        match = pattern.match(item)
        if match and AFTER_ITEM.match(item[match.end():]):
            names = re.split(r"::|\.", match.group(2)) if kind == "test" else [match.group(2)] if kind == "rule" else []
            return Plug(kind, match.group(1), names, match.group(0))
    return None


def parse_plug(value):
    """(plugs, unread): the plug items in VALUE, and the items that are none of test, guard or rule."""
    if not value or NO_PLUG.match(value.strip()):
        return [], []
    plugs, unread = [], []
    unquoted = re.split(r"(\"[^\"]*\"|“[^”]*”)", value)
    value = "".join(part if index % 2 else part.replace("`", "") for index, part in enumerate(unquoted))
    for item in split_items(value):
        plug = parse_item(item)
        if plug:
            plugs.append(plug)
        else:
            unread.append(item)
    return plugs, unread


def last(scope, kinds, name):
    """The last node of KINDS named NAME in SCOPE (a later definition replaces an earlier one), or None."""
    found = [node for node in scope if isinstance(node, kinds) and node.name == name]
    return found[-1] if found else None


def find_function(tree, names):
    """(function, classes around it) that NAMES points at in the module TREE: [function] is a function or a method
    of any class; [Class, ..., method] a method. (None, []) when there is none."""
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    if len(names) == 1:
        for scope in [tree] + [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
            found = last(scope.body, functions, names[0])
            if found:
                return found, [] if scope is tree else [scope]
        return None, []
    scope, classes = tree.body, []
    for name in names[:-1]:
        cls = last(scope, ast.ClassDef, name)
        if cls is None:
            return None, []
        classes.append(cls)
        scope = cls.body
    method = last(scope, functions, names[-1])
    return (method, classes) if method else (None, [])


def lineage(tree, classes):
    """CLASSES and every base class of theirs that the module TREE defines."""
    module = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    found, todo = [], list(classes)
    while todo:
        cls = todo.pop()
        if cls not in found:
            found.append(cls)
            todo += [module[base.id] for base in cls.bases if isinstance(base, ast.Name) and base.id in module]
    return found


def decorator_name(node):
    node = node.func if isinstance(node, ast.Call) else node
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")


def always_skips(node):
    """The name of NODE (a marker, or a list of them) when it always stops a test failing, else None."""
    for item in node.elts if isinstance(node, (ast.List, ast.Tuple)) else [node]:
        name = decorator_name(item)
        first = item.args[0] if isinstance(item, ast.Call) and item.args else None
        literal = isinstance(first, ast.Constant) and first.value is CONDITIONAL.get(name.lower())
        if name in NEVER_FAILS or (name.lower() in CONDITIONAL and literal):
            return name
    return None


def never_fails(tree, function, classes):
    """The marker that stops FUNCTION failing: on it, its classes or their bases, a `pytestmark`, or a skip call in
    its body. None when there is none."""
    scopes = lineage(tree, classes)
    markers = [decorator for node in [function] + scopes for decorator in node.decorator_list]
    markers += [node.value for scope in [tree] + scopes for node in scope.body if isinstance(node, ast.Assign)
                and any(getattr(target, "id", "") == "pytestmark" for target in node.targets)]
    markers += [node.value for node in function.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and decorator_name(node.value) in NEVER_FAILS]
    for marker in markers:
        if always_skips(marker):
            return always_skips(marker)
    return None


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def flat(text):
    """TEXT with backticks dropped and whitespace runs made one space, for comparing rule lines."""
    return " ".join(text.replace("`", "").split())


def block_lines(text):
    """The lines of TEXT's first review-slices block as the guard reads them: comments dropped, flattened."""
    block = re.search(r"^```review-slices[^\n]*\n(.*?)^```", text, re.S | re.M)
    return [flat(re.sub(r"(?:^|\s)#.*$", "", line)) for line in (block.group(1).splitlines() if block else [])]


def broken_test(path, plug, text):
    """Why the test PLUG in the file at PATH, holding TEXT, is not a working test, or None."""
    if not plug.path.endswith(".py"):
        found = re.search(r"\b%s\b" % re.escape(plug.names[-1]), text)
        return None if found else "%s does not mention %s" % (plug.path, plug.names[-1])
    try:
        tree = ast.parse(text, path)
    except (SyntaxError, ValueError) as error:
        return "%s does not parse as Python (%s)" % (plug.path, error)
    function, classes = find_function(tree, plug.names)
    if function is None:
        return "%s defines no %s" % (plug.path, ".".join(plug.names))
    marker = never_fails(tree, function, classes)
    if marker:
        return "%s is marked %s, so it passes while the defect is back" % (".".join(plug.names), marker)
    return None


def plug_problem(root, plug):
    """Why PLUG does not exist under ROOT, or None when it does."""
    parts = plug.path.replace("\\", "/").split("/")
    if os.path.isabs(plug.path) or ".." in parts:
        return "%s is not a path inside the repo" % plug.path
    if plug.kind == "rule" and plug.path != RULE_FILE:
        return "a rule plug must name %s, not %s" % (RULE_FILE, plug.path)
    if plug.kind == "rule" and not flat(plug.names[0]):
        return "the rule's quoted line is blank"
    path = os.path.join(root, plug.path)
    if not os.path.isfile(path):
        return "%s does not exist" % plug.path
    if os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) != os.path.realpath(root):
        return "%s is a link to a file outside the repo" % plug.path
    try:
        text = read_text(path)
    except OSError as error:
        return "%s cannot be read (%s)" % (plug.path, error.strerror or error)
    if plug.kind == "rule" and flat(plug.names[0]) not in flat(text):
        return "%s does not contain %r" % (plug.path, plug.names[0])
    if plug.kind == "rule" and BAND_RULE.match(flat(plug.names[0])) and flat(plug.names[0]) not in block_lines(text):
        return "%s's review-slices block has no line %r, so the band is not narrowed" % (plug.path, plug.names[0])
    return broken_test(path, plug, text) if plug.kind == "test" else None


def check_plugs(root, incident):
    """(problems, notes): a problem for each plug item of a plugged INCIDENT that is missing or cannot be read."""
    plugs, unread = parse_plug(incident.fields.get("plug", ""))
    if incident.status != "plugged":
        return [], (["%s: %d plug item(s) not understood, the first %r; they are checked once it is plugged"
                     % (incident.id, len(unread), unread[0])] if unread else [])
    problems = ["%s is plugged but names no plug; name it or reopen the incident" % incident.id] if not (
        plugs or unread) else []
    problems += ["%s: plug item not understood, so it cannot be checked: %r (write `test <path>::<function>`"
                 ", `guard <path>` or `rule REVIEW.md \"<line>\"`)" % (incident.id, item) for item in unread]
    reasons = [(plug, plug_problem(root, plug)) for plug in plugs]
    problems += ["%s: plug `%s` is missing: %s; %s" % (incident.id, plug.text, reason, REOPEN)
                 for plug, reason in reasons if reason]
    return problems, []


def age_notes(incident, today):
    """Notes on INCIDENT's date: in the future, or open for more than OPEN_DAYS."""
    age = (today - incident.date).days
    notes = ["%s is dated %s, in the future" % (incident.id, incident.date)] if age < 0 else []
    if incident.status == "open" and age > OPEN_DAYS:
        notes += ["%s has been open for %d days (over %d); plug it or say why not" % (incident.id, age, OPEN_DAYS)]
    return notes


def has_recurrences(incident):
    return not NO_RECURRENCE.match(incident.fields.get("recurrences", "").strip())


def misses(incident):
    """[load, ...]: one for each miss of INCIDENT through a reduced review load, from its Slice field at 2 Review
    and from each recurrence that names the load."""
    slice_text = incident.fields.get("slice that should have caught it", "").lower()
    recurrences = incident.fields.get("recurrences", "").lower()
    found = [load for load in REDUCED_LOADS if incident.slice == SLICES[2] and "(%s)" % load in slice_text]
    return found + [load for load in REDUCED_LOADS for _ in range(recurrences.count("(%s)" % load))]


def tested(root, incident):
    """Whether INCIDENT is plugged with at least one test plug that exists."""
    plugs, _unread = parse_plug(incident.fields.get("plug", ""))
    return incident.status == "plugged" and any(plug.kind == "test" and not plug_problem(root, plug)
                                                for plug in plugs)


def bands_on(root, load):
    """The `small: off` / `medium: off` lines REVIEW.md's review-slices block lacks to stop LOAD (a band with no line
    is on: small by default). An unreadable REVIEW.md turns nothing off."""
    try:
        lines = block_lines(read_text(os.path.join(root, RULE_FILE)))
    except OSError:
        lines = []
    settings = [tuple(part.strip() for part in line.partition(":")[::2]) for line in lines]
    code = load == PAIR and any(key == "critical code" for key, _value in settings)
    return ["%s: off" % band for band in LOAD_BANDS[load] + (("small",) if code else ())
            if (band, "off") not in settings]


def band_problems(root, incidents):
    """A problem for each reduced load that two or more misses went through while one of their incidents has no
    test plug and REVIEW.md leaves a band of that load on: the band is off until a test plug exists."""
    problems = []
    for load in REDUCED_LOADS:
        through = [incident for incident in incidents for found in misses(incident) if found == load]
        ids = list(dict.fromkeys(incident.id for incident in through))
        untested = list(dict.fromkeys(incident.id for incident in through if not tested(root, incident)))
        missing = bands_on(root, load) if len(through) > 1 and untested else []
        if missing:
            problems.append("%d misses went through the %s load (%s) and %s has no working test plug, so %s's "
                            "review-slices block needs %s until each has one"
                            % (len(through), load, ", ".join(ids), ", ".join(untested), RULE_FILE,
                               " and ".join("`%s`" % line for line in missing)))
    return problems


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
    loads = collections.Counter(load for incident in incidents for load in misses(incident))
    if loads:
        print("  misses through a reduced load, recurrences included: " + ", ".join(
            "%s %d" % (load, loads[load]) for load in REDUCED_LOADS))
    recurring = [incident for incident in incidents if has_recurrences(incident)]
    print("recurrences (each means a weak plug):" + ("" if recurring else " none"))
    for incident in recurring:
        print("  %s. %s: %s" % (incident.id, incident.title, incident.fields["recurrences"]))


def repo_root():
    """The git top level of the current directory, or the current directory outside git."""
    try:
        done = subprocess.run(("git", "rev-parse", "--show-toplevel"), capture_output=True, text=True)
    except OSError:
        done = None
    return done.stdout.strip() if done and done.returncode == 0 and done.stdout.strip() else os.getcwd()


def report(path, root, check, today=None):
    """Print the report for the log at PATH; return the exit code."""
    try:
        with open(path, encoding="utf-8-sig") as handle:
            text = handle.read()
    except OSError as error:
        raise IncidentError("cannot read %s: %s" % (path, error.strerror or error))
    except UnicodeDecodeError:
        raise IncidentError("%s is not UTF-8 text" % path)
    today = today or datetime.date.today()
    incidents, problems, notes, skipped = parse_log(text)
    for incident in incidents:
        plug_problems, plug_notes = check_plugs(root, incident)
        problems, notes = problems + plug_problems, notes + plug_notes + age_notes(incident, today)
    problems += band_problems(root, incidents)
    print_report(os.path.relpath(path), incidents, skipped, today)
    for message in notes:
        print("note: " + message)
    for message in problems:
        print("problem: " + message)
    print("incidents: %s" % ("%d problem(s)" % len(problems) if problems else "ok"))
    return 1 if check and problems else 0


def main(argv):
    sys.stdout.reconfigure(errors="backslashreplace")
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
