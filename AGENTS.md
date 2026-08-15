# Social Content Engine Agent Guide

`spec/` is the source of truth. Before changing code, read `spec/README.md`, the
active milestone, and the applicable contract.

## Current scope

- Active milestone: M0 (`spec/MILESTONES.md`)
- Priority: obtain and preserve one real public Threads API response.
- Forbidden before M0: content generation, auto-posting, Fortune Engine
  integration, dashboards, and production deployment.

## Working rules

- Do not invent API capabilities or data. Use `UNKNOWN` or `UNSPECIFIED`.
- Preserve raw API responses and provenance; normalized records are derived.
- Never commit credentials, access tokens, or raw `.env` files.
- Routine implementation proceeds through tests and review without a human gate.
- Stop only for a gate defined in `spec/HUMAN_GATES.md`.
- Agent ownership and path boundaries are defined in `spec/AGENT_REGISTRY.json`.
- Material scope or contract changes require a change record under
  `spec/change_requests/`.

## Required verification

Run `python -m unittest discover -s tests -v` and
`python scripts/validate_repo.py` before declaring work complete.
