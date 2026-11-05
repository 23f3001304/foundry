#!/bin/sh
# Sets Foundry up: ./setup.sh, or ./setup.sh --try, --stop, --status, --reset. This only finds uv. Everything else is in tools/foundry_setup.py.
set -eu
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  guide="https://docs.astral.sh/uv/getting-started/installation/"
  echo "Foundry runs itself with uv, and uv is not on your PATH."
  if [ ! -t 0 ]; then
    echo "Install it from $guide and run this again."
    exit 1
  fi
  echo "Setup can install it: this fetches uv's official install script from https://astral.sh/uv/install.sh and runs it."
  echo "That script puts uv in your own bin folder, and it may change your shell profile to add that folder to your PATH."
  printf "Install uv this way? [y/N] "
  read -r answer || answer=""
  case "$answer" in
    [yY]*) ;;
    *) echo "Nothing was installed. Install uv from $guide and run this again."; exit 1 ;;
  esac
  script=$(mktemp "${TMPDIR:-/tmp}/uv-install.XXXXXX")
  if ! curl -LsSf https://astral.sh/uv/install.sh -o "$script" || ! sh "$script"; then
    rm -f "$script"
    echo "uv did not install. Check your internet connection, or install it from $guide, and run this again."
    exit 1
  fi
  rm -f "$script"
  PATH="${UV_INSTALL_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}:$HOME/.local/bin:$PATH"
  export PATH
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv installed, but this terminal can't find it yet. Open a new terminal and run this again."
    exit 1
  fi
fi

exec uv run --no-project --isolated --python ">=3.12" tools/foundry_setup.py "$@"
