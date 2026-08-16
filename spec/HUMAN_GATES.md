# Human Gates

Human approval is not required for routine implementation, tests, fixtures,
internal refactoring, or CI changes within the active approved milestone scope.

## HG-01 External credentials

Required when a live test needs Threads, Meta, OpenAI, or another external
credential. Credentials must be supplied through environment variables and must
never be committed.

## HG-02 External cost, legal, or irreversible risk

Required before a new paid service, material terms-of-service judgment, bulk
access, destructive operation, external publication, deployment, or push.

Uncertainty alone is not a gate: record it as `UNKNOWN` and continue with work
that does not depend on it.

## HG-03 Interactive browser verification

Required before loading the unpacked extension into the user's browser, reading
the user's signed-in Threads page, or performing live human-selected collection
and detail enrichment. The user performs login and selection. The implementation
must never request, inspect or persist browser credentials, cookies or tokens.

## HG-04 Viral Pattern quality review

Required after the first local `VIRAL_PATTERN_REPORT` over an approved frozen
dataset. A human reviewer decides whether the abstract Pattern Intelligence is
useful and not over-generalized. This gate does not authorize content
generation, publication, or an inference that a Pattern causes performance.
