#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv"

find_python() {
  local candidate
  for candidate in python3.12 python3.11 python3.10 python3; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi

    if "$candidate" - <<PY >/dev/null 2>&1
import sys
major, minor = sys.version_info[:2]
raise SystemExit(0 if major == 3 and 10 <= minor <= 12 else 1)
PY
    then
      command -v "$candidate"
      return 0
    fi
  done

  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  cat >&2 <<'EOF'
Error: Autovisor currently needs Python 3.10, 3.11, or 3.12 on macOS.

Install one with Homebrew, then rerun this script:
  brew install python@3.12
EOF
  exit 1
fi

printf 'Using Python: %s\n' "$("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])')"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
export AUTOVISOR_DRIVER="${AUTOVISOR_DRIVER:-chromium}"

cat <<'EOF'

Before first run:
  1. Edit configs.ini and fill course URL/account settings.
  2. This script defaults to Playwright Chromium on macOS.
  3. Leave EXE_PATH empty unless you know the exact browser executable path.

To use another browser for this run:
  AUTOVISOR_DRIVER=chrome ./run_macos.sh

Starting Autovisor...
EOF

python Autovisor.py
