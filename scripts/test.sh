#!/bin/sh
# Runs the suite with a clean Python path (Hermes sessions export PYTHONPATH).
cd "$(dirname "$0")/.." && exec env -u PYTHONPATH .venv/bin/python -m pytest -c tests/pytest.ini tests "$@"
