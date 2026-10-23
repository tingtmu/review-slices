# Review meeting

A decision meeting limited to disputed review findings at Critical level. It needs Orca's
[`orca-cli`](https://github.com/stablyai/orca/blob/main/skills/orca-cli/SKILL.md) and
[`orchestration`](https://github.com/stablyai/orca/blob/main/skills/orchestration/SKILL.md) skills, a running Orca
app, and terminals the user opens. Without Orca, a disputed Critical review finding goes to the user.

Never start one on your own. Propose it to the user first:

```
Review meeting proposal
Disputed review findings: <ID, one line each, with both positions>
Why it is critical:   <the one-way door at stake>
Members and lenses:   <for example 2 Claude + 3 Codex; correctness, security, adversarial>
Rounds:               2 (a third only for a split or a blocking objection)
Cost:                 about <N> agent sessions, <minutes>
Folder:               .agents/review-meetings/<topic>-<date>/
Go ahead? (yes / no / change)
```

The meeting's folder holds its briefs, positions and decision. Keep it out of commits unless the user asks; add
`.agents/review-meetings/` to `.gitignore` the first time.
