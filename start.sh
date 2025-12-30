#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/My_bot"

# Now imports like "from config import ..." work again because config.py is in this folder
exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8080}"
export PYTHONPATH="$(pwd)"
