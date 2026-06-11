"""
Sessions Router: 列出/详情/关闭/分析触发
"""
from __future__ import annotations
import json
import time
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.api.schemas import (
    SessionCreateReq, SessionResp, SessionDetailResp,
    SessionStatsResp, CubeResp, AIReportResp, TrainingTaskResp,
)
from app.api.ws import ws_manager
from app.domain.session_aggregator import SessionAggregator
from app.domain.training_engine import TrainingRuleEngine
from app.persistence import repositories as repo
from app.persistence.db import SessionLocal
from app.persistence.models import (
    TrainingSession, Cube, SolveStages, SessionStats,
    AIReport, TrainingTask, MoveEvent, PauseEvent,
)


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _now_ms() -> int:
    return int(time.time() * 1000)


@router.post("", response_model=SessionResp)
def create_session(req: SessionCreateReq, db: Session = Depends(_get_db)) -> SessionResp:
    user = db.get(__import__("app.persistence.models", fromlist=["User"]).User, req.user_id)
    if not user:
        raise HTTPException(404, f"user {req.user_id} not found")
    sess = repo.create_session(
        db, user_id=req.user_id, target_size=req.target_size, name=req.name
        or f"manual-{_now_ms()}"
    )
    db.commit()
    return SessionResp.model_validate(sess)


@router.get("", response_model=list[SessionResp])
def list_sessions(user_id: int, limit: int = 30, db: Session = Depends(_get_db)):
    rows = list(db.scalars(
        select(TrainingSession)
        .where(TrainingSession.user_id == user_id)
        .order_by(desc(TrainingSession.started_at))
        .limit(limit)
    ))
    return [SessionResp.model_validate(r) for r in rows]


@router.get("/{session_id}", response_model=SessionDetailResp)
def get_session(session_id: int, db: Session = Depends(_get_db)) -> SessionDetailResp:
    sess = db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, f"session {session_id} not found")

    cubes = list(db.scalars(
        select(Cube).where(Cube.session_id == session_id).order_by(Cube.started_at)
    ))
    stats = db.scalar(select(SessionStats).where(SessionStats.session_id == session_id))
    ai = db.scalar(
        select(AIReport)
        .where(AIReport.session_id == session_id, AIReport.status == "ok")
        .order_by(desc(AIReport.created_at)).limit(1)
    )
    tasks = list(db.scalars(
        select(TrainingTask).where(TrainingTask.session_id == session_id)
    ))

    return SessionDetailResp(
        session=SessionResp.model_validate(sess),
        stats=SessionStatsResp(**stats.to_dict()) if stats else None,
        cubes=[CubeResp.model_validate(c) for c in cubes],
        ai_report=_to_ai_resp(ai) if ai else None,
        training_tasks=[_to_task_resp(t) for t in tasks],
    )


@router.post("/{session_id}/close", response_model=SessionResp)
def close_session(session_id: int, db: Session = Depends(_get_db)) -> SessionResp:
    sess = db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, f"session {session_id} not found")
    user_id = sess.user_id
    repo.close_session(db, session_id)
    db.commit()

    # 广播: session_closed
    ws_manager.send_to_user(user_id, "session_closed", {
        "session_id": session_id,
    })

    return SessionResp.model_validate(sess)


@router.post("/{session_id}/aggregate")
def aggregate_session(session_id: int, db: Session = Depends(_get_db)) -> dict:
    """手动触发 Session 聚合, 返回 stats"""
    sess = db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, f"session {session_id} not found")
    user_id = sess.user_id
    db.close()  # aggregator 用自己的 session

    ws_manager.send_to_user(user_id, "session_aggregated", {
        "session_id": session_id, "status": "running",
    })

    summary = SessionAggregator().aggregate(session_id)
    return {"session_id": session_id, "stats": summary.to_dict()}


@router.post("/{session_id}/generate-training")
def generate_training(session_id: int, run_ai: bool = False, db: Session = Depends(_get_db)):
    """根据 session 统计 + (可选) AI 报告, 生成训练项"""
    sess = db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, f"session {session_id} not found")
    user_id = sess.user_id
    db.close()

    summary = SessionAggregator().aggregate(session_id)
    ai_report = None
    if run_ai:
        try:
            from app.llm.ai_coach import AICoach
            coach = AICoach()
            ai_report = coach.analyze(session_id, summary, user_level="未指定")
        except Exception as e:
            # 失败不阻塞, 训练项用规则生成
            ai_report = {"_error": str(e)}

    engine = TrainingRuleEngine()
    tasks = engine.generate(session_id, summary, ai_report=ai_report, user_id=user_id)
    return {
        "session_id": session_id,
        "ai_report": ai_report,
        "training_tasks": tasks,
    }


# ── helpers ────────────────────────────────────────────
def _to_ai_resp(ai: AIReport) -> AIReportResp:
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


def _to_task_resp(t: TrainingTask) -> TrainingTaskResp:
    try:
        config = json.loads(t.config_json) if t.config_json else {}
    except (TypeError, ValueError):
        config = {}
    try:
        result = json.loads(t.result_json) if t.result_json else {}
    except (TypeError, ValueError):
        result = {}
    return TrainingTaskResp(
        id=t.id, rule_id=t.rule_id, category=t.category, title=t.title,
        description=t.description, target_metric=t.target_metric,
        duration_min=t.duration_min, status=t.status,
        scheduled_for=t.scheduled_for, completed_at=t.completed_at,
        config=config, result=result,
    )
