#!/usr/bin/env bash
# Installs (or updates) the Local Finance Analyzer on Linux and macOS.
#
#   ./install.sh            interactive: explains each step and asks before changing anything
#   ./install.sh --yes      non-interactive: accepts the defaults (also used automatically without a terminal)
#   ./install.sh --help     all options
#
# Safe to run again at any time: it reuses the existing environment, keeps
# your settings as defaults, and never deletes financial data.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
CONFIG_FILE="$REPO_ROOT/finance.env"
APP_NAME="finance-analyzer"
MIN_PYTHON="3.12"
TOTAL_STEPS=6

# --- options -------------------------------------------------------------------

ASSUME_YES=false
OPT_DATA_DIR=""
OPT_PORT=""
WITH_DEV=false
FORCE_PIP=false
OPT_SHORTCUT=""   # "", yes, no

usage() {
  cat <<EOF
Usage: ./install.sh [options]

  -y, --yes           don't ask anything, use defaults / previous choices
      --data-dir DIR  where your database, imported statements and backups are stored
      --port PORT     local port the app listens on (default 8420)
      --dev           also install development tools (tests, linter)
      --no-uv         use Python's venv + pip even if uv is installed
      --shortcut      create an application-menu entry (Linux)
      --no-shortcut   don't create one
  -h, --help          show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes) ASSUME_YES=true ;;
    --data-dir) OPT_DATA_DIR="${2:?--data-dir needs a directory}"; shift ;;
    --data-dir=*) OPT_DATA_DIR="${1#*=}" ;;
    --port) OPT_PORT="${2:?--port needs a number}"; shift ;;
    --port=*) OPT_PORT="${1#*=}" ;;
    --dev) WITH_DEV=true ;;
    --no-uv) FORCE_PIP=true ;;
    --shortcut) OPT_SHORTCUT=yes ;;
    --no-shortcut) OPT_SHORTCUT=no ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# No terminal to ask (CI, piped input) -> behave like --yes.
if [ ! -t 0 ]; then ASSUME_YES=true; fi

# --- output helpers ------------------------------------------------------------

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; RESET=""
fi

step()  { echo; echo "${BOLD}${BLUE}[$1/$TOTAL_STEPS] $2${RESET}"; }
info()  { echo "  $*"; }
ok()    { echo "  ${GREEN}✓${RESET} $*"; }
warn()  { echo "  ${YELLOW}!${RESET} $*"; }
fail()  { echo; echo "${RED}${BOLD}Installation stopped:${RESET} $*" >&2; exit 1; }

# ask "Question" "default" -> prints the answer
ask() {
  local question="$1" default="$2" answer
  if [ "$ASSUME_YES" = true ]; then echo "$default"; return; fi
  read -r -p "  $question ${DIM}[$default]${RESET} " answer </dev/tty || answer=""
  echo "${answer:-$default}"
}

# confirm "Question" y|n -> exit status 0 for yes
confirm() {
  local question="$1" default="$2" hint answer
  if [ "$ASSUME_YES" = true ]; then [ "$default" = y ]; return; fi
  if [ "$default" = y ]; then hint="Y/n"; else hint="y/N"; fi
  while true; do
    read -r -p "  $question [$hint] " answer </dev/tty || answer=""
    answer="$(printf '%s' "${answer:-$default}" | tr '[:upper:]' '[:lower:]')"
    case "$answer" in
      y|yes|j|ja) return 0 ;;
      n|no|nein) return 1 ;;
      *) echo "  Please answer y or n." ;;
    esac
  done
}

version_ge() {  # version_ge 3.12.1 3.12 -> true (numeric, portable: no `sort -V` on older macOS)
  awk -v a="$1" -v b="$2" 'BEGIN {
    na = split(a, x, "."); nb = split(b, y, "."); n = (na > nb ? na : nb)
    for (i = 1; i <= n; i++) { xi = x[i] + 0; yi = y[i] + 0; if (xi != yi) exit !(xi > yi) }
    exit 0
  }'
}

config_value() {  # previous value from finance.env, if any
  [ -f "$CONFIG_FILE" ] || return 0
  sed -n "s/^$1=//p" "$CONFIG_FILE" | tail -n1 | sed "s/^'\(.*\)'\$/\1/; s/\\\\'/'/g"
}

