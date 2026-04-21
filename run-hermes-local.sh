#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_HERMES_HOME="$REPO_DIR/.hermes-home"
PROJECT_TERMINAL_CWD="${TERMINAL_CWD:-$REPO_DIR}"
PYTHON_BIN="$REPO_DIR/.venv/bin/python"

if [[ -n "${HERMES_HOME:-}" && "${HERMES_HOME}" != "$PROJECT_HERMES_HOME" && ! "${HERMES_HOME}" =~ ^${PROJECT_HERMES_HOME}/profiles/[^/]+$ ]]; then
  echo "Refusing external HERMES_HOME: $HERMES_HOME" >&2
  echo "Project-local Hermes only allows $PROJECT_HERMES_HOME or $PROJECT_HERMES_HOME/profiles/<name>" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python interpreter not found: $PYTHON_BIN" >&2
  echo "Expected the project virtualenv to live at .venv/" >&2
  exit 1
fi

mkdir -p \
  "$PROJECT_HERMES_HOME/cron" \
  "$PROJECT_HERMES_HOME/sessions" \
  "$PROJECT_HERMES_HOME/logs" \
  "$PROJECT_HERMES_HOME/hooks" \
  "$PROJECT_HERMES_HOME/memories" \
  "$PROJECT_HERMES_HOME/skills" \
  "$PROJECT_HERMES_HOME/skins" \
  "$PROJECT_HERMES_HOME/plans" \
  "$PROJECT_HERMES_HOME/workspace" \
  "$PROJECT_HERMES_HOME/home"

export HERMES_HOME="$PROJECT_HERMES_HOME"
export TERMINAL_CWD="$PROJECT_TERMINAL_CWD"
export PATH="$REPO_DIR/.venv/bin:$PATH"
export HERMES_PROJECT_ROOT="$REPO_DIR"

exec "$PYTHON_BIN" -m hermes_cli.main "$@"
