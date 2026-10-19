#!/bin/bash
# Compatibility: sync-push.sh <skill-name> <commit-message> [publisher options]
# Uses the same safety checks and dual-branch publisher, never a separate sync path.
set -euo pipefail
if [ "$#" -lt 2 ]; then
  printf 'Usage: %s <skill-name> <commit-message> [--dry-run ...]\n' "$0" >&2
  exit 2
fi
SKILL="$1"
MSG="$2"
shift 2
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec bash "$SCRIPT_DIR/../skills/ljg-push/Tools/Push.sh" \
  --repo "${SKILLS_REPO:-$HOME/.claude/ljg-skills-repo}" \
  --local "${SKILLS_LOCAL:-$HOME/.claude/skills}" \
  --skill "$SKILL" --message "$MSG" "$@"
