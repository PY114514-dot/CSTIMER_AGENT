"""
CSTIMER 智能魔方训练助手 - FastAPI 入口
"""
from __future__ import annotations
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.settings import settings
from app.persistence.db import init_db
from app.api.schemas import HealthResp
from app.api.routers import solves, sessions, dashboard, training, ai, import_data, users, ws, formulas, agent, replay, devices


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cstimer-coach")

# 前端 dist 路径: 优先环境变量, 否则默认 ../frontend/dist
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
SERVE_FRONTEND = os.environ.get("SERVE_FRONTEND", "auto").lower()  # auto|true|false
# auto = 仅当 dist 存在时挂载 (开发期可仍用 vite dev)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化 DB + 注册主事件循环 (供 WS 广播)"""
    logger.info("initializing database ...")
    init_db()
    logger.info(f"DB ready: {settings.db_path}")

    # 把主事件循环暴露给 sync 路由 (WS fire-and-forget 用)
    from app.api.ws import ws_manager
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)
    logger.info("main event loop registered for WS")
    print(f"[LIFESPAN] WS loop registered: {loop}", flush=True)

    if _should_serve_frontend():
        logger.info(f"Serving frontend from {FRONTEND_DIST} (open http://127.0.0.1:8000/)")
    else:
        logger.info("Frontend dist not found; API-only mode (run `npm run build` in frontend/, "
                    "or use `npm run dev` for vite dev server)")

    yield
    print("[LIFESPAN] shutting down", flush=True)
    logger.info("shutting down")


def _should_serve_frontend() -> bool:
    if SERVE_FRONTEND == "true":
        return True
    if SERVE_FRONTEND == "false":
        return False
    return FRONTEND_INDEX.exists()


app = FastAPI(
    title="CSTIMER 智能魔方训练助手 API",
    description="速拧训练数据采集 + AI 教练 + 智能训练计划生成",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS: 允许本地前端开发
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",      # Vite dev 默认
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",      # 后端自己挂前端时
        "http://localhost:8000",
        "*",                            # 开发期允许所有 (生产应收紧)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ────────────────────────────────────────────
app.include_router(users.router)
app.include_router(solves.router)
app.include_router(sessions.router)
app.include_router(dashboard.router)
app.include_router(training.router)
app.include_router(ai.router)
app.include_router(import_data.router)
app.include_router(ws.router)
app.include_router(formulas.router)
app.include_router(agent.router)
app.include_router(replay.router)
app.include_router(devices.router)


# ── Health ─────────────────────────────────────────────
@app.get("/health", response_model=HealthResp, tags=["meta"])
def health():
    return HealthResp(status="ok", db=settings.db_path)


@app.get("/api/info", tags=["meta"])
def api_info():
    """API 元信息 (避免占用 /, 让 / 走前端 SPA)"""
    return {
        "name": "CSTIMER 智能魔方训练助手",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "users":     "/api/users",
            "solves":    "/api/solves",
            "sessions":  "/api/sessions",
            "dashboard": "/api/dashboard",
            "training":  "/api/training",
            "ai":        "/api/ai",
            "import":    "/api/import",
            "formulas":  "/api/formulas",
            "agent":     "/api/agent",
        },
        "frontend": "served" if _should_serve_frontend() else "not built (run `npm run build` in frontend/)",
    }


# ── 前端 dist 静态托管 + SPA fallback ──────────────────
# 必须在 routers 之后, 否则会拦截 /api/*
if _should_serve_frontend():
    # 1) assets/ 子目录 (Vite build 输出, 含 hash 文件名) -> StaticFiles
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    # 2) 顶层静态文件 (vite.svg, favicon.ico 等) - 直接挂载, 非 /api/* 走这里
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIST), html=False), name="frontend-static")

    # 3) 根路径: 显式返 SPA index.html (优先级高于下面的 catch-all)
    @app.get("/", include_in_schema=False)
    async def spa_root():
        return FileResponse(str(FRONTEND_INDEX), media_type="text/html")

    # 4) SPA fallback: 任何 GET 非 /api/*, /ws/*, /docs, /openapi, /assets, /static 都没匹配到 -> 返 index.html
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request):
        # 显式排除: 让 /api/* 走 API, /ws/* 走 WS, /docs 走 FastAPI
        if (full_path.startswith("api/") or full_path.startswith("ws/")
                or full_path in ("docs", "openapi.json", "redoc")):
            from fastapi import HTTPException
            raise HTTPException(404, f"Not Found: /{full_path}")
        # 否则返 index.html, 由 React Router 处理客户端路由
        return FileResponse(str(FRONTEND_INDEX), media_type="text/html")


# 全局异常处理
@app.exception_handler(Exception)
async def unhandled_exception(request, exc):
    logger.exception(f"unhandled: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": exc.__class__.__name__},
    )
