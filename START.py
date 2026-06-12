#!/usr/bin/env python3
"""
START.py ── cstimer_agent 一键启动脚本

用法:
    python START.py              # 同时启动后端 + 前端
    python START.py --backend    # 只启动后端
    python START.py --frontend   # 只启动前端
    python START.py --install    # 先安装依赖再启动

行为:
    - 自动检测 .venv, 缺失则提示用 --install
    - 后端: uvicorn backend.app.main:app --reload --port 8000
    - 前端: npm run dev (frontend/)
    - 两个进程统一接收 Ctrl+C, 一同关闭
    - 彩色日志, 方便区分前后端输出
"""
from __future__ import annotations
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

# ── 颜色 ─────────────────────────────────────────────
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RED    = "\033[31m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    BLUE   = "\033[34m"
    MAGENTA= "\033[35m"
    CYAN   = "\033[36m"
    @staticmethod
    def wrap(s: str, color: str) -> str:
        return f"{color}{s}{C.RESET}" if sys.stdout.isatty() else s

# Windows 10+ 启用 ANSI 颜色
if sys.platform == "win32":
    os.system("")

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / "Scripts" / "python.exe" if sys.platform == "win32" else VENV / "bin" / "python"
VENV_PIP    = VENV / "Scripts" / "pip.exe"    if sys.platform == "win32" else VENV / "bin" / "pip"
VENV_NPM    = VENV / "Scripts" / "npm.exe"    if sys.platform == "win32" else VENV / "bin" / "npm"
FRONTEND    = ROOT / "frontend"
BACKEND     = ROOT / "backend"

# ── 工具 ─────────────────────────────────────────────
def info(msg: str) -> None:  print(C.wrap(f"[start] {msg}", C.CYAN))
def ok(msg: str)   -> None:  print(C.wrap(f"[  ok ] {msg}", C.GREEN))
def warn(msg: str) -> None:  print(C.wrap(f"[warn ] {msg}", C.YELLOW))
def err(msg: str)  -> None:  print(C.wrap(f"[ ERR ] {msg}", C.RED))

def python() -> str:
    """优先用 venv 里的 python"""
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable

def pip() -> str:
    return str(VENV_PIP) if VENV_PIP.exists() else "pip"

def npm() -> Optional[str]:
    """返回 npm 可执行文件的绝对路径 (优先 .cmd, Windows 上 CreateProcess 需要扩展名)"""
    candidates = ["npm.cmd", "npm.exe", "npm"]
    for c in candidates:
        p = shutil.which(c)
        if p: return p
    if VENV_NPM.exists():
        return str(VENV_NPM)
    return None

# ── 安装依赖 ─────────────────────────────────────────
def install_deps() -> int:
    if not VENV.exists():
        warn(f"未找到 {VENV}, 请先创建: python -m venv .venv")
        return 1
    p = str(pip())
    # 后端: 优先 pyproject.toml (PEP 621), 否则 requirements.txt
    pyproject = BACKEND / "pyproject.toml"
    if pyproject.exists():
        info("安装后端依赖 (backend/pyproject.toml, 含 dev) ...")
        code = subprocess.run(
            [p, "install", "-e", ".[dev]", "--quiet"],
            cwd=str(BACKEND),
        ).returncode
        if code != 0: return code
    else:
        req = BACKEND / "requirements.txt"
        if req.exists():
            info("安装后端依赖 (backend/requirements.txt) ...")
            code = subprocess.run([p, "install", "-r", str(req)]).returncode
            if code != 0: return code
        else:
            warn("未找到 backend/pyproject.toml 或 backend/requirements.txt, 跳过后端依赖安装")

    # 前端
    if (FRONTEND / "package.json").exists():
        info("安装前端依赖 (frontend/) ...")
        npm_cmd = npm()
        if not npm_cmd:
            err("未找到 npm, 请先安装 Node.js 18+")
            return 1
        code = subprocess.run(
            [npm_cmd, "install", "--no-audit", "--no-fund"],
            cwd=str(FRONTEND),
        ).returncode
    return code
# ── 后端 ─────────────────────────────────────────────
def start_backend() -> Optional[subprocess.Popen]:
    """用 uvicorn 启动 FastAPI"""
    main_path = BACKEND / "app" / "main.py"
    if not main_path.exists():
        warn(f"未找到 {main_path}, 跳过后端启动")
        return None
    info("启动后端: uvicorn :8000 (auto-reload)")
    # backend 用 pyproject.toml (可编辑安装), 跑在 backend/ 目录下, 模块路径 app.main:app
    return subprocess.Popen(
        [str(python()), "-m", "uvicorn", "app.main:app",
         "--reload", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=str(BACKEND),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

# ── 前端 ─────────────────────────────────────────────
def start_frontend() -> Optional[subprocess.Popen]:
    pkg = FRONTEND / "package.json"
    if not pkg.exists():
        warn(f"未找到 {pkg}, 跳过后端启动")
        return None
    npm_cmd = npm()
    if not npm_cmd:
        warn("未找到 npm, 跳过后端启动 (需要 Node.js 18+)")
        return None
    info("启动前端: vite :5173")
    if not (FRONTEND / "node_modules").exists():
        warn("frontend/node_modules 缺失, 第一次启动会比较慢")
    return subprocess.Popen(
        [npm_cmd, "run", "dev"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=str(FRONTEND),
        env={**os.environ, "FORCE_COLOR": "1"},
    )

# ── 实时日志转发 ─────────────────────────────────────
TAG_BE = C.wrap("[BE]", C.MAGENTA + C.BOLD)
TAG_FE = C.wrap("[FE]", C.BLUE   + C.BOLD)

def pipe_output(proc: subprocess.Popen, tag: str) -> None:
    """在独立线程里把子进程输出加 tag 后打到主控制台"""
    import threading
    def _run():
        try:
            for line in iter(proc.stdout.readline, b""):
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    print(f"{tag} {text}", flush=True)
        except Exception:
            pass
    t = threading.Thread(target=_run, daemon=True)
    t.start()

# ── 优雅退出 ─────────────────────────────────────────
def wait_with_signal(procs: List[subprocess.Popen]) -> int:
    """阻塞到任意子进程退出 或 收到 Ctrl+C"""
    stop = {"flag": False}
    def _handler(_sig, _frm): stop["flag"] = True
    signal.signal(signal.SIGINT, _handler)
    if hasattr(signal, "SIGTERM"): signal.signal(signal.SIGTERM, _handler)

    try:
        while not stop["flag"]:
            time.sleep(0.2)
            for p in procs:
                if p.poll() is not None:
                    return p.returncode or 0
        return 0
    finally:
        info("收到退出信号, 关闭所有子进程 ...")
        for p in procs:
            if p.poll() is None:
                try: p.terminate()
                except Exception: pass
        # 给 3s 优雅退出
        for p in procs:
            try: p.wait(timeout=3)
            except Exception:
                try: p.kill()
                except Exception: pass
        ok("已退出")

# ── 入口 ─────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="cstimer_agent 一键启动")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--backend",  action="store_true", help="只启动后端")
    g.add_argument("--frontend", action="store_true", help="只启动前端")
    parser.add_argument("--install", action="store_true", help="先安装依赖再启动")
    args = parser.parse_args()

    print(C.wrap("=" * 60, C.BOLD))
    print(C.wrap("  cstimer_agent 启动器", C.BOLD + C.CYAN))
    print(C.wrap("=" * 60, C.BOLD))

    if args.install:
        code = install_deps()
        if code != 0:
            err("依赖安装失败")
            return code

    procs: List[subprocess.Popen] = []
    if not args.frontend:
        be = start_backend()
        if be: procs.append(be); pipe_output(be, TAG_BE)
    if not args.backend:
        fe = start_frontend()
        if fe: procs.append(fe); pipe_output(fe, TAG_FE)

    if not procs:
        err("没有任何进程启动, 请检查 backend/ frontend/ 目录")
        return 1

    print()
    ok(f"已启动 {len(procs)} 个进程, 按 Ctrl+C 停止")
    if any("8000" in (p.args[0] if p.args else "") for p in procs):
        info("后端 API:    http://127.0.0.1:8000/docs")
    if any("dev" in (p.args[0] if p.args else "") for p in procs):
        info("前端 Dev:    http://localhost:5173")
    print()

    return wait_with_signal(procs)

if __name__ == "__main__":
    sys.exit(main())
