"""
工具: 在 sync context (FastAPI 同步路由) 中调度 async 协程到主事件循环
"""
from __future__ import annotations
import asyncio
import logging
import threading

logger = logging.getLogger("cstimer-coach.utils")

# 启动时记录主事件循环引用
_main_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    with _loop_lock:
        _main_loop = loop


def fire_and_forget(coro) -> None:
    """从 sync 代码 (FastAPI 同步路由) 调度一个 async 协程到主事件循环.
    事件循环没启动 (例如纯 sync 测试) 时静默丢弃.
    """
    with _loop_lock:
        loop = _main_loop
    if loop is None or loop.is_closed():
        # 测试或 sync 模式: 静默丢弃
        return
    try:
        asyncio.run_coroutine_threadsafe(coro, loop)
    except RuntimeError as e:
        logger.debug(f"fire_and_forget failed: {e}")
