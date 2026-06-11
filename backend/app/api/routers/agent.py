"""
AGENT Router
  POST /api/agent/chat          { user_id, session_id?, message } -> { answer, transcript, steps }
  POST /api/agent/chat/stream   same body -> SSE stream
"""
from __future__ import annotations
import json
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.llm.agent import Agent

logger = logging.getLogger("cstimer-coach.agent")
router = APIRouter(prefix="/api/agent", tags=["agent"])


class ChatReq(BaseModel):
    user_id: int
    session_id: int | None = None
    message: str


class ChatResp(BaseModel):
    answer: str
    steps: int
    transcript: list[dict]


@router.post("/chat", response_model=ChatResp)
def chat(req: ChatReq) -> ChatResp:
    if not req.message.strip():
        raise HTTPException(400, "message empty")
    if len(req.message) > 2000:
        raise HTTPException(400, "message too long (max 2000)")

    try:
        result = Agent().chat(req.user_id, req.session_id, req.message)
    except Exception as e:
        logger.exception("agent chat failed")
        raise HTTPException(500, f"agent error: {e}")

    return ChatResp(
        answer=result.get("answer", ""),
        steps=result.get("steps", 0),
        transcript=result.get("transcript", []),
    )


def _sse_format(event: dict) -> bytes:
    """转 SSE 帧: event: <name>\ndata: <json>\n\n"""
    name = event.get("event", "message")
    data = json.dumps(event, ensure_ascii=False, default=str)
    return f"event: {name}\ndata: {data}\n\n".encode("utf-8")


@router.post("/chat/stream")
def chat_stream(req: ChatReq):
    """Server-Sent Events stream of agent progress"""
    if not req.message.strip():
        raise HTTPException(400, "message empty")
    if len(req.message) > 2000:
        raise HTTPException(400, "message too long (max 2000)")

    def gen():
        try:
            for ev in Agent().stream_chat(req.user_id, req.session_id, req.message):
                yield _sse_format(ev)
        except Exception as e:
            logger.exception("agent stream failed")
            yield _sse_format({"event": "error", "message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(gen(), media_type="text/event-stream")