port_in_use() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

OS="$(uname -s)"
DISTRO=""
if [ -r /etc/os-release ]; then DISTRO="$(. /etc/os-release; echo "${ID_LIKE:-} ${ID:-}")"; fi

default_data_dir() {
  if [ "$OS" = Darwin ]; then echo "$HOME/Library/Application Support/$APP_NAME"
  else echo "${XDG_DATA_HOME:-$HOME/.local/share}/$APP_NAME"; fi
}

# Suggests (and, if the user agrees, runs) the package-manager command.
offer_package_install() {
  local what="$1" cmd=""
  case "$DISTRO" in
    *arch*)            cmd="sudo pacman -S --needed $2" ;;
    *debian*|*ubuntu*) cmd="sudo apt-get install -y $3" ;;
    *fedora*|*rhel*)   cmd="sudo dnf install -y $4" ;;
    *suse*)            cmd="sudo zypper install -y $4" ;;
  esac
  [ "$OS" = Darwin ] && command -v brew >/dev/null 2>&1 && cmd="brew install $5"
  if [ -z "$cmd" ]; then
    info "Please install $what with your system's package manager, then run this script again."
    return 1
  fi
  info "It can be installed with:  ${BOLD}$cmd${RESET}"
  if [ "$ASSUME_YES" = false ] && confirm "Run this command now? (it may ask for your password)" n; then
    if eval "$cmd"; then return 0; fi
    warn "The command did not succeed."
  fi
  return 1
}

# --- welcome --------------------------------------------------------------------

echo "${BOLD}Local Finance Analyzer — installation${RESET}"
echo
info "This sets up the app in:  $REPO_ROOT"
info "What will happen:"
info "  1. check that Python and Node.js are available"
info "  2. ask where to keep your data and which port to use"
info "  3. install the backend's Python packages (into backend/.venv, nothing system-wide)"
info "  4. build the web interface"
info "  5. save your settings to finance.env"
info
info "Only the packages themselves are downloaded (from PyPI and npm)."
info "Your financial data never leaves this computer."
if [ "$ASSUME_YES" = false ]; then
  echo
  confirm "Continue?" y || { echo "Nothing was changed."; exit 0; }
fi

# --- 1. requirements ------------------------------------------------------------

step 1 "Checking requirements"

USE_UV=false
if [ "$FORCE_PIP" = false ] && command -v uv >/dev/null 2>&1; then
  USE_UV=true
  ok "uv $(uv --version 2>/dev/null | awk '{print $2}') found — it will manage Python and the packages."
fi

PYTHON=""
for candidate in python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
    if [ -n "$version" ] && version_ge "$version" "$MIN_PYTHON"; then PYTHON="$(command -v "$candidate")"; break; fi
  fi
done

if [ "$USE_UV" = false ]; then
  if [ -n "$PYTHON" ]; then
    ok "Python $("$PYTHON" -c 'import platform; print(platform.python_version())') found ($PYTHON)."
    if ! "$PYTHON" -c 'import venv, ensurepip' >/dev/null 2>&1; then
      warn "Python's venv module is missing."
      offer_package_install "python venv support" python python3-venv python3 python@3.12 || \
        fail "Python's venv module is required (e.g. 'sudo apt install python3-venv')."
    fi
  else
    warn "Python $MIN_PYTHON or newer was not found."
    info "Option A (recommended): install 'uv' — a small tool that downloads the right Python by itself."
    info "          It is installed for your user only (~/.local/bin) from https://astral.sh/uv"
    if [ "$ASSUME_YES" = false ] && confirm "Install uv now?" y; then
      command -v curl >/dev/null 2>&1 || fail "curl is needed to download uv."
      curl -LsSf https://astral.sh/uv/install.sh | sh
      export PATH="$HOME/.local/bin:$PATH"
      command -v uv >/dev/null 2>&1 || fail "uv was installed but is not on PATH — open a new terminal and run ./install.sh again."
      USE_UV=true
      ok "uv installed."
    else
      info "Option B: install Python $MIN_PYTHON+ yourself:"
      offer_package_install "Python $MIN_PYTHON+" python "python3 python3-venv" python3 python@3.12 || true
      fail "Python $MIN_PYTHON or newer is required. Install it (or uv), then run ./install.sh again."
    fi
  fi
