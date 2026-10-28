#!/usr/bin/env bash
# Starts the Local Finance Analyzer. The backend serves the web interface
# itself — one command, one local server.
#
#   ./run.sh              start with the settings chosen during installation
#   ./run.sh --port 8421  use another port this time
#   ./run.sh --open       also open the browser
#   ./run.sh --stop       stop the running app (also one started without a window)
#   ./run.sh --restart    stop it and start it again (e.g. after an update)
#   ./run.sh --help       all options
set -euo pipefail

# Files the app creates (database, backup ZIPs, exports) hold financial data:
# readable by the user only, even in a folder others can open.
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$REPO_ROOT/backend/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "The app is not installed yet (backend/.venv is missing)." >&2
  echo "Run ./install.sh first." >&2
  exit 1
fi

if [ ! -f "$REPO_ROOT/frontend/dist/index.html" ]; then
  echo "WARNING: the web interface has not been built (frontend/dist is missing)." >&2
  echo "         The API works, but the page will not load. Run ./install.sh to build it." >&2
fi

cd "$REPO_ROOT/backend"
exec "$PYTHON" -m app "$@"
