#!/bin/sh
set -eu
python -m ruff check .
python -m mypy src
python scripts/validate_repo.py
python -m unittest discover -s tests -v
node extension/tests/extractor_test.js
node extension/tests/injection_test.js
node extension/tests/transport_test.js
node extension/tests/detail_extractor_test.js
node extension/tests/detail_action_test.js
node extension/tests/options_test.js
node extension/tests/detail_batch_worker_test.js
node extension/tests/batch_controller_test.js
