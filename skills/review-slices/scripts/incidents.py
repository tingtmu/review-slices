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
                                     `small:` or `medium:` line must be a line of its review-slices block, not a
                                     comment, unless the block turns that band off
    check "<test: line>"             a `test:` line of REVIEW.md's review-slices block (comments dropped, as the
                                     guard reads it) whose raw line ends with the comment `# <this incident's id>`
                                     alone; the quoted line may not contain `"`

Paths are relative to the repo root and stay inside it. A missing plug is a problem: the hole is open again. An
open incident older than 30 days is a note. A test plug on a .md, .txt or .rst file is no plug. A Plug field may end
with `(no check: <reason>)`, also after `none yet`; a reason in words is a note. An incident with a recurrence (a
date in its Recurrences field), open or plugged, is a problem until it has a working test or check plug or such a
reason. A `(suite)` mark in REVIEW.md is a problem unless it is on a "Failure looks like" item linking `[I<n>]`
incidents that all have a working test or check plug and no recurrence; elsewhere, one in backticks is a mention.
Two notes never change the exit code: a one-sighting near miss in docs/NEAR-MISSES.md (one date that is not
`rejected <date>`) older than 90 days, and `prune due` when the log's `Last pruned: YYYY-MM-DD` is missing or older
than 90 days.

A miss through a reduced review load is a Slice field at 2 Review, or a recurrence, that names the load in
parentheses: `2 Review (merged reviewer)` (or `one merged reviewer`, as `status` prints it, with more after it),
`2 Review (adversarial + conformance)` (or `and`). A miss may name the review unit it went through, the commit
that carries the unit's trailer, after the load: `2 Review (merged reviewer), unit 1a2b3c4d`. Misses that name the
same unit count as one; a miss that names none counts alone. Misses from two or more review units through one load
are a problem until each incident they belong to is plugged with a distinct working test per miss, unless
REVIEW.md's review-slices block has the line that load needs: `small: off` for the merged reviewer; `cross-check: on`
for adversarial + conformance, the most `status` prints since 0.13.0. A miss through the pair names the unit's size
band or Critical after the load, `2 Review (adversarial + conformance, large)`; the report counts those.
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
# Reduced review loads a Slice 2 miss may name, as in "2 Review (merged reviewer)"; misses from a second review
# unit turn them off.
MERGED, PAIR = "merged reviewer", "adversarial + conformance"
REDUCED_LOADS = (MERGED, PAIR)
# A load that opens a parenthesis, as SKILL.md writes it or `status` prints it, with anything after it, parentheses
# included: "(merged reviewer)", "(one merged reviewer (small: ...))". A mention in prose is no miss.
LOAD_NAMES = {MERGED: re.compile(r"\((?:one\s+)?merged\s+reviewers?\b", re.I),
              PAIR: re.compile(r"\(adversarial\s*(?:\+|and)\s*conformance\b", re.I)}
