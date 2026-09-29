#!/usr/bin/env bash
set -euo pipefail

python3 -m compileall -q opspilot tests
python3 -m pip install --disable-pip-version-check --no-deps -q .
python3 -m unittest discover -s tests -v
opspilot validate-project --project-file examples/devcontrol.project.example.json
