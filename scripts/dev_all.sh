#!/usr/bin/env bash
# 开发模式: 后端 8000 + 前端 5173 (Vite dev, 带 HMR) - bash 版本
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

echo "=== CSTIMER 开发模式 (双端口) ==="
echo "  后端: http://127.0.0.1:8000"
echo "  前端: http://127.0.0.1:5173"
echo

( cd "$BACKEND" && .venv/bin/python -m uvicorn app.main:app --reload --port 8000 ) &
BACK_PID=$!
( cd "$FRONTEND" && npx vite ) &
FRONT_PID=$!

trap "kill $BACK_PID $FRONT_PID 2>/dev/null" EXIT
echo "后端 PID=$BACK_PID  前端 PID=$FRONT_PID  (Ctrl+C 关闭)"
wait
