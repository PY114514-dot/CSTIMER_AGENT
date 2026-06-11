"""
WebSocket 广播管理器 - 异步版 (与 FastAPI 主 loop 集成)

注意: WebSocket.send_text 是 async, 必须从事件循环调用.
本模块不主动启动后台线程, 而是把 send_* 暴露为 async, 在 async context 中调用.
对于 sync 路由, 使用 utils.async_dispatch.fire_and_forget 把任务调度到主 loop.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Any
from fastapi import WebSocket

logger = logging.getLogger("cstimer-coach.ws")


class WSManager:
    def __init__(self) -> None:
        # user_id -> set[WebSocket]
        self._user_clients: dict[int, set[WebSocket]] = {}
        # session_id -> set[WebSocket]
        self._session_clients: dict[int, set[WebSocket]] = {}
        # 全局订阅
        self._broadcast_clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        # 引用主 loop 用于 sync 路由 fire-and-forget
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect_user(self, ws: WebSocket, user_id: int) -> None:
        await ws.accept()
        async with self._lock:
            self._user_clients.setdefault(user_id, set()).add(ws)
        logger.info(f"WS connected: user={user_id}")

    async def connect_session(self, ws: WebSocket, session_id: int) -> None:
        await ws.accept()
        async with self._lock:
            self._session_clients.setdefault(session_id, set()).add(ws)
        logger.info(f"WS connected: session={session_id}")

    async def connect_broadcast(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._broadcast_clients.add(ws)
        logger.info("WS connected: broadcast")

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            for s in self._user_clients.values():
                s.discard(ws)
            for s in self._session_clients.values():
                s.discard(ws)
            self._broadcast_clients.discard(ws)

    def _schedule(self, coro) -> None:
        """从 sync 上下文把 coro 调度到主 loop"""
        if self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            pass

    def send_to_user(self, user_id: int, event: str, data: dict[str, Any] | None = None) -> None:
        """sync 入口: 调度到主 loop"""
        self._schedule(self._send_to_user_async(user_id, event, data))

    def send_to_session(self, session_id: int, event: str, data: dict[str, Any] | None = None) -> None:
        self._schedule(self._send_to_session_async(session_id, event, data))

    def broadcast(self, event: str, data: dict[str, Any] | None = None) -> None:
        self._schedule(self._broadcast_async(event, data))

    async def _send_to_user_async(self, user_id: int, event: str, data: dict[str, Any] | None) -> None:
        payload = self._make_payload(event, data)
        async with self._lock:
            user_targets = list(self._user_clients.get(user_id, set()))
            broadcast_targets = list(self._broadcast_clients)
        await self._broadcast_to(payload, user_targets + broadcast_targets)

    async def _send_to_session_async(self, session_id: int, event: str, data: dict[str, Any] | None) -> None:
        payload = self._make_payload(event, data)
        async with self._lock:
            session_targets = list(self._session_clients.get(session_id, set()))
            broadcast_targets = list(self._broadcast_clients)
        await self._broadcast_to(payload, session_targets + broadcast_targets)

    async def _broadcast_async(self, event: str, data: dict[str, Any] | None) -> None:
        payload = self._make_payload(event, data)
        async with self._lock:
            targets = list(self._broadcast_clients)
        await self._broadcast_to(payload, targets)

    async def await_send_to_user(self, user_id: int, event: str, data: dict[str, Any] | None = None) -> None:
        """async 入口: 直接 await (在 async 路由或 BackgroundTask 中使用)"""
        await self._send_to_user_async(user_id, event, data)

    async def await_send_to_session(self, session_id: int, event: str, data: dict[str, Any] | None = None) -> None:
        await self._send_to_session_async(session_id, event, data)

    def _make_payload(self, event: str, data: dict[str, Any] | None) -> dict:
        return {
            "event": event,
            "ts": int(time.time() * 1000),
            "data": data or {},
        }

    async def _broadcast_to(self, payload: dict, targets: list[WebSocket]) -> None:
        if not targets:
            return
        text = json.dumps(payload, ensure_ascii=False, default=str)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception as e:
                logger.debug(f"WS send failed: {e}")
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    for s in self._user_clients.values():
                        s.discard(ws)
                    for s in self._session_clients.values():
                        s.discard(ws)
                    self._broadcast_clients.discard(ws)


# 全局单例
ws_manager = WSManager()
