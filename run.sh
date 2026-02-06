#!/usr/bin/env bash
set -euo pipefail

# Change to this script's directory
cd "$(dirname "$0")"

# Create venv if missing
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Upgrade pip and install requirements
python -m pip install --upgrade pip
pip install -r requirements.txt

# Load .env if present (DB_FILEPATH, TABLE_NAME)
if [ -f .env ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs -d '\n' -r)
fi

# Allow optional --db and --port flags
DB_ARG=""
PORT_ARG=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --db)
      shift
      DB_FILEPATH=${1:-}
      export DB_FILEPATH
      ;;
    --port)
      shift
      PORT_ARG="--server.port=${1:-8501}"
      ;;
  esac
  shift || true
done

# Run streamlit
exec streamlit run app.py ${PORT_ARG}

