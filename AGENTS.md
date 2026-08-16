# Social Content Engine Agent Guide

`spec/` is the source of truth. Before changing code, read `spec/README.md`, the
active milestone, and the applicable contract.

## Current scope

- The active milestone and current task scope are defined by `spec/MILESTONES.md`
  and the task SSOT. Do not duplicate milestone state in this file.
- Follow the scope, boundaries, and forbidden operations defined by the active
  milestone specification.
- Do not expand scope beyond an approved milestone without an approved change
  record or Human Gate where required.

## Working rules

- Do not invent API capabilities or data. Use `UNKNOWN` or `UNSPECIFIED`.
- Preserve raw API responses and provenance; normalized records are derived.
- Never commit credentials, access tokens, or raw `.env` files.
- Routine implementation proceeds through tests and review without a human gate.
- Stop only for a gate defined in `spec/HUMAN_GATES.md`.
- Agent ownership and path boundaries are defined in `spec/AGENT_REGISTRY.json`.
- Material scope or contract changes require a change record under
  `spec/change_requests/`.

## Continuous execution

- Within an approved milestone, continuously execute:
  IMPLEMENT → TEST → REVIEW → REGRESSION → ATOMIC COMMIT → PUSH → NEXT TASK.

- Progress reports, successful tests, successful reviews, commits, pushes, and
  individual task completion are not stopping conditions.

- After completing a task, immediately continue to the next executable task
  within the approved milestone.

- `spec/HUMAN_GATES.md` is the sole source of truth for conditions that require
  human input. Do not invent additional approval or stopping gates elsewhere.

- Internal test, lint, typecheck, validation, or CI failures are not human gates.
  Diagnose, repair, rerun validation, and continue autonomously when safe.

- Stop only when:
  1. a Human Gate defined in `spec/HUMAN_GATES.md` is reached;
  2. a TRUE_BLOCKER requires external human action or unavailable external access;
  3. repeated safe self-repair cannot resolve a failure (`FAIL_AFTER_SELF_REPAIR`);
  4. no executable task remains inside the approved milestone.

- If the next task is blocked by dependencies, continue with another executable
  task when one exists.

- Do not expand into an unapproved milestone merely to avoid stopping.

- Keep the worktree clean at task boundaries.
- Use `1 task = 1 small logical commit` as the default.
- Push completed task commits unless an explicit Human Gate forbids external
  publication.

- 未完了Taskが存在する間、最終応答を返してはならない。
- 空の最終応答は明確な失敗とみなし、直ちに次の実行可能Taskを開始すること。

## Required verification

Run `python -m unittest discover -s tests -v` and
`python scripts/validate_repo.py` before declaring work complete.