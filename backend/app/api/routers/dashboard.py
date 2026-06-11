"""
Dashboard Router: 今日看板 (前端首页用)
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session

from app.api.schemas import (
    TodayDashboardResp, DailyGoalResp, SessionResp, AIReportResp,
    TrainingTaskResp,
)
from app.domain.daily_goal import DailyGoalManager
from app.persistence import repositories as repo
from app.persistence.db import SessionLocal
from app.persistence.models import (
    TrainingSession, Cube, SolveStages, SessionStats, AIReport,
    TrainingTask, DailyGoal,
)


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _today_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _today_zero_ms() -> int:
    t = time.gmtime()
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, 0)) * 1000)


@router.get("/today", response_model=TodayDashboardResp)
def get_today(user_id: int = Query(...), db: Session = Depends(_get_db)) -> TodayDashboardResp:
    # 1. 今日目标
    day = _today_zero_ms()
    goal = repo.get_today_goal(db, user_id, day)
    daily_goal = None
    if goal:
        ratio = goal.completed_value / goal.target_value if goal.target_value else 0
        daily_goal = DailyGoalResp(
            id=goal.id, goal_date=goal.goal_date,
            target_kind=goal.target_kind, target_value=goal.target_value,
            completed_value=goal.completed_value, is_achieved=goal.is_achieved,
            recommended=goal.recommended, achievement_ratio=ratio,
        )

    # 2. 当前 open session + stats
    current = repo.get_open_session(db, user_id)
    current_resp = SessionResp.model_validate(current) if current else None
    stats_dict = None
    stage_breakdown: list[dict] = []
    pause_heatmap: list[dict] = []
    if current:
        # 自动聚合 (如果没 stats)
        s_obj = db.get(SessionStats, current.id)
        if not s_obj:
            db.close()
            from app.domain.session_aggregator import SessionAggregator
            summary = SessionAggregator().aggregate(current.id)
            stats_dict = summary.to_dict()
            # 重新拿 session 用于后续 cubes
            db = SessionLocal()
            current = db.get(TrainingSession, current.id)
        else:
            stats_dict = s_obj.to_dict() if hasattr(s_obj, "to_dict") else None

        if stats_dict:
            # stage breakdown
            cubes = list(db.scalars(
                select(Cube).where(Cube.session_id == current.id).order_by(Cube.started_at)
            ))
            for c in cubes:
                st = db.scalar(select(SolveStages).where(SolveStages.solve_id == c.id))
                stage_breakdown.append({
                    "solve_id": c.id,
                    "seq": c.id,
                    "cross_ms": st.cross_dur_ms if st else None,
                    "f2l_ms":   st.f2l_dur_ms   if st else None,
                    "oll_ms":   st.oll_dur_ms   if st else None,
                    "pll_ms":   st.pll_dur_ms   if st else None,
                })

            # pause heatmap: 简化为各 solve 的 pause 总时长
            for c in cubes:
                from app.persistence.models import PauseEvent
                pauses = list(db.scalars(
                    select(PauseEvent).where(PauseEvent.solve_id == c.id)
                ))
                # 16 个 1s 时间窗
                bins = [0] * 16
                for p in pauses:
                    idx = min(15, p.start_ms // 1000)
                    bins[idx] += p.duration_ms
                pause_heatmap.append({
                    "solve_id": c.id,
                    "bins_ms": bins,
                })

    # 3. 最新 AI 报告 (从任何 session 选最近一个)
    ai = db.scalar(
        select(AIReport)
        .where(AIReport.user_id == user_id, AIReport.status == "ok")
        .order_by(desc(AIReport.created_at)).limit(1)
    )
    ai_resp = None
    if ai:
        try:
            parsed = json.loads(ai.parsed_json) if ai.parsed_json else {}
        except (TypeError, ValueError):
            parsed = {}
        ai_resp = AIReportResp(
            id=ai.id, session_id=ai.session_id, user_id=ai.user_id,
            model=ai.model, prompt_version=ai.prompt_version,
            bottleneck=ai.bottleneck, confidence=ai.confidence,
            parsed=parsed, created_at=ai.created_at,
        )

    # 4. 今日训练项
    tasks = list(db.scalars(
        select(TrainingTask)
        .where(TrainingTask.user_id == user_id,
               TrainingTask.created_at >= day)
        .order_by(TrainingTask.created_at)
    ))
    task_resps = []
    for t in tasks:
        try:
            config = json.loads(t.config_json) if t.config_json else {}
        except (TypeError, ValueError):
            config = {}
        task_resps.append(TrainingTaskResp(
            id=t.id, rule_id=t.rule_id, category=t.category, title=t.title,
            description=t.description, target_metric=t.target_metric,
            duration_min=t.duration_min, status=t.status,
            scheduled_for=t.scheduled_for, completed_at=t.completed_at,
            config=config, result={},
        ))

    # 5. 历史趋势 (近 30 个 session)
    from app.api.routers.sessions import _to_ai_resp, _to_task_resp
    trend_sessions = list(db.scalars(
        select(TrainingSession)
        .where(TrainingSession.user_id == user_id,
               TrainingSession.status != "open")
        .order_by(desc(TrainingSession.ended_at))
        .limit(30)
    ))
    trend_30 = []
    for s in trend_sessions:
        st = db.scalar(select(SessionStats).where(SessionStats.session_id == s.id))
        trend_30.append({
            "session_id": s.id,
            "closed_at": s.ended_at,
            "avg3_ms": st.avg3_ms if st else None,
            "avg5_ms": st.avg5_ms if st else None,
        })

    return TodayDashboardResp(
        date=_today_str(),
        daily_goal=daily_goal,
        current_session=current_resp,
        latest_ai_report=ai_resp,
        training_tasks=task_resps,
        stage_breakdown=stage_breakdown,
        pause_heatmap=pause_heatmap,
        trend_30=trend_30,
    )


@router.post("/recommend-goal")
def recommend_goal(user_id: int = Query(...), db: Session = Depends(_get_db)) -> dict:
    """推荐/更新今日目标"""
    db.close()
    return DailyGoalManager().recommend_for_today(user_id)
