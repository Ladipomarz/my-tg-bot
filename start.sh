#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/My_bot"

echo "PWD=$(pwd)"
echo "Files in PWD:"
ls -la

echo "Testing import server..."
python -c "import server; print('✅ server imported'); print('Has app:', hasattr(server, 'app'))"

exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8080}"


