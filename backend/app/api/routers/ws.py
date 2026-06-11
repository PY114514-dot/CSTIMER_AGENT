"""
WebSocket 端点:
  /ws/user/{user_id}      - 订阅某用户的所有事件
  /ws/session/{session_id} - 订阅某 Session 的事件
  /ws                     - 订阅全广播
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.ws import ws_manager


logger = logging.getLogger("cstimer-coach.ws")
router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def ws_broadcast(ws: WebSocket):
    """全广播通道"""
    await ws_manager.connect_broadcast(ws)
    try:
        while True:
            # 客户端可以发 ping/pong, 我们只关心接收
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS broadcast error: {e}")
    finally:
        await ws_manager.disconnect(ws)


@router.websocket("/ws/user/{user_id}")
async def ws_user(ws: WebSocket, user_id: int):
    """用户级频道"""
    await ws_manager.connect_user(ws, user_id)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS user error: {e}")
    finally:
        await ws_manager.disconnect(ws)


@router.websocket("/ws/session/{session_id}")
async def ws_session(ws: WebSocket, session_id: int):
    """Session 级频道"""
    await ws_manager.connect_session(ws, session_id)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS session error: {e}")
    finally:
        await ws_manager.disconnect(ws)
