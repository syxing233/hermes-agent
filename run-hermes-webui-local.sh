#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
WEBUI_DIR="$REPO_DIR/hermes-web-ui"
PROJECT_HERMES_HOME="$REPO_DIR/.hermes-home"
PROJECT_WEBUI_HOME="$PROJECT_HERMES_HOME/webui"
PROJECT_HOME_DIR="$PROJECT_HERMES_HOME/home"
PYTHON_BIN="$REPO_DIR/.venv/bin/python"
SERVER_ENTRY="$WEBUI_DIR/dist/server/index.js"

if [[ ! -d "$WEBUI_DIR" ]]; then
  echo "Web UI directory not found: $WEBUI_DIR" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python interpreter not found: $PYTHON_BIN" >&2
  echo "Expected the project virtualenv to live at .venv/" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is required but was not found in PATH." >&2
  exit 1
fi

if [[ ! -d "$WEBUI_DIR/node_modules" ]]; then
  echo "Web UI dependencies are missing: $WEBUI_DIR/node_modules" >&2
  echo "Run: cd \"$WEBUI_DIR\" && npm install" >&2
  exit 1
fi

if [[ ! -f "$SERVER_ENTRY" ]]; then
  echo "Web UI build output not found, building once..." >&2
  (
    cd "$WEBUI_DIR"
    npm run build
  )
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
  "$PROJECT_HOME_DIR" \
  "$PROJECT_WEBUI_HOME"

export HERMES_PROJECT_ROOT="$REPO_DIR"
export HERMES_HOME="$PROJECT_HERMES_HOME"
export HERMES_BIN="$REPO_DIR/run-hermes-local.sh"
export TERMINAL_CWD="${TERMINAL_CWD:-$REPO_DIR}"
export HOME="$PROJECT_HOME_DIR"
export PATH="$REPO_DIR/.venv/bin:$WEBUI_DIR/node_modules/.bin:$PATH"

exec node "$WEBUI_DIR/bin/hermes-web-ui.mjs" "$@"
