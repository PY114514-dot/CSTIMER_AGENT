"""
跨平台一键启动器 - 走 python -m scripts.start 就能用, PowerShell 字符串解析坑全避开
用法:
  python -m scripts.start                  (默认 8000)
  python -m scripts.start -p 9000
  python -m scripts.start --skip-frontend
  python -m scripts.start --dev            (双端口)
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT     = Path(__file__).resolve().parents[1]
BACKEND  = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def step(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def info(msg: str) -> None:
    print(f"  {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}", flush=True)


def err(msg: str) -> None:
    print(f"  [ERR] {msg}", flush=True)


def run(cmd: list[str], cwd: Path, shell: bool = False, **kwargs) -> int:
    """subprocess wrapper. shell=True 时 Windows 走 cmd.exe 找命令 (npx/npm 等)"""
    if shell:
        # 拼成单字符串给 cmd
        joined = subprocess.list2cmdline(cmd) if sys.platform == "win32" else " ".join(cmd)
        print(f"  $ {joined}   (cwd={cwd})", flush=True)
        return subprocess.call(joined, cwd=str(cwd), shell=True, **kwargs)
    print(f"  $ {' '.join(str(c) for c in cmd)}   (cwd={cwd})", flush=True)
    return subprocess.call(cmd, cwd=str(cwd), **kwargs)


def find_venv_python(backend: Path) -> Path | None:
    """优先 .venv/Scripts/python.exe (win) / .venv/bin/python (unix)"""
    if sys.platform == "win32":
        p = backend / ".venv" / "Scripts" / "python.exe"
    else:
        p = backend / ".venv" / "bin" / "python"
    return p if p.exists() else None


def ensure_backend(backend: Path) -> Path:
    """确保 venv + 依赖, 返回 python 可执行路径"""
    py = find_venv_python(backend)
    if py is None:
        warn("venv 不存在, 创建中 ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(backend / ".venv")])
        py = find_venv_python(backend)
        assert py is not None
    info(f"venv: {py}")

    # 探测 fastapi/uvicorn 是否已装
    probe = subprocess.run(
        [str(py), "-c", "import fastapi, uvicorn, sqlalchemy, pydantic"],
        capture_output=True, text=True,
    )
    if probe.returncode == 0:
        info("依赖已就绪, 跳过 pip install")
    else:
        # 给个选项: 不想等就强起 (实际启时缺包会立刻报错)
        if "--no-install" in sys.argv:
            warn("依赖未全, --no-install 跳过装, 直接起 (可能 ImportError)")
        else:
            info("安装依赖 (首次需 1-2 分钟) ...")
            rc = run([str(py), "-m", "pip", "install", "-e", ".[dev]"], backend)
            if rc != 0:
                warn(f"pip install 返回 {rc}, 继续尝试启动 (可能缺包)")
    return py


def build_frontend(frontend: Path, skip: bool) -> None:
    if skip:
        info("跳过前端 build (-SkipFrontend)")
        return
    if not (frontend / "node_modules").exists():
        info("npm install (首次) ...")
        rc = run(["npm", "install"], frontend, shell=True)
        if rc != 0:
            err("npm install 失败"); sys.exit(1)
    info("vite build ...")
    # npm/npx 在 venv PATH 里找不到, 必须 shell=True
    rc = run(["npx", "vite", "build"], frontend, shell=True)
    if rc != 0:
        err("vite build 失败"); sys.exit(1)


def start_dev(backend: Path, frontend: Path, py: Path) -> None:
    info("dev 双端口: 后端 8000 + 前端 5173")
    backend_cmd = [str(py), "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"]
    frontend_cmd = "npx vite"  # shell=True 形式
    bp = subprocess.Popen(backend_cmd, cwd=str(backend))
    try:
        fp = subprocess.Popen(frontend_cmd, cwd=str(frontend), shell=True)
    except Exception:
        bp.terminate(); raise
    try:
        print("\n按 Ctrl+C 关闭 ...", flush=True)
        while True:
            time.sleep(0.5)
            if bp.poll() is not None or fp.poll() is not None:
                break
    except KeyboardInterrupt:
        pass
    finally:
        for p in (bp, fp):
            try: p.terminate()
            except Exception: pass


def start_single(backend: Path, py: Path, port: int) -> None:
    info(f"启动后端 (单端口 {port})")
    info(f"open http://127.0.0.1{':'}{port}/ in browser")
    os.chdir(backend)
    cmd = [str(py), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port), "--reload"]
    # 用 subprocess.run 阻塞, Ctrl+C 会把信号传给子进程
    sys.exit(subprocess.call(cmd, cwd=str(backend)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, default=8000)
    parser.add_argument("--skip-frontend", action="store_true", help="不重新 build, 用现有 dist")
    parser.add_argument("--dev", action="store_true", help="双端口模式 (后端 8000 + Vite 5173)")
    parser.add_argument("--no-install", action="store_true", help="跳过 pip install (依赖已就绪时)")
    args = parser.parse_args()

    print("=" * 60)
    print("CSTIMER 智能魔方训练助手")
    print("=" * 60)
    print(f"ROOT     = {ROOT}")
    print(f"BACKEND  = {BACKEND}")
    print(f"FRONTEND = {FRONTEND}")
    print(f"PORT     = {args.port}")
    print(f"MODE     = {'dev' if args.dev else 'single'}")
    print()

    step("[1/3] 后端环境")
    py = ensure_backend(BACKEND)

    step("[2/3] 前端构建")
    build_frontend(FRONTEND, skip=args.skip_frontend)

    step("[3/3] 启动")
    if args.dev:
        start_dev(BACKEND, FRONTEND, py)
    else:
        start_single(BACKEND, py, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