fi

# Node.js is only needed to build the web interface.
BUILD_FRONTEND=true
node_ok() {
  command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 || return 1
  local v; v="$(node --version | sed 's/^v//')"
  # Vite 8 requires Node 20.19+ or 22.12+.
  if version_ge "$v" "22.12.0"; then return 0; fi
  if version_ge "$v" "20.19.0" && ! version_ge "$v" "21.0.0"; then return 0; fi
  return 1
}
if node_ok; then
  ok "Node.js $(node --version) and npm $(npm --version) found."
else
  if command -v node >/dev/null 2>&1 && ! command -v npm >/dev/null 2>&1; then
    warn "Node.js is installed, but npm (its package manager) is missing."
  elif command -v node >/dev/null 2>&1; then
    warn "Node.js $(node --version) is too old — version 20.19+ or 22.12+ is needed."
  else
    warn "Node.js is not installed. It is only needed to build the web interface."
  fi
  offer_package_install "Node.js and npm" "nodejs npm" "nodejs npm" "nodejs npm" node || true
  if node_ok; then
    ok "Node.js $(node --version) and npm $(npm --version) found."
  elif [ -f "$FRONTEND_DIR/dist/index.html" ]; then
    warn "Using the web interface that was built earlier (it will not be updated)."
    BUILD_FRONTEND=false
  else
    fail "Node.js 20.19+ (or 22.12+) with npm is required to build the web interface. See https://nodejs.org/"
  fi
fi

# --- 2. settings ----------------------------------------------------------------

step 2 "Settings"

LEGACY_DB="$REPO_ROOT/data/finance.db"
MOVE_LEGACY=false
KEEP_LEGACY=false
if [ -f "$LEGACY_DB" ] && [ -z "$(config_value FINANCE_DATA_DIR)" ]; then
  warn "Found data from an older version inside the program folder ($REPO_ROOT/data)."
  info "New versions keep data in your personal data folder, so updating or deleting"
  info "the program folder can never affect it."
  # An earlier "no" is remembered in finance.env and becomes the default, so
  # --yes (or a run without a terminal) never moves the data against it.
  move_default=y
  if [ "$(config_value FINANCE_KEEP_DATA_IN_PROGRAM_FOLDER)" = true ]; then
    move_default=n
    info "Last time you chose to keep it there."
  fi
  if confirm "Move your existing data there now? (recommended; everything is copied and checked first)" "$move_default"; then
    MOVE_LEGACY=true
  else
    KEEP_LEGACY=true
    info "OK — the data stays where it is and keeps working."
  fi
fi

if [ "$KEEP_LEGACY" = true ]; then
  DATA_DIR="$REPO_ROOT/data"
