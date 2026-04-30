#!/usr/bin/env bash
set -euo pipefail

# Ensure the script runs from the project directory so .env is loaded correctly.
cd "$(dirname "$0")"

# Use the virtualenv Python interpreter directly.
.venv/bin/python bt-etmd-tndrs.py >> "$(pwd)/bt_tndrs_etimad_cron.log" 2>&1