# The review-slices block lines that misses from a second review unit through each load need until a test plug
# exists: the merged reviewer's band off; for the pair, the most `status` prints since 0.13.0, a cross-check (no band
# turned off lightens it any more).
NEEDED = {MERGED: ("small: off",), PAIR: ("cross-check: on",)}
# A miss through the pair names the unit's size band, or Critical, after the load: "(adversarial + conformance, large)".
LARGE = re.compile(r"\b(large|critical)\b", re.I)
BAND = re.compile(r"\b(small|medium|large|critical)\b", re.I)
# The review unit a miss went through, right after its load's parentheses: ", unit <sha>" (the commit that carries
# the unit's trailer). A sha anywhere else names no unit.
UNIT = re.compile(r"\s*,?\s*unit\s+`?([0-9a-f]{7,40})\b", re.I)
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
TEXT_FILES = (".md", ".txt", ".rst")  # a test plug naming one of these is no test (its name is only grepped)
# Text allowed after a plug item: nothing, or a parenthetical, then an optional full stop.
AFTER_ITEM = re.compile(r"^\s*(\([^()]*\))?\s*\.?\s*$")
# A check plug quotes a `test:` line of REVIEW.md's block: its text runs to the last quote before what AFTER_ITEM
# allows, so a `"` inside it is read and refused rather than cut short.
CHECK_ITEM = re.compile(r"check\s+[\"“](.*)[\"”](?=\s*(?:\([^()]*\))?\s*\.?\s*$)")
# Why an incident has no test or check plug, at the end of its Plug field: "none yet (no check: <reason>)".
NO_CHECK = re.compile(r"\(\s*no\s+check\s*:\s*([^()]*?)\s*\)\s*\.?\s*$", re.I)
# The comment that ends the block line a check plug names: that incident's id alone.
CHECK_TAG = re.compile(r"\s#\s*(I\d+)\s*$")
FAILURES = re.compile(r"^#{1,6}\s+Failure looks like\s*$", re.I)  # REVIEW.md's section of failure classes
SUITE = re.compile(r"\(suite\)", re.I)
ITEM = re.compile(r"\s*(?:[-*]|\d+[.)])\s")  # a bullet or numbered item
SECTION_END = re.compile(r"^#{1,2}\s")  # a "Failure looks like" section runs to the next level-1 or 2 heading
LINK = re.compile(r"\[(I\d+)\]")
STALE_DAYS = 90
NEAR_MISSES = "docs/NEAR-MISSES.md"  # os.path.join takes "/" on every platform
DATE = r"\d{4}-\d{2}-\d{2}"
SIGHTING = re.compile(r"(rejected\s+)?\b(%s)\b" % DATE, re.I)
KEPT = re.compile(r"^\s*[-*]\s+F\d+\b|\bplugged:", re.I)  # a promoted or plugged near miss: pruning reads it
LAST_PRUNED = re.compile(r"Last pruned\W*(%s)\b" % DATE, re.I)
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
    """A Plug for ITEM, or None when it is not a test, guard, rule or check followed by at most a parenthetical."""
    check = CHECK_ITEM.match(item)
    if check:
        return Plug("check", RULE_FILE, [check.group(1)], check.group(0))
    for kind, pattern in (("test", TEST_ITEM), ("guard", GUARD_ITEM), ("rule", RULE_ITEM)):
        match = pattern.match(item)
        if match and AFTER_ITEM.match(item[match.end():]):
            names = re.split(r"::|\.", match.group(2)) if kind == "test" else [match.group(2)] if kind == "rule" else []
            return Plug(kind, match.group(1), names, match.group(0))
    return None


def no_check(value):
    """The reason in a `(no check: <reason>)` that ends the Plug field VALUE, or None when it gives none in words (a
    placeholder such as the template's `<reason>`, a dash or a number is none)."""
    match = NO_CHECK.search(value or "")
    reason = match.group(1) if match else ""
    return reason if re.search(r"[^\W\d_]", reason) and not PLACEHOLDER.search(reason) else None


def parse_plug(value):
    """(plugs, unread): the plug items in VALUE, and the items that are none of test, guard, rule or check; a
    closing `(no check: <reason>)` is no item."""
    value = NO_CHECK.sub("", value or "").strip()
    if not value or NO_PLUG.match(value):
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


def raw_block(text):
    """The raw lines of TEXT's first review-slices block, comments kept."""
    block = re.search(r"^```review-slices[ \t]*\r?\n(.*?)^```", text, re.S | re.M)  # the guard's fence, exactly
    return block.group(1).splitlines() if block else []


def uncommented(line):
    """LINE as the guard reads a block line: its comment dropped, flattened."""
    return flat(re.sub(r"(?:^|\s)#.*$", "", line))


def block_lines(text):
    """The lines of TEXT's first review-slices block as the guard reads them: comments dropped, flattened."""
    return [uncommented(line) for line in raw_block(text)]


