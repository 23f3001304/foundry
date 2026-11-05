#!/bin/sh
# Sets Foundry up: ./setup.sh, or ./setup.sh --try, --stop, --status, --reset. This only finds uv. Everything else is in tools/foundry_setup.py.
set -eu
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "Foundry runs itself with uv, and uv is not on your PATH."
  if [ ! -t 0 ]; then
    echo "Install it from https://docs.astral.sh/uv/getting-started/installation/ and run this again."
    exit 1
  fi
  printf "Install uv now with its official installer from https://astral.sh/uv? [y/N] "
  read -r answer
  case "$answer" in
    [yY]*) curl -LsSf https://astral.sh/uv/install.sh | sh ;;
    *) echo "Nothing was installed. Install uv from https://docs.astral.sh/uv/getting-started/installation/ and run this again."; exit 1 ;;
  esac
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi

exec uv run --no-project --isolated --quiet --python ">=3.12" tools/foundry_setup.py "$@"
