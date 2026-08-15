# Change control

Routine implementation, tests, CI, fixtures, and internal refactors within M0 do
not require a change request or human approval.

A change request is required for a material SSOT meaning change, breaking stored
data contract, agent boundary change, or expansion beyond the active milestone.
Use `spec/contracts/change-request.schema.json` and store approved records under
`spec/change_requests/`.

Human approval is required only when the change also triggers HG-01 or HG-02 in
`HUMAN_GATES.md`.
