# Human Gates

Human approval is not required for routine implementation, tests, fixtures,
internal refactoring, or CI changes within the approved M0 scope.

## HG-01 External credentials

Required when a live test needs Threads, Meta, OpenAI, or another external
credential. Credentials must be supplied through environment variables and must
never be committed.

## HG-02 External cost, legal, or irreversible risk

Required before a new paid service, material terms-of-service judgment, bulk
access, destructive operation, external publication, deployment, or push.

Uncertainty alone is not a gate: record it as `UNKNOWN` and continue with work
that does not depend on it.
