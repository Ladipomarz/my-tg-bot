#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR/My_bot"
exec uvicorn My_bot.server:app --host 0.0.0.0 --port "${PORT:-8080}"
