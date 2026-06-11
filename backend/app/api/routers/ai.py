"""
AI Router: 触发/查询 AI 分析
"""
from __future__ import annotations
import asyncio
import json
import time
from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.api.schemas import AIReportResp
from app.api.ws import ws_manager
from app.domain.session_aggregator import SessionAggregator
from app.persistence import repositories as repo
from app.persistence.db import SessionLocal
from app.persistence.models import AIReport, TrainingSession


router = APIRouter(prefix="/api/ai", tags=["ai"])


def _get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _to_resp(ai: AIReport) -> AIReportResp:
    try:
        parsed = json.loads(ai.parsed_json) if ai.parsed_json else {}
    except (TypeError, ValueError):
        parsed = {}
    return AIReportResp(
        id=ai.id, session_id=ai.session_id, user_id=ai.user_id,
        model=ai.model, prompt_version=ai.prompt_version,
        bottleneck=ai.bottleneck, confidence=ai.confidence,
        parsed=parsed, created_at=ai.created_at,
    )


@router.post("/sessions/{session_id}/analyze", response_model=AIReportResp)
async def analyze_session(
    session_id: int,
    user_level: str = Query("未指定"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(_get_db),
):
    """对已关闭的 session 触发 AI 分析 (调用 DeepSeek, 异步后台执行)
    前端可订阅 /ws/session/{session_id} 看到 ai_analysis_progress / ai_analysis_done
    """
    sess = db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, f"session {session_id} not found")
    user_id = sess.user_id
    db.close()

    # 推送开始
    await ws_manager.send_to_user(user_id, "ai_analysis_started", {
        "session_id": session_id, "status": "running",
    })
    await ws_manager.send_to_session(session_id, "ai_analysis_started", {
        "session_id": session_id, "status": "running",
    })

    # 后台跑分析 (避免阻塞 HTTP)
    background_tasks.add_task(_run_ai_sync, session_id, user_id, user_level)

    return {"detail": "analysis started", "session_id": session_id,
            "websocket": f"ws://host/ws/session/{session_id}"}


@router.post("/sessions/{session_id}/analyze-sync", response_model=AIReportResp)
def analyze_session_sync(
    session_id: int,
    user_level: str = Query("未指定"),
    db: Session = Depends(_get_db),
):
    """同步版本的 AI 分析, 直接返回结果 (调试/小测试用)"""
    sess = db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, f"session {session_id} not found")
    db.close()

    summary = SessionAggregator().aggregate(session_id)
    from app.llm.ai_coach import AICoach
    from app.llm.client import LLMError
    try:
        coach = AICoach()
        report = coach.analyze(session_id, summary, user_level=user_level)
    except LLMError as e:
        raise HTTPException(502, f"LLM error: {e}")
    except Exception as e:
        raise HTTPException(500, f"unexpected: {e}")

    db = SessionLocal()
    ai = db.scalar(
        select(AIReport)
        .where(AIReport.session_id == session_id, AIReport.status == "ok")
        .order_by(desc(AIReport.created_at)).limit(1)
    )
    if not ai:
        raise HTTPException(500, "report not found after analysis")
    return _to_resp(ai)


def _run_ai_sync(session_id: int, user_id: int, user_level: str) -> None:
    """在 BackgroundTask 中同步执行 AI 分析 + 推送进度"""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        # 进度 1: 聚合
        loop.run_until_complete(ws_manager.send_to_user(user_id, "ai_analysis_progress", {
            "session_id": session_id, "stage": "aggregating", "progress": 0.2,
        }))
        summary = SessionAggregator().aggregate(session_id)

        # 进度 2: 调 LLM
        loop.run_until_complete(ws_manager.send_to_user(user_id, "ai_analysis_progress", {
            "session_id": session_id, "stage": "calling_llm", "progress": 0.5,
        }))

        from app.llm.ai_coach import AICoach
        from app.llm.client import LLMError
        try:
            coach = AICoach()
            report = coach.analyze(session_id, summary, user_level=user_level)
        except LLMError as e:
            loop.run_until_complete(ws_manager.send_to_user(user_id, "ai_analysis_failed", {
                "session_id": session_id, "error": str(e),
            }))
            return
        except Exception as e:
            loop.run_until_complete(ws_manager.send_to_user(user_id, "ai_analysis_failed", {
                "session_id": session_id, "error": str(e),
            }))
            return

        # 进度 3: 生成训练项
        loop.run_until_complete(ws_manager.send_to_user(user_id, "ai_analysis_progress", {
            "session_id": session_id, "stage": "generating_training", "progress": 0.8,
        }))

        from app.domain.training_engine import TrainingRuleEngine
        engine = TrainingRuleEngine()
        tasks = engine.generate(session_id, summary, ai_report=report, user_id=user_id)

        # 进度 4: 完成
        loop.run_until_complete(ws_manager.send_to_user(user_id, "ai_analysis_done", {
            "session_id": session_id, "report_id": report.get("id"),
            "bottlenecks": report.get("bottlenecks", []),
            "summary": report.get("summary", ""),
            "training_tasks_count": len(tasks),
        }))
        loop.run_until_complete(ws_manager.send_to_session(session_id, "ai_analysis_done", {
            "session_id": session_id, "report_id": report.get("id"),
        }))
    finally:
        loop.close()


@router.get("/sessions/{session_id}/latest", response_model=AIReportResp | None)
def latest_for_session(session_id: int, db: Session = Depends(_get_db)):
    ai = db.scalar(
        select(AIReport)
        .where(AIReport.session_id == session_id, AIReport.status == "ok")
        .order_by(desc(AIReport.created_at)).limit(1)
    )
    return _to_resp(ai) if ai else None
