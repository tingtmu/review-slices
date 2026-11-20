# Tool notes: bug-only fast checks

Optional guidance for [Set up a repo](set-up.md) step 1, for choosing the lint and type-check `test:` lines. Use it
when the repo has no lint or type-check setup of its own, or runs a tool on its defaults only. The repo's own config
always wins.

Agent-written code needs checks that catch bugs, not style. Among the bug patterns of LLM-written code,
[Tambon et al.](https://arxiv.org/abs/2403.08937) report hallucinated objects and wrong attributes;
[Liu et al.](https://arxiv.org/abs/2307.12596) report type mismatches and undefined variables among runtime errors,
and unused variables as a code smell.

## Principles

1. **Select bug rules explicitly.** Pick a linter's correctness rules: undefined and unused names, mutable
   defaults, swallowed or blind exceptions, misused async, leftover debugger calls. Leave out style, formatting,
   naming, docstring and modernisation rules. A formatter that rewrites files is never a `test:` line: it breaks
   the pass stamp.
2. **Never trust a tool's unconfigured default.** Write the selection into the repo's config, then check that the
   tool reads it. With no config, a tool may run mostly style rules, or check almost nothing and still exit 0.
3. **Add a type checker, even on untyped code.** It is the only cheap check that catches made-up attributes and
   wrong argument counts. On untyped code, turn off only the "possibly None" reports: they are most of the noise,
   while the argument-type report also catches real wrong-type calls.
4. **Keep the checks that catch suppressions:** unused, blanket and unexplained ignore comments. Agents route
   around a check by silencing it. The adversarial brief's lens 5 flags a new suppression that gives no reason.
5. **Turn a rule on instead of off.** Where code already does what a rule asks for, make it explicit (for example,
   pass an argument's default value) rather than ignoring the rule. The rule exists for the next call, the one that
   does not do it.
6. **Give agents no complexity or coverage thresholds.** An agent will game the number
   ([Pstrucha, "Stop Prompting"](https://finance.biggo.com/podcast/6e17bccdea629159)).
7. **The commit hook previews the suite:**
   - It runs the same command as the suite's `test:` line on the whole tree (no per-file arguments). The hook
     tools set unstaged edits aside first, and untracked files are linted, as the pass stamp includes them.
   - Neither command may fix files: pass every flag that turns the linter's fix modes off, since a fix setting in
     the config makes the check rewrite files and pass. As a backstop, the hook tools fail a hook that modifies
     files, and `run-suite` writes no stamp when a file changes during the run.
   - The config, the hook and the `test:` line go in, and come out, together: the command left behind after its
     config is removed runs the tool's defaults.
   - It also triggers on every file that holds the tool's config (a shared one such as `pyproject.toml` too), so a
     config-only commit with a bad rule name fails.
   - It is installed so that it passes where the config does not exist yet (older branches).

## Tested examples

Measured 2026-11-19 on this skill's own repo and on an untyped file seeded with 13 bugs, 12 of them visible to a
static check (the 13th is a bad keyword passed through `**kwargs`). Re-check on newer versions.

**Python: ruff 0.17.5.**
- Its default (about 400 rules since 0.16) gave 382 findings here, 308 of them `UP031` (old-style `%`
  formatting).
- This bug-only selection gave 38 findings: 37 from PLW1510, each made explicit with `check=False`, and 1 unused
  `noqa`:
  ```
  [lint]
  select = ["F", "E9", "B", "PLE", "BLE001", "S110", "S112", "ASYNC", "T100", "PGH003", "PGH004", "RUF006",
            "RUF008", "RUF009", "RUF012", "RUF016", "RUF018", "RUF024", "RUF100", "PLW0177", "PLW1508", "PLW1510"]
  ignore = ["B008", "B028", "B905"]
  ```
- The style families it leaves out: UP, SIM, C4, I, E/W (except E9), N, D, ANN, FURB, PERF, TRY, RET, PTH.

**Python: type checkers.**
- pyright 1.1.413 in standard mode caught all 12 visible seeded bugs with no config, and 57 findings on this
  skill's scripts. With `reportOptionalMemberAccess`, `reportOptionalSubscript` and `reportOptionalOperand` off, it
  caught 10 and the scripts gave 32. Also turning off `reportArgumentType` cut the scripts to 15, all its hits
  there being `X | None` arguments, but lost the seeded `len(5)`: keep it on.
- pyrefly 1.5.0 with no config falls back to its `basic` preset and caught none of them. With `preset = "default"`
  it caught all 12. It reports "possibly None" under the same error kind as a truly missing attribute, so that noise
  cannot be turned off on its own.

**R.**
- Jarl 0.7.1: `jarl check --select CORR,SUSP,COMM .` runs its correctness, suspicious-code and
  suppression-comment groups. Leave out READ and PERF. CORR also turns on `unused_object`, which flags
  script-level variables.
- Air 0.13.0 is a formatter only.

**Commit hook: prek 0.5.11 (pre-commit-compatible config).**
- A local hook with `entry: ruff check --no-fix --no-fix-only .`, `pass_filenames: false` and
  `files: '(\.pyi?|\.ipynb|(^|/)(\.?ruff\.toml|pyproject\.toml)|^\.pre-commit-config\.yaml)$'`.
- With `fix = true` in ruff.toml, `ruff check .` deleted an unused import and exited 0; `--no-fix` reported it and
  exited 1. With `fix-only = true`, `--no-fix` alone still deleted it and exited 0; `--no-fix --no-fix-only`
  reported it and exited 1. prek failed that hook: "files were modified by this hook".
- Installed with `prek install --allow-missing-config`. A plain install blocked every commit on a branch from
  before the config file.

## Not measured here

From the tools' own docs, not run in this repo:
- mypy skips functions that have no annotations unless given `--check-untyped-defs`.
- JS/TS: `tsc --noEmit` plus typescript-eslint's `recommended-type-checked` config, not `stylistic`.
- Go: `go vet` plus staticcheck's SA checks, not ST.
- Shell: `shellcheck -S warning`.
