#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "PWD=$(pwd)"
echo "Files in PWD:"
ls -la

echo "Files in My_bot:"
ls -la My_bot

# Make /app/My_bot the import root so "import utils" works
export PYTHONPATH="$PWD/My_bot:${PYTHONPATH:-}"

echo "Testing import bot..."
python -c "import My_bot.bot as b; print('✅ bot imported'); print('Has app:', hasattr(b, 'app'))"

uvicorn My_bot.bot:app --host 0.0.0.0 --port "${PORT:-8000}"
