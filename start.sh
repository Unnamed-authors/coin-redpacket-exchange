#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data
if [ ! -d frontend/node_modules ]; then (cd frontend && npm ci); fi
(cd frontend && npm run build)
python3 mock_redpacket.py &
MOCK_PID=$!
python3 server.py &
APP_PID=$!
trap 'kill "$APP_PID" "$MOCK_PID" 2>/dev/null || true' EXIT INT TERM
sleep 1
kill -0 "$APP_PID" "$MOCK_PID"
printf '\n访问 http://localhost:8080 · demo / demo12345\n'
while kill -0 "$APP_PID" 2>/dev/null && kill -0 "$MOCK_PID" 2>/dev/null; do sleep 1; done
printf '\n服务进程已退出，请检查端口占用或错误日志。\n' >&2
exit 1