def check_problem(plug, ident, text):
    """Why the check PLUG of incident IDENT is not a working check in REVIEW.md, holding TEXT, or None: its line must
    be a `test:` line of the block that ends with the comment `# <IDENT>`, so it pins that incident alone."""
    line = uncommented(plug.names[0])
    if '"' in plug.names[0]:
        return "the quoted line contains `\"`; quote the test: line's arguments with single quotes"
    found = [raw for raw in raw_block(text) if uncommented(raw) == line]
    if line.partition(":")[0].strip() != "test" or not found:
        return "%r is not a `test:` line of %s's review-slices block" % (plug.names[0], RULE_FILE)
    tags = [CHECK_TAG.search(raw) for raw in found]
    if not any(tag and tag.group(1) == ident for tag in tags):
        return "%s's block line %r does not end with the comment `# %s`, so it is not that incident's own check" % (
            RULE_FILE, found[0].strip(), ident)
    return None


def block_settings(text):
    """[(key, value)] of TEXT's review-slices block, split at the first colon as the guard splits them."""
    return [tuple(part.strip() for part in line.partition(":")[::2]) for line in block_lines(text)]


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


def inside(root, path):
    """Whether PATH, links followed, is inside ROOT."""
    return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)


def plug_problem(root, plug, ident=None):
    """Why PLUG, of incident IDENT, does not exist under ROOT, or None when it does."""
    parts = plug.path.replace("\\", "/").split("/")
    if os.path.isabs(plug.path) or ".." in parts:
        return "%s is not a path inside the repo" % plug.path
    if plug.kind == "rule" and plug.path != RULE_FILE:
        return "a rule plug must name %s, not %s" % (RULE_FILE, plug.path)
    if plug.kind == "rule" and not flat(plug.names[0]):
        return "the rule's quoted line is blank"
    if plug.kind == "test" and plug.path.lower().endswith(TEXT_FILES):
        return "a test plug must name a test file the suite runs, not the text file %s" % plug.path
    path = os.path.join(root, plug.path)
    if not os.path.isfile(path):
        return "%s does not exist" % plug.path
    if not inside(root, path):
        return "%s is a link to a file outside the repo" % plug.path
    try:
        text = read_text(path)
    except OSError as error:
        return "%s cannot be read (%s)" % (plug.path, error.strerror or error)
    band = BAND_RULE.match(flat(plug.names[0])) if plug.kind == "rule" else None
    if band and (band.group(1), "off") in block_settings(text):
        return None  # off is narrower than any band the plug names: misses from a second review unit turned it off
    if plug.kind == "rule" and flat(plug.names[0]) not in flat(text):
        return "%s does not contain %r" % (plug.path, plug.names[0])
    if band and flat(plug.names[0]) not in block_lines(text):
        return "%s's review-slices block has no line %r, so the band is not narrowed" % (plug.path, plug.names[0])
    if plug.kind == "check":
        return check_problem(plug, ident, text)
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
                 ", `guard <path>`, `rule REVIEW.md \"<line>\"` or `check \"<test: line>\"`)" % (incident.id, item)
                 for item in unread]
    reasons = [(plug, plug_problem(root, plug, incident.id)) for plug in plugs]
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


def recurrence_text(incident):
    """INCIDENT's Recurrences field, or its singular Recurrence alias, nested lines included."""
    return " ".join(incident.fields.get(label, "") for label in ("recurrences", "recurrence")).strip()


def has_recurrences(incident):
    """Whether INCIDENT has a recurrence: its field holds a YYYY-MM-DD date, or any text that is not `none` or the
    like. The report, the escalation rule and the (suite) rule all read recurrences this way."""
    text = recurrence_text(incident)
    return bool(re.search(r"\b%s\b" % DATE, text)) or not NO_RECURRENCE.match(text)


def misses(incident):
    """[(load, unit), ...]: one for each miss of INCIDENT through a reduced review load, from its Slice field at
    2 Review and from each recurrence that names the load in parentheses; UNIT is the review unit named after it,
    or None."""
    slice_text, recurrences = (incident.fields.get(label, "") for label in ("slice that should have caught it",
                                                                            "recurrences"))
    first = {}
    for load, unit in named_loads(slice_text) if incident.slice == SLICES[2] else ():
        first.setdefault(load, unit)
    return list(first.items()) + named_loads(recurrences)