else
  info "Your database, imported statements and backups are stored in one folder."
  previous_dir="$(config_value FINANCE_DATA_DIR)"
  DATA_DIR="${OPT_DATA_DIR:-$(ask "Data folder:" "${previous_dir:-$(default_data_dir)}")}"
  DATA_DIR="${DATA_DIR/#\~/$HOME}"
  case "$DATA_DIR" in /*) ;; *) DATA_DIR="$PWD/$DATA_DIR" ;; esac
fi

previous_port="$(config_value FINANCE_PORT)"
while true; do
  PORT="${OPT_PORT:-$(ask "Port (the app will be at http://127.0.0.1:PORT):" "${previous_port:-8420}")}"
  if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
    warn "Please enter a number between 1024 and 65535."; OPT_PORT=""; [ "$ASSUME_YES" = true ] && fail "Invalid port: $PORT"; continue
  fi
  if port_in_use "$PORT"; then
    warn "Port $PORT is currently in use (maybe the app is already running — that's fine if so)."
  fi
  break
done

previous_open="$(config_value FINANCE_OPEN_BROWSER)"
if confirm "Open the app in your browser automatically when you start it?" "$([ "${previous_open:-true}" = true ] && echo y || echo n)"; then
  OPEN_BROWSER=true
else
  OPEN_BROWSER=false
fi

CREATE_SHORTCUT=false
if [ "$OS" = Linux ]; then
  case "$OPT_SHORTCUT" in
    yes) CREATE_SHORTCUT=true ;;
    no) ;;
    *) confirm "Add 'Local Finance Analyzer' to your application menu?" n && CREATE_SHORTCUT=true ;;
  esac
fi

echo
info "${BOLD}Summary${RESET}"
info "  Data folder:   $DATA_DIR$([ "$MOVE_LEGACY" = true ] && echo "  (existing data will be moved here)")"
info "  Address:       http://127.0.0.1:$PORT"
info "  Open browser:  $OPEN_BROWSER"
info "  Python setup:  $([ "$USE_UV" = true ] && echo "uv" || echo "venv + pip ($PYTHON)")"
if [ "$ASSUME_YES" = false ]; then
  confirm "Install with these settings?" y || { echo "Nothing was changed."; exit 0; }
fi

# --- 3. backend ------------------------------------------------------------------

step 3 "Installing the backend (Python packages)"
cd "$BACKEND_DIR"

if [ -d "$BACKEND_DIR/finance" ] && [ -x "$BACKEND_DIR/finance/bin/python" ]; then
  warn "backend/finance is the environment of an older version and is no longer used."
  if confirm "Delete it? (it only contains downloaded packages)" y; then rm -rf "$BACKEND_DIR/finance"; ok "Removed."; fi
fi

if [ "$USE_UV" = true ]; then
  info "uv installs the exact package versions from uv.lock into backend/.venv ..."
  sync_args=(sync --locked)
  [ "$WITH_DEV" = true ] || sync_args+=(--no-dev)
  uv "${sync_args[@]}" || fail "uv could not install the packages (see the messages above)."
else
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    info "Creating the environment backend/.venv ..."
    "$PYTHON" -m venv "$VENV_DIR" || fail "Could not create the virtual environment."
  fi
  req="requirements.txt"; [ "$WITH_DEV" = true ] && req="requirements-dev.txt"
  info "Installing the exact package versions from backend/$req (verified by checksum) ..."
  "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip || warn "Could not upgrade pip; continuing."
  "$VENV_DIR/bin/python" -m pip install --quiet --prefer-binary --require-hashes -r "$req" \
    || fail "pip could not install the packages (see the messages above)."
fi

"$VENV_DIR/bin/python" -c "import fastapi, sqlmodel, alembic, pymupdf, openpyxl, platformdirs, app.main" \
  || fail "The backend environment is incomplete. Delete backend/.venv and run ./install.sh again."
ok "Backend ready."

# --- 4. frontend ------------------------------------------------------------------

step 4 "Building the web interface"
if [ "$BUILD_FRONTEND" = true ]; then
  cd "$FRONTEND_DIR"
  info "Installing the exact package versions from package-lock.json ..."
  npm ci --no-audit --no-fund --loglevel=error || fail "npm could not install the packages (see the messages above)."
  info "Building ..."
  npm run build --silent || fail "Building the web interface failed (see the messages above)."
  [ -f "$FRONTEND_DIR/dist/index.html" ] || fail "The build did not produce frontend/dist/index.html."
  ok "Web interface built."
else
  info "Skipped (Node.js not available) — using the existing build."
fi

# --- 5. data & settings --------------------------------------------------------------

step 5 "Saving settings"

# Financial data: only the user may open the data folder. A new folder is
# made private right away; an existing one only when the user says so in an
# interactive run, since it may be shared on purpose (--yes never changes
# it). ls -ld instead of stat: stat's options differ between GNU and
# BSD/macOS. Characters 5-10 are the group and other permissions.
make_private() {
  local dir="$1" existed="$2"
  [ "$(ls -ld "$dir" | cut -c5-10)" = "------" ] && return 0
  if [ "$existed" = true ]; then
    warn "Other users on this computer can open $dir."
    if [ "$ASSUME_YES" = true ]; then
      info "Left as it is (an existing folder is only changed when you agree; run ./install.sh without --yes)."
      return 0
    fi
    confirm "Make it private (only you can open it)?" y || { warn "Left as it is."; return 0; }
  fi
  if chmod 700 "$dir"; then ok "Data folder is private: only you can open it."
  else warn "Could not restrict $dir; other users may be able to read your data."; fi
}

DATA_DIR_EXISTED=false
[ -d "$DATA_DIR" ] && DATA_DIR_EXISTED=true
mkdir -p "$DATA_DIR" || fail "Could not create the data folder $DATA_DIR"
[ -w "$DATA_DIR" ] || fail "The data folder $DATA_DIR is not writable."
make_private "$DATA_DIR" "$DATA_DIR_EXISTED"

if [ "$MOVE_LEGACY" = true ]; then
  # The migration detects a running app by its instance lock and by open
  # database connections. An app started before this update has no lock and,
  # until its first page load, no open connection: the port still gives it away.
  if port_in_use "$PORT"; then
    confirm "Port $PORT is in use. Is the app stopped? (it must not run while its data is moved)" n \
      || fail "Stop the app (Ctrl+C in its window, or ./run.sh --stop), then run ./install.sh again. Your data was not moved."
  fi
  # Copies, verifies, switches finance.env, and only then deletes the
  # originals. See backend/app/legacy_migration.py.
  info "Copying your data to $DATA_DIR and checking the copy ..."
  (cd "$BACKEND_DIR" && "$VENV_DIR/bin/python" -m app.legacy_migration --repo-root "$REPO_ROOT" --target "$DATA_DIR") \
    || fail "Your data was not moved; it stays in $REPO_ROOT/data and the app keeps using it."
  ok "Data moved to $DATA_DIR"
fi

quote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/\\\\'/g")"; }
{
  echo "# Local Finance Analyzer settings — written by install.sh on $(date '+%Y-%m-%d %H:%M')."
  echo "# Re-run ./install.sh to change them, or edit this file and restart the app."
  if [ "$KEEP_LEGACY" = true ]; then
    # Read back by the next run as the default answer (the app ignores it).
    echo "FINANCE_KEEP_DATA_IN_PROGRAM_FOLDER=true"
  else
    echo "FINANCE_DATA_DIR=$(quote "$DATA_DIR")"
  fi
  echo "FINANCE_PORT=$PORT"
  echo "FINANCE_OPEN_BROWSER=$OPEN_BROWSER"
} > "$CONFIG_FILE.tmp"
# Moved over the old file in one step: after a data move the old database is
# gone, so a half-written finance.env (disk full, power cut) would lose
# FINANCE_DATA_DIR and the app would open an empty default folder.
mv -f "$CONFIG_FILE.tmp" "$CONFIG_FILE"
ok "Settings saved to finance.env"

chmod +x "$REPO_ROOT/run.sh" 2>/dev/null || true

if [ "$CREATE_SHORTCUT" = true ]; then
  apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  mkdir -p "$apps"
  # Desktop-entry quoting: inside "...", \ " ` $ need a backslash — which the
  # file's string escaping doubles — and % is written %%.
  desktop_quote() {
    printf '%s' "$1" | sed -e 's/\\/\\\\\\\\/g' -e 's/["`$]/\\\\&/g' -e 's/%/%%/g'
  }
  exec_path=$(desktop_quote "$REPO_ROOT/run.sh")
  cat > "$apps/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Local Finance Analyzer
Comment=Analyze your bank statements locally
Exec="$exec_path" --open
Icon=$FRONTEND_DIR/public/favicon.svg
Terminal=true
Categories=Office;Finance;
EOF
  ok "Added to the application menu (it opens a terminal window; close it to stop the app)."
fi

# --- 6. done -----------------------------------------------------------------------

step 6 "Done"
ok "Installation complete."
info "Start the app with:   ${BOLD}./run.sh${RESET}"
info "Then open:            http://127.0.0.1:$PORT"
info "Your data is kept in: $DATA_DIR"
info "Stop the app with Ctrl+C in the window it runs in, or with ./run.sh --stop."
if [ "$ASSUME_YES" = false ] && confirm "Start the app now?" y; then
  exec "$REPO_ROOT/run.sh"
fi
