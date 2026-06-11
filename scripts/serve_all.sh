#!/usr/bin/env bash
# 一键启动: 拼装前端 + 起后端 (单端口模式) - bash 版本
# 用法: ./scripts/serve_all.sh [port]
set -e

PORT="${1:-8000}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

echo "=== CSTIMER 智能魔方训练助手 ==="
echo "ROOT     = $ROOT"
echo "BACKEND  = $BACKEND"
echo "FRONTEND = $FRONTEND"
echo "PORT     = $PORT"
echo

# 1) 后端依赖
echo "[1/3] 检查后端依赖 ..."
cd "$BACKEND"
if [ ! -d .venv ]; then
  echo "  创建 venv ..."
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -e ".[dev]" || {
  echo "  [WARN] pip install 失败, 继续"
}

# 2) 前端构建
echo "[2/3] 拼装前端 ..."
cd "$FRONTEND"
[ -d node_modules ] || npm install
npx vite build

# 3) 后端
echo "[3/3] 启动后端 (单端口) ..."
echo "  浏览器打开: http://127.0.0.1:$PORT/"
cd "$BACKEND"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