def named_loads(text):
    """[(load, unit), ...] for each reduced load TEXT names, in order, with the unit named right after it."""
    found = sorted((match.start(), load) for load in REDUCED_LOADS for match in LOAD_NAMES[load].finditer(text))
    return [(load, unit_after(text, start)) for start, load in found]


def closing(text, start):
    """The index of the parenthesis that closes the one opening at START in TEXT, or None."""
    depth = 0
    for index in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[index], 0)
        if depth == 0:
            return index
    return None


def unit_after(text, start):
    """The unit named right after the parentheses that open at START in TEXT, or None."""
    end = closing(text, start)
    match = UNIT.match(text, end + 1) if end is not None else None
    return match.group(1).lower() if match else None


def pair_bands(incident):
    """(large, unnamed): how many of INCIDENT's misses through the pair, counted as misses() counts them (the Slice
    field's first, then each recurrence), name the large band or Critical in their parentheses, and name no band."""
    slice_text, recurrences = (incident.fields.get(label, "") for label in ("slice that should have caught it",
                                                                            "recurrences"))
    found = [(slice_text, match) for match in LOAD_NAMES[PAIR].finditer(slice_text)][:1] if (
        incident.slice == SLICES[2]) else []
    found += [(recurrences, match) for match in LOAD_NAMES[PAIR].finditer(recurrences)]
    inner = [text[match.start():closing(text, match.start()) or None] for text, match in found]
    return sum(1 for part in inner if LARGE.search(part)), sum(1 for part in inner if not BAND.search(part))


def unit_count(units):
    """How many review units UNITS (sha or None, one per miss) are: a miss that names none counts alone, and a short
    sha is the unit of a longer one it starts."""
    distinct = []
    for unit in sorted({unit for unit in units if unit}, key=len, reverse=True):
        if not any(other.startswith(unit) for other in distinct):
            distinct.append(unit)
    return len(distinct) + sum(1 for unit in units if not unit)


def tested(root, incident):
    """Whether INCIDENT is plugged with a distinct working test for each of its misses, so a recurrence through a
    reduced load adds a test to the Plug field (the earlier plug did not stop it)."""
    working = {test_key(root, plug) for plug in working_checks(root, incident) if plug.kind == "test"}
    return incident.status == "plugged" and len(working) >= max(1, len(misses(incident)))


def working_checks(root, incident):
    """The test and check plugs INCIDENT's Plug field names that work (plug_problem finds nothing), whatever its
    status."""
    plugs, _unread = parse_plug(incident.fields.get("plug", ""))
    return [plug for plug in plugs if plug.kind in ("test", "check") and plug_problem(root, plug, incident.id) is None]


def escalation_problems(root, incidents):
    """(problems, notes): a problem for each incident with a recurrence that has neither a working test or check plug
    nor a `(no check: <reason>)`; a note for every such reason."""
    problems, notes = [], []
    for incident in incidents:
        plug = incident.fields.get("plug", "")
        reason = no_check(plug)
        notes += ["%s: no check: %s" % (incident.id, reason)] if reason else []
        if has_recurrences(incident) and not reason and not working_checks(root, incident):
            problems.append("%s has a recurrence but no working test or check plug: add one that fails on the class "
                            "(shown failing before the fix), or end its Plug field with `(no check: <reason>)`%s"
                            % (incident.id, "; its `(no check: ...)` gives no reason in words" if
                               NO_CHECK.search(plug) else ""))
    return problems, notes




def failure_items(text):
    """[[item, line numbers]] for each bullet or numbered item of TEXT's "Failure looks like" section, which runs to
    the next level-1 or level-2 heading; an item's indented wrapped lines are joined to it."""
    items, inside = [], False
    for number, line in enumerate(unfenced(text)):
        if FAILURES.match(line) or SECTION_END.match(line):
            inside = bool(FAILURES.match(line))
        elif inside and ITEM.match(line):
            items.append([line.strip(), [number]])
        elif inside and items and items[-1][1][-1] == number - 1 and line.strip() and line[:1].isspace():
            items[-1] = [items[-1][0] + " " + line.strip(), items[-1][1] + [number]]
    return items


