"""review-slices discover sources: find the checks a repo already has, for discover.py.

Each *_candidates(root) function reads one kind of file with line-based parsing (there is no YAML library) and
returns Candidates. A CI step is a remote check whenever anything hints that it needs secrets, an environment,
services, another OS or CI values, or that it deploys or publishes: discover.py --run runs every local one.
Standard library only, Python 3.8+.
"""
import collections
import importlib.util
import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# remote: "" for a local candidate, else why it is a remote check; legs: other OSes a local CI step also runs on.
Candidate = collections.namedtuple("Candidate", "source line kind command remote legs")
KINDS = (("format", r"format|fmt|black|prettier|isort"),
         ("types", r"mypy|pyright|tsc|typecheck|type-check|types"),
         ("lint", r"lint|ruff|flake8|pylint|eslint|clippy|vet|pre-commit|golangci-lint|shellcheck"),
         ("test", r"test|tests|pytest|unittest|jest|vitest|mocha|tox|nox|ctest|rspec"),
         ("build", r"build|compile"))
KIND_PATTERNS = [(kind, re.compile(r"(?<![\w-])(?:%s)(?![\w-])" % words, re.I)) for kind, words in KINDS]
SECRET = re.compile(r"\$\{\{[^}]*\bsecrets\b")  # secrets.X, secrets['X'], toJSON(secrets)
# Words that mark a deploy or a publish, even inside a name such as deploy-prod, gh-pages or semantic-release.
DEPLOY = re.compile(r"(?<![A-Za-z0-9])(deploy[a-z]*|publish[a-z]*|release[a-z]*|push|ship|twine|kubectl|"
                    r"helm|terraform|gcloud|aws|az|gh|rsync|scp|sftp|ssh)(?![A-Za-z0-9])", re.I)
# Coverage and report uploads, which need the network and usually a token.
UPLOAD = re.compile(r"(?<![A-Za-z0-9])(upload[a-z]*|codecov|coveralls|codacy|codeclimate|cc-test-reporter|deepsource|"
                    r"sonar[a-z-]*|report-coverage)(?![A-Za-z0-9])", re.I)
# The one flag dropped before DEPLOY, so `cargo build --release` stays local; --push and --publish still count.
RELEASE_FLAG = re.compile(r"(?:^|\s)--release(?=\s|$)")
# A CI expression, or an environment variable a local shell would not have set.
CI_VALUES = re.compile(r"\$\{\{|\$\{?(?!(?:HOME|PWD|PATH|USER|TMPDIR)\b)[A-Z_][A-Z0-9_]*")
WORKDIR = re.compile(r"^\s*working-directory:\s*(.+)$", re.M)
# Lines of a CI script that prepare the machine rather than check the code.
SETUP = re.compile(r"(sudo|apt(-get)?|brew|choco|pipx|rustup|echo|printf|export|set|source|\.|curl|wget|git|mkdir|"
                   r"cp|mv|rm|chmod|cat|ls|pwd|if|then|else|elif|fi|for|while|do|done|case|esac)(\s|$)|"
                   r"((python3?|py) -m )?pip3? install|(npm|pnpm|bun|poetry) (ci|install)|yarn( install\b.*)?$|"
                   r"uv (sync|pip|venv|tool)|go (install|mod download)|[A-Za-z_][A-Za-z0-9_]*=\S*$")
NPM_SCRIPTS = {"test": "test", "lint": "lint", "typecheck": "types", "type-check": "types", "check": None,
               "build": "build", "format:check": "format"}
LOCKFILES = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"), ("bun.lock", "bun"))
TARGETS = {"test": "test", "lint": "lint", "check": "other", "typecheck": "types", "build": "build"}
MAKEFILES = (("GNUmakefile", "make"), ("makefile", "make"), ("Makefile", "make"),
             ("justfile", "just"), ("Justfile", "just"), (".justfile", "just"))
