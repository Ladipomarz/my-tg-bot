#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR/My_bot"
exec python "$DIR/My_bot/bot.py"