def suite_item_problem(root, item, by_id):
    """Why the "Failure looks like" ITEM marked (suite) is not backed by the suite, or None."""
    ids = list(dict.fromkeys(LINK.findall(item)))
    why = [] if ids else ["it links no [I<n>]"]
    why += ["%s is not in the log" % ident for ident in ids if ident not in by_id]
    why += ["%s has no working test or check plug" % ident for ident in ids
            if ident in by_id and not working_checks(root, by_id[ident])]
    why += ["%s is open" % ident for ident in ids if ident in by_id and by_id[ident].status != "plugged"]
    why += ["%s has a recurrence" % ident for ident in ids if ident in by_id and has_recurrences(by_id[ident])]
    return ("%s's \"Failure looks like\" line %r is marked (suite) but %s; reviewers would skip a class the suite "
            "does not hold" % (RULE_FILE, item, "; ".join(why))) if why else None


def suite_problems(root, incidents):
    """A problem for each (suite) mark, in any case, of REVIEW.md: on a "Failure looks like" item that links no
    incident, or one without a working test or check plug, or with a recurrence (its plug pinned an instance, not the
    class); and anywhere else."""
    try:
        text = read_text(os.path.join(root, RULE_FILE))
    except OSError:
        return []  # no REVIEW.md, no (suite) mark
    by_id = {incident.id: incident for incident in incidents}
    problems, covered = [], set()
    for item, numbers in failure_items(text):
        covered.update(numbers)
        problem = suite_item_problem(root, item, by_id) if SUITE.search(item) else None
        problems += [problem] if problem else []
    problems += ["%s line %d: (suite) outside a \"Failure looks like\" item; mark only those items" % (RULE_FILE,
                 number + 1) for number, line in enumerate(text.splitlines())
                 if SUITE.search(re.sub(r"`[^`]*`", "", line)) and number not in covered]  # `(suite)` is a mention
    return problems


def notices(root, log_text, today):
    """Notes that never change the exit code: one-sighting near misses older than STALE_DAYS in NEAR_MISSES, and
    `prune due` when the log's `Last pruned:` date is missing or older than STALE_DAYS."""
    near = near_misses_text(root)
    notes = ["%s is not a regular file inside the repo, so it was not read" % NEAR_MISSES] if near is None else []
    for line in unfenced(near or ""):
        sightings = [found.group(2) for found in SIGHTING.finditer(line) if not found.group(1)]
        if re.match(r"\s*[-*]\s", line) and not KEPT.search(line) and len(sightings) == 1 and (
                days_since(sightings[0], today) or 0) > STALE_DAYS:
            notes.append("%s: a one-sighting near miss over %d days old; delete it in your next commit: %s"
                         % (NEAR_MISSES, STALE_DAYS, line.strip()))
    pruned = LAST_PRUNED.search(log_text)
    age = days_since(pruned.group(1), today) if pruned else None
    if age is None or age > STALE_DAYS:
        notes.append("prune due: %s; read REVIEW.md, the log and %s, bring the pruning to the user at the next "
                     "go-ahead, then set `Last pruned: %s`" % (
                         "no readable `Last pruned: YYYY-MM-DD` line in the log" if age is None else
                         "last pruned %s, %d days ago (over %d)" % (pruned.group(1), age, STALE_DAYS),
                         NEAR_MISSES, today))
    return notes


def near_misses_text(root):
    """NEAR_MISSES's text under ROOT: "" when it is absent, None when it is no regular file inside ROOT (a link out of
    the repo, a pipe or a device) or cannot be read."""
    path = os.path.join(root, NEAR_MISSES)
    if not os.path.lexists(path):
        return ""
    try:
        return read_text(path) if os.path.isfile(path) and inside(root, path) else None
    except OSError:
        return None


def days_since(text, today):
    """Days from the YYYY-MM-DD date TEXT to TODAY, or None when TEXT is no date."""
    try:
        return (today - datetime.datetime.strptime(text, "%Y-%m-%d").date()).days
    except ValueError:
        return None


