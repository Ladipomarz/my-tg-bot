#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

export PYTHONPATH="$(pwd)"

echo "PWD=$(pwd)"
echo "PYTHONPATH=$PYTHONPATH"
echo "Listing My_bot:"
ls -la My_bot || true

echo "Testing import My_bot.server..."
python -c "import My_bot.server; print('✅ import ok')"  # <-- will show the real error if it fails

exec uvicorn My_bot.server:app --host 0.0.0.0 --port "${PORT:-8080}"
