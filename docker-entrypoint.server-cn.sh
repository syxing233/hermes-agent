#!/bin/sh
set -eu

REPO_DIR="/opt/hermes"
HERMES_HOME_DIR="${HERMES_HOME:-$REPO_DIR/.hermes-home}"
ENV_FILE="$HERMES_HOME_DIR/.env"

mkdir -p \
  "$HERMES_HOME_DIR/cron" \
  "$HERMES_HOME_DIR/sessions" \
  "$HERMES_HOME_DIR/logs" \
  "$HERMES_HOME_DIR/hooks" \
  "$HERMES_HOME_DIR/memories" \
  "$HERMES_HOME_DIR/skills" \
  "$HERMES_HOME_DIR/skins" \
  "$HERMES_HOME_DIR/plans" \
  "$HERMES_HOME_DIR/workspace" \
  "$HERMES_HOME_DIR/home" \
  "$HERMES_HOME_DIR/webui"

if [ ! -f "$ENV_FILE" ] && [ -f "$REPO_DIR/.env.example" ]; then
  cp "$REPO_DIR/.env.example" "$ENV_FILE"
fi

if [ ! -f "$HERMES_HOME_DIR/config.yaml" ] && [ -f "$REPO_DIR/cli-config.yaml.example" ]; then
  cp "$REPO_DIR/cli-config.yaml.example" "$HERMES_HOME_DIR/config.yaml"
fi

if [ ! -f "$HERMES_HOME_DIR/SOUL.md" ] && [ -f "$REPO_DIR/docker/SOUL.md" ]; then
  cp "$REPO_DIR/docker/SOUL.md" "$HERMES_HOME_DIR/SOUL.md"
fi

ensure_env() {
  key="$1"
  value="$2"
  if [ ! -f "$ENV_FILE" ]; then
    printf '%s=%s\n' "$key" "$value" > "$ENV_FILE"
    return
  fi
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    printf '\n%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

ensure_env "API_SERVER_ENABLED" "true"
ensure_env "API_SERVER_HOST" "127.0.0.1"
ensure_env "API_SERVER_PORT" "8642"

export HERMES_PROJECT_ROOT="$REPO_DIR"
export HERMES_HOME="$HERMES_HOME_DIR"
export HOME="$HERMES_HOME_DIR/home"
export TERMINAL_CWD="${TERMINAL_CWD:-$REPO_DIR}"
export PATH="$REPO_DIR/.venv/bin:$REPO_DIR/hermes-web-ui/node_modules/.bin:$PATH"

cd "$REPO_DIR"
exec "$REPO_DIR/run-hermes-webui-local.sh" "${PORT:-8805}"
