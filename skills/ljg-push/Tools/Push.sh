#!/bin/bash
# Single publisher implementation; Python 3.9+ standard library only.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec python3 -B "$SCRIPT_DIR/publish.py" "$@"
