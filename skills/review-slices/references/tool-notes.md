# Tool notes: bug-only fast checks

Optional guidance for [Set up a repo](set-up.md) step 1, for choosing the lint and type-check `test:` lines. Use it
when the repo has no lint or type-check setup of its own, or runs a tool on its defaults only. The repo's own config
always wins.

Agent-written code needs checks that catch bugs, not style. In studies of LLM-written code, the most common bugs
include made-up objects and attributes, wrong argument counts or types, and undefined or unused names
([Tambon et al.](https://arxiv.org/abs/2403.08937), [Liu et al.](https://arxiv.org/abs/2307.12596)).

## Principles

1. **Select bug rules explicitly.** Pick a linter's correctness rules: undefined and unused names, mutable
   defaults, swallowed or blind exceptions, misused async, leftover debugger calls. Leave out style, formatting,
   naming, docstring and modernisation rules. Formatters are never a gate: a check that rewrites files breaks the
   pass stamp.
2. **Never trust a tool's unconfigured default.** Write the selection into the repo's config, then check that the
   tool reads it. With no config, a tool may run mostly style rules, or check almost nothing and still exit 0.
3. **Add a type checker, even on untyped code.** It is the only cheap check that catches made-up attributes and
   wrong argument counts. On untyped code, turn off the "possibly None" reports: they are most of the noise.
4. **Keep the checks that catch suppressions:** unused, blanket and unexplained ignore comments. Agents route
   around a check by silencing it. The adversarial brief's lens 5 flags a new suppression that gives no reason.
5. **Turn a rule on instead of off.** Where code already does what a rule asks for, make it explicit (for example,
   pass an argument's default value) rather than ignoring the rule. The rule exists for the next call, the one that
   does not do it.
6. **Give agents no complexity or coverage thresholds.** An agent will game the number
   ([Pstrucha, "Stop Prompting"](https://finance.biggo.com/podcast/6e17bccdea629159)).
7. **The commit hook previews the gate:**
   - It runs the same command as the suite's `test:` line, on the same tree (no per-file arguments).
   - It also triggers on the tool's own config files, so a config-only commit with a bad rule name fails.
   - It is installed so that it passes where the config does not exist yet (older branches).

## Tested examples

Measured 2026-11-19 on this skill's own repo and on a file seeded with 12 bugs. Re-check on newer versions.

**Python: ruff 0.17.5.**
- Its default (about 400 rules since 0.16) gave 382 findings here, 308 of them `UP031` (old-style `%`
  formatting).
- This bug-only selection gave 38 findings: 37 from PLW1510, each made explicit with `check=False`, and 1 unused
  `noqa`:
  ```
  select = ["F", "E9", "B", "PLE", "BLE001", "S110", "S112", "ASYNC", "T100", "PGH003", "PGH004", "RUF006",
            "RUF008", "RUF009", "RUF012", "RUF016", "RUF018", "RUF024", "RUF100", "PLW0177", "PLW1508", "PLW1510"]
  ignore = ["B008", "B028", "B905"]
  ```
- The style families it leaves out: UP, SIM, C4, I, E/W (except E9), N, D, ANN, FURB, PERF, TRY, RET, PTH.

**Python: type checkers.**
- pyright 1.1.413 in standard mode caught 12 of 12 seeded bugs with no config. With `reportOptionalMemberAccess`,
  `reportOptionalSubscript`, `reportOptionalOperand` and `reportArgumentType` off, it caught 9 of 12, and its
  findings on this repo fell from 57 to 11.
- pyrefly 1.5.0 with no config falls back to its `basic` preset and caught 0 of 12. With `preset = "default"` it
  caught 12 of 12. It reports "possibly None" under the same error kind as a truly missing attribute, so that noise
  cannot be turned off on its own.
- mypy skips functions that have no annotations unless given `--check-untyped-defs`.

**R.**
- Jarl 0.7.1: `jarl check --select CORR,SUSP,COMM .` runs its correctness, suspicious-code and
  suppression-comment groups. Leave out READ and PERF. CORR also turns on `unused_object`, which flags
  script-level variables.
- Air 0.13.0 is a formatter only.

**Other languages (not measured here):**
- JS/TS: `tsc --noEmit` plus typescript-eslint's `recommended-type-checked` config, not `stylistic`.
- Go: `go vet` plus staticcheck's SA checks, not ST.
- Shell: `shellcheck -S warning`.

**Commit hook: prek 0.5.11 (pre-commit-compatible config).**
- A local hook with `entry: ruff check .`, `pass_filenames: false` and
  `files: '(\.py|^ruff\.toml|^\.pre-commit-config\.yaml)$'`.
- Installed with `prek install --allow-missing-config`. A plain install blocked every commit on a branch from
  before the config file.