def test_key(root, plug):
    """What the working test PLUG resolves to, so one test spelled two ways (`./`, `Class.method` or the bare method)
    counts once: its file and the line its function starts on."""
    path = os.path.normpath(plug.path)
    if not path.endswith(".py"):
        return path, plug.names[-1]
    tree = ast.parse(read_text(os.path.join(root, path)), path)
    return path, find_function(tree, plug.names)[0].lineno


def review_settings(root):
    """(settings, error): the (key, value) lines of REVIEW.md's review-slices block, or why it cannot be read."""
    try:
        return block_settings(read_text(os.path.join(root, RULE_FILE))), None
    except OSError as error:
        return [], error.strerror or str(error)


def lines_needed(settings, load):
    """The lines of NEEDED[LOAD] the block SETTINGS lack (a band with no line is on: small by default)."""
    return [line for line in NEEDED[load] if tuple(part.strip() for part in line.partition(":")[::2]) not in settings]


def band_problems(root, incidents):
    """A problem for each reduced load that misses from two or more review units went through while one of their
    incidents lacks a test plug for each of its misses and REVIEW.md's block lacks a line NEEDED for that load."""
    settings, error = review_settings(root)
    problems = []
    for load in REDUCED_LOADS:
        pairs = [(incident, unit) for incident in incidents for found, unit in misses(incident) if found == load]
        through = [incident for incident, _unit in pairs]
        ids = list(dict.fromkeys(incident.id for incident in through))
        untested = list(dict.fromkeys(incident.id for incident in through if not tested(root, incident)))
        units = unit_count([unit for _incident, unit in pairs])
        missing = lines_needed(settings, load) if units > 1 and untested else []
        if missing:
            problems.append("%d misses went through the %s load (%s) and %s has no working test plug for each, so "
                            "%s's review-slices block needs %s until each has one%s"
                            % (len(through), load, ", ".join(ids), ", ".join(untested), RULE_FILE,
                               " and ".join("`%s`" % line for line in missing),
                               " (%s cannot be read: %s)" % (RULE_FILE, error) if error else ""))
    return problems


def miss_count(load, units, bands=(0, 0)):
    """`<load> <misses>`, the review units they came from where those are fewer, and, for the pair, how many named
    a large unit or Critical and how many named no band (the stop rule cannot see those)."""
    count = unit_count(units)
    notes = ["%d on a large or Critical unit: tell the user before the next one" % bands[0]] if bands[0] else []
    notes += ["%d name no band: add it" % bands[1]] if bands[1] else []
    return "%s %d%s%s" % (load, len(units), " in %d review unit(s)" % count if count < len(units) else "",
                          " (%s)" % "; ".join(notes) if notes else "")


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
    found = [miss for incident in incidents for miss in misses(incident)]
    if found:
        print("  misses through a reduced load, recurrences included: " + ", ".join(
            miss_count(load, [unit for named, unit in found if named == load],
                       [sum(part) for part in zip(*(pair_bands(incident) for incident in incidents))] if load == PAIR
                       else (0, 0))
            for load in REDUCED_LOADS))
    recurring = [incident for incident in incidents if has_recurrences(incident)]
    print("recurrences (each means a weak plug):" + ("" if recurring else " none"))
    for incident in recurring:
        print("  %s. %s: %s" % (incident.id, incident.title, recurrence_text(incident)))


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
    escalated, reasons = escalation_problems(root, incidents)
    problems += band_problems(root, incidents) + escalated + suite_problems(root, incidents)
    notes += reasons + notices(root, text, today)
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
    parser.add_argument("--check", action="store_true", help="exit 1 on any problem: a plug missing or unreadable, "
                        "a band that misses from a second review unit through a reduced load need off, a recurrence "
                        "with no working test or check plug or reason, or a (suite) line its incidents do not back")
    args = parser.parse_args(argv[1:])
    root = repo_root()
    try:
        return report(args.path or os.path.join(root, "docs", "INCIDENTS.md"), root, args.check)
    except IncidentError as error:
        print("incidents: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
