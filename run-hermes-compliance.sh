#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
HERMES_PYTHON="$REPO_DIR/.venv/bin/python"
PROJECT_HERMES_HOME="$REPO_DIR/.hermes-home"
PROFILE_HOME="$PROJECT_HERMES_HOME/profiles/compliance"
COMPLIANCE_EXTERNAL_SKILLS_DIR="${COMPLIANCE_EXTERNAL_SKILLS_DIR:-}"
COMPLIANCE_PRELOAD_SKILL="${COMPLIANCE_PRELOAD_SKILL:-compliance-workflow-cn}"

if [[ -n "${HERMES_HOME:-}" && "${HERMES_HOME}" != "$PROFILE_HOME" && "${HERMES_HOME}" != "$PROJECT_HERMES_HOME" ]]; then
  echo "Refusing external HERMES_HOME: $HERMES_HOME" >&2
  echo "Compliance launcher only allows $PROJECT_HERMES_HOME or $PROFILE_HOME" >&2
  exit 1
fi

if [[ ! -x "$HERMES_PYTHON" ]]; then
  echo "Hermes Python interpreter not found: $HERMES_PYTHON" >&2
  echo "Expected the project virtualenv to live at /Users/syxing/Documents/hermes-agent/.venv/" >&2
  exit 1
fi

mkdir -p \
  "$PROFILE_HOME/cron" \
  "$PROFILE_HOME/sessions" \
  "$PROFILE_HOME/logs" \
  "$PROFILE_HOME/hooks" \
  "$PROFILE_HOME/memories" \
  "$PROFILE_HOME/skills" \
  "$PROFILE_HOME/skins" \
  "$PROFILE_HOME/plans" \
  "$PROFILE_HOME/workspace" \
  "$PROFILE_HOME/home"

export HERMES_HOME="$PROFILE_HOME"
export TERMINAL_CWD="${TERMINAL_CWD:-$PWD}"
export PATH="$REPO_DIR/.venv/bin:$PATH"
export HERMES_PROJECT_ROOT="$REPO_DIR"

if [[ -n "$COMPLIANCE_EXTERNAL_SKILLS_DIR" && ! -d "$COMPLIANCE_EXTERNAL_SKILLS_DIR" ]]; then
  COMPLIANCE_EXTERNAL_SKILLS_DIR=""
fi
export COMPLIANCE_EXTERNAL_SKILLS_DIR

"$HERMES_PYTHON" - <<'PY'
import os
from hermes_cli.compliance_profile import ensure_compliance_profile_config

external_skills_dir = (os.getenv("COMPLIANCE_EXTERNAL_SKILLS_DIR") or "").strip() or None
ensure_compliance_profile_config(external_skills_dir=external_skills_dir)
PY

if [[ $# -eq 0 ]]; then
  set -- chat
else
  case "$1" in
    -q|--query|--image|-m|--model|-t|--toolsets|-s|--skills|--provider|-v|--verbose|-Q|--quiet|--resume|-r|--continue|-c|--worktree|--checkpoints|--max-turns|--yolo|--pass-session-id|--source)
      set -- chat "$@"
      ;;
  esac
fi

has_skills_flag=0
for arg in "$@"; do
  case "$arg" in
    -s|--skills|--skills=*)
      has_skills_flag=1
      break
      ;;
  esac
done

if [[ "${1:-}" == "chat" && $has_skills_flag -eq 0 && -n "$COMPLIANCE_PRELOAD_SKILL" ]]; then
  set -- "$1" --skills "$COMPLIANCE_PRELOAD_SKILL" "${@:2}"
fi

exec "$HERMES_PYTHON" -m hermes_cli.main "$@"
