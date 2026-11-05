#!/bin/sh
# Desktop half tests: node's built-in runner, no npm install. The three SDK specifiers resolve to tests/js/stubs.
cd "$(dirname "$0")/.." && exec node --import ./tests/js/register.mjs --test "tests/js/*.test.mjs" "$@"