MAKE_TARGET = re.compile(r"([^\s:#=][^:#=]*?)\s*::?(?!=)")
JUST_RECIPE = re.compile(r"@?([A-Za-z_][\w-]*)(?:\s+[^:]*)?:(?!=)")
PY_TOOLS = (("pytest", "pytest"), ("ruff", "ruff check ."), ("mypy", "mypy ."), ("black", "black --check ."))
FIXED = (("tox.ini", ("tox",)), ("noxfile.py", ("nox",)), (".pre-commit-config.yaml", ("pre-commit run --all-files",)),
         ("Cargo.toml", ("cargo test", "cargo clippy -- -D warnings")), ("go.mod", ("go test ./...", "go vet ./...")))
CONTRIBUTING = ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md")
SHELL_FENCES = ("", "sh", "bash", "shell", "zsh", "console", "shell-session")
OS_PREFIXES = (("ubuntu", "linux"), ("linux", "linux"), ("macos", "macos"), ("darwin", "macos"), ("win", "windows"),
               ("cygwin", "windows"))
GITLAB_KEYWORDS = {"stages", "variables", "default", "include", "workflow", "image", "services", "before_script",
                   "after_script", "cache"}


def load_guard():
    spec = importlib.util.spec_from_file_location("review_slices", os.path.join(HERE, "review_slices.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_guard()


def note(message):
    print("note: " + message, file=sys.stderr)


def read_lines(root, rel):
    """[(number, text)] of REL in ROOT; [] when it does not exist."""
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as handle:
            return list(enumerate(handle.read().splitlines(), 1))
    except FileNotFoundError:
        return []
    except OSError as error:
        note("could not read %s, so it was skipped: %s" % (rel, error))
        return []


def kind_of(command):
    return next((kind for kind, pattern in KIND_PATTERNS if pattern.search(command)), "other")


def indent(text):
    return len(text) - len(text.lstrip())


def scalar(value):
    """A YAML scalar's text: quotes removed, or a plain scalar's trailing comment."""
    value = value.strip()
    if value[:1] in ("'", '"') and value.rfind(value[0]) > 0:
        return value[1:value.rfind(value[0])].replace("''", "'" if value[0] == "'" else "''")
    return guard.COMMENT.sub("", value).strip()


def field(fields, key):
    """The scalar value of KEY in FIELDS, from keys(); "" when absent."""
    return scalar(fields.get(key, (0, ""))[1])


def labels(value):
    """The items of a YAML flow list or a scalar, such as `[ubuntu-latest, macos-latest]`."""
    return [scalar(item) for item in value.strip().strip("[]").split(",") if item.strip()]


def key_col(block):
    first = block[0][1]
    if first.strip() == "-" and len(block) > 1:
        return indent(block[1][1])
    return re.match(r"\s*(?:-\s+)?", first).end()


def keys(block):
    """{key: (index, value)} for the keys of the YAML mapping BLOCK, whose first line may start with '- '."""
    found = {}
    if not block:
        return found
    col = key_col(block)
    for index, (_number, text) in enumerate(block):
        match = re.match(r"\s*(?:-\s+)?([\w.-]+):(?:\s+(.*))?$", text)
        if match and (index == 0 or indent(text) == col) and match.group(1) not in found:
            found[match.group(1)] = (index, (match.group(2) or "").strip())
    return found


def nested(block, index, col):
    """The lines after BLOCK[INDEX] that are indented deeper than COL."""
    lines = []
    for number, text in block[index + 1:]:
        if indent(text) <= col:
            break
        lines.append((number, text))
    return lines


def chained(text):
    """The commands of the shell line TEXT, split at each `&&` and `;` outside quotes and parentheses; splitting
    stops at a comment."""
    parts, start, quote, depth, index = [], 0, None, 0, 0
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            quote = None if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or text[index - 1].isspace()):
            break
        elif char in "()":
            depth = max(depth + (1 if char == "(" else -1), 0)
        elif depth == 0 and (char == ";" or text.startswith("&&", index)):
            parts.append(text[start:index])
            start = index + (1 if char == ";" else 2)
            index = start
            continue
        index += 1
    return [part.strip() for part in parts + [text[start:]] if part.strip()]


def shell_commands(lines, prefix=""):
    """[(number, command)] of the shell LINES worth checking: `\\` continuations joined, setup commands dropped,
    also from a chain (`pip install ruff && ruff check .`), and each `cd DIR` carried into the commands after it."""
    commands, held = [], None
    for number, text in lines:
        text = text.strip()
        if held:
            number, text = held[0], held[1] + " " + text
        held = (number, text[:-1].rstrip()) if text.endswith("\\") else None
        if held or not text or text.startswith("#"):
            continue
        start, kept = prefix, []
        for part in chained(text):
            cd = re.match(r"cd\s+(\S+)$", part)
            prefix += "cd %s && " % cd.group(1) if cd else ""
            if cd and not kept:
                start = prefix
            elif cd or not SETUP.match(part):
                kept.append(part)
        if kept:
            commands.append((number, start + " && ".join(kept)))
    return commands


def yaml_lines(root, rel):
    return [(number, text.rstrip()) for number, text in read_lines(root, rel)
            if text.strip() and not text.strip().startswith("#")]


def split_jobs(lines):
    """A GitHub workflow's LINES as (top, jobs): the lines outside `jobs:`, and per job (header, steps), where
    header holds the job's lines outside `steps:` and each step is a list of lines."""
    top, jobs, in_jobs, job_col = [], [], False, None
    for number, text in lines:
        col, stripped = indent(text), text.strip()
        if col == 0:
            in_jobs, job_col = stripped.startswith("jobs:"), None
        if not in_jobs:
            top.append((number, text))
        elif col > 0 and (job_col is None or col <= job_col):
            job_col, fields, in_steps, dash = col, None, False, None
            jobs.append(([(number, text)], []))
        elif col > 0:
            header, steps = jobs[-1]
            fields = col if fields is None else fields
            if in_steps and (col > fields or (col == fields and stripped.startswith("-"))):
                if stripped.startswith("-") and dash in (None, col):
                    dash = col
                    steps.append([])
                if steps:
                    steps[-1].append((number, text))
                continue
            in_steps, dash = col == fields and guard.COMMENT.sub("", stripped).strip() == "steps:", None
            header.append((number, text))
    return top, jobs


def os_of(label):
    """The OS of a runner label such as ubuntu-latest, or of a sys.platform value; None when unknown."""
    return next((name for prefix, name in OS_PREFIXES if label.lower().startswith(prefix)), None)


def matrix_labels(header, key):
    """The runner labels under a job's matrix KEY, inline or as a list."""
    found, col = [], None
    for _number, text in header:
        match = re.match(r"\s*(?:-\s+)?%s:\s*(.*)$" % re.escape(key), text)
        if match:
            found, col = found + labels(match.group(1)), indent(text)
        elif col is not None and indent(text) > col and text.strip().startswith("-"):
            found.append(scalar(text.strip()[1:]))
        else:
            col = None
    return found


def job_os(header, fields):
    """(reason, legs): why the job is remote by its runners' OS, and the other OSes it also runs on."""
    runs_on, here = fields.get("runs-on", (0, ""))[1], os_of(sys.platform)
    key = re.search(r"matrix\.([\w-]+)", runs_on)
    found = matrix_labels(header, key.group(1) if key else "os") if key or not runs_on else labels(runs_on)
    oses = {os_of(label) for label in found} - {None}
    if not oses or here is None:
        return "", []
    if here not in oses:
        return "runs only on %s" % ", ".join(sorted(oses)), []
    return "", sorted(oses - {here})


def run_lines(value, number, following):
    """[(number, line)] of a `run:` VALUE on line NUMBER, whose nested lines are FOLLOWING."""
    if value[:1] == "|":
        return following
    if value[:1] == ">":
        return [(following[0][0], " ".join(text.strip() for _number, text in following))] if following else []
    return [(number, " ".join([scalar(value)] + [text.strip() for _number, text in following]))]


def deploy_reason(*texts):
    """Why TEXTS (a command, a script or recipe body, the names around it) upload, deploy or publish; "" if not."""
    text = RELEASE_FLAG.sub(" ", " ".join(texts))
    upload, deploy = UPLOAD.search(text), DEPLOY.search(text)
    if upload:
        return "uploads to a service (%s)" % upload.group(1)
    return "deploys or publishes (%s)" % deploy.group(1) if deploy else ""


def command_reason(command, *names):
    """Why COMMAND, in the jobs or steps called NAMES, is a remote check; "" when nothing says so."""
    reason = deploy_reason(*(names + (command,)))
    return reason or ("needs CI values or variables" if CI_VALUES.search(command) else "")


def step_reason(fields, command, job):
    shell = field(fields, "shell")
    if shell in ("pwsh", "powershell", "cmd") and os_of(sys.platform) != "windows":
        return "uses the %s shell" % shell
    return command_reason(command, job, field(fields, "name"))


def job_candidates(rel, top, header, steps):
    """Candidates of one job. Anything that hints at secrets, an environment or services makes the whole job
    remote: a secret can reach every step (through $GITHUB_ENV, for one), and --run must never deploy."""
    fields = keys(header[1:])
    whole = "\n".join(text for _number, text in top + header + [line for step in steps for line in step])
    os_reason, legs = job_os(header, fields)
    reason = ("its job uses secrets" if SECRET.search(whole) else
              "its job deploys to an environment" if "environment" in fields else
              "its job needs services" if "services" in fields else os_reason)
    job = header[0][1].strip().rstrip(":") + " " + field(fields, "name")
    workdir = (WORKDIR.search("\n".join(text for _number, text in header))
               or WORKDIR.search("\n".join(text for _number, text in top)))
    found = []
    for step in steps:
        step_fields = keys(step)
        if "run" not in step_fields:
            continue
        index, value = step_fields["run"]
        where = field(step_fields, "working-directory") or (scalar(workdir.group(1)) if workdir else "")
        lines = run_lines(value, step[index][0], nested(step, index, key_col(step)))
        for number, command in shell_commands(lines, "cd %s && " % shlex.quote(where) if where else ""):
            why = reason or step_reason(step_fields, command, job)
            found.append(Candidate(rel, number, kind_of(command), command, why, [] if why else legs))
    return found


def workflow_candidates(root):
    folder, found = os.path.join(root, ".github", "workflows"), []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith((".yml", ".yaml")):
            rel = ".github/workflows/" + name
            top, jobs = split_jobs(yaml_lines(root, rel))
            for header, steps in jobs:
                found += job_candidates(rel, top, header, steps)
    return found


def list_items(lines):
    """[(number, text)] of a YAML block list, with `- |` items expanded line by line."""
    items, col = [], None
    for number, text in lines:
        stripped = text.strip()
        if stripped.startswith("-") and (col is None or indent(text) <= col):
            col, value = indent(text), stripped[1:].strip()
            if value and value[0] not in "|>":
                items.append((number, scalar(value)))
        else:
            items.append((number, stripped))
    return items


def gitlab_candidates(root):
    rel, blocks = ".gitlab-ci.yml", []
    for number, text in yaml_lines(root, rel):
        if indent(text) == 0:
            blocks.append((text.split(":", 1)[0].strip(), []))
        elif blocks:
            blocks[-1][1].append((number, text))
    shared = "services" in [name for name, _body in blocks]
    found = []
    for name, body in blocks:
        fields = keys(body)
        if name in GITLAB_KEYWORDS or name.startswith(".") or "script" not in fields:
            continue  # a keyword, or a hidden job, which GitLab never runs
        index, value = fields["script"]
        reason = ("its job needs services" if shared or "services" in fields else
                  "its job deploys to an environment" if "environment" in fields else "")
        following = nested(body, index, key_col(body))
        if value.startswith("["):
            lines = [(body[index][0], item) for item in labels(value)]
        else:
            lines = run_lines(value, body[index][0], following) if value else list_items(following)
        for number, command in shell_commands(lines):
            why = reason or command_reason(command, name, field(fields, "stage"))
            found.append(Candidate(rel, number, kind_of(command), command, why, []))
    return found


def package_candidates(root):
    lines = read_lines(root, "package.json")
    try:
        data = json.loads("\n".join(text for _number, text in lines)) if lines else {}
    except ValueError as error:
        note("package.json is not valid JSON, so it was skipped: %s" % error)
        return []
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return []
    runner = next((tool for lock, tool in LOCKFILES if os.path.exists(os.path.join(root, lock))), "npm")
    start = next((number for number, text in lines if '"scripts"' in text), 0)
    found = []
    for name, body in scripts.items():
        if name in NPM_SCRIPTS and isinstance(body, str):
            pattern = re.compile(r'"%s"\s*:' % re.escape(name))
            number = next((n for n, text in lines if n >= start and pattern.search(text)), start or 1)
            # `run test` also runs pretest and posttest, so a publish in either makes it remote.
            hooks = [scripts.get(prefix + name) for prefix in ("pre", "", "post")]
            reason = command_reason(" && ".join(hook for hook in hooks if isinstance(hook, str)), name)
            found.append(Candidate("package.json", number, NPM_SCRIPTS[name] or kind_of(body),
                                   "%s run %s" % (runner, name), reason, []))
    return found


def recipe(lines, index):
    """The target or recipe on LINES[INDEX]: that line, with its prerequisites, and the indented lines under it."""
    body = [lines[index][1]]
    for _number, text in lines[index + 1:]:
        if text.strip() and not text[:1].isspace():
            break
        body.append(text)
    return "\n".join(body)


def target_candidates(root):
    present, tools, found = set(os.listdir(root)), set(), []
    for name, tool in MAKEFILES:
        if name not in present or tool in tools:
            continue
        tools.add(tool)
        pattern, done, lines = MAKE_TARGET if tool == "make" else JUST_RECIPE, set(), read_lines(root, name)
        for index, (number, text) in enumerate(lines):
            match = pattern.match(text)
            for target in match.group(1).split() if match else []:
                if target in TARGETS and target not in done:
                    done.add(target)  # Make's and just's own ${VARIABLES} are not CI values, so only deploys count
                    found.append(Candidate(name, number, TARGETS[target], "%s %s" % (tool, target),
                                           deploy_reason(recipe(lines, index)), []))
    return found


def pyproject_candidates(root):
    runner = next((prefix for lock, prefix in (("uv.lock", "uv run "), ("poetry.lock", "poetry run "))
                   if os.path.exists(os.path.join(root, lock))), "")
    found, done = [], set()
    for number, text in read_lines(root, "pyproject.toml"):
        match = re.match(r"\s*\[tool\.([\w-]+)[\].]", text)
        for tool, command in PY_TOOLS:
            if match and match.group(1) == tool and tool not in done:
                done.add(tool)
                found.append(Candidate("pyproject.toml", number, kind_of(command), runner + command, "", []))
    return found


def fixed_candidates(root):
    return [Candidate(name, 1, kind_of(command), command, "", [])
            for name, commands in FIXED if os.path.isfile(os.path.join(root, name)) for command in commands]


def fence_commands(fence, lines):
    """The commands of one fenced block: every line, or only the `$ ` lines of a console session."""
    console = fence in ("console", "shell-session")
    picked = []
    for number, text in lines:
        prompt = re.match(r"\s*[$%] (.*)$", text)
        if prompt or not console:
            picked.append((number, prompt.group(1) if prompt else text))
    return [(number, command) for number, command in shell_commands(picked)
            if re.search(r"test|lint|check", command, re.I)]


def contributing_candidates(root):
    found = []
    for rel in CONTRIBUTING:
        fence, lang, lines = None, "", []
        for number, text in read_lines(root, rel):
            match = re.match(r"\s*(`{3,}|~{3,})\s*([\w-]*)", text)
            if fence is None and match:
                fence, lang, lines = match.group(1), match.group(2).lower(), []
            elif fence and text.strip().startswith(fence) and not text.strip().strip(fence[0]):
                if lang in SHELL_FENCES:
                    found += [Candidate(rel, n, kind_of(command), command, command_reason(command), [])
                              for n, command in fence_commands(lang, lines)]
                fence = None
            elif fence:
                lines.append((number, text))
    return found


SOURCES = (workflow_candidates, gitlab_candidates, package_candidates, target_candidates, pyproject_candidates,
           fixed_candidates, contributing_candidates)
