#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  python3.12 -m venv .venv
fi

.venv/bin/python -m pip install -q -r requirements.txt

if [[ ! -f .env ]]; then
  echo "Create .env from .env.example and set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL." >&2
  exit 1
fi

if ! az account show --query id -o none >/dev/null 2>&1; then
  echo "Sign in with 'az login' and rerun this script." >&2
  exit 1
fi

.venv/bin/python -m pytest -q
exec .venv/bin/python main.py "$@"
