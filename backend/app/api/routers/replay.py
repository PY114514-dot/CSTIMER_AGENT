"""
复盘 + CSV 导出路由
  GET /api/sessions/{sid}/replay          -> JSON: 每 cube 详细 (moves + pauses + stages)
  GET /api/sessions/{sid}/export.csv      -> CSV 下载 (UTF-8 BOM)
  GET /api/dashboard/export/today.csv     -> 今日 dashboard 一行 CSV
"""
from __future__ import annotations
import csv
import io
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.persistence import repositories as repo
from app.persistence.db import SessionLocal
from app.persistence.models import (
    TrainingSession, Cube, MoveEvent, PauseEvent, SolveStages,
    SessionStats, AIReport, TrainingTask, DailyGoal,
)


router = APIRouter(tags=["replay"])


def _get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


# ── 复盘 ──────────────────────────────────────────────
@router.get("/api/sessions/{session_id}/replay")
def get_session_replay(session_id: int, db: Session = Depends(_get_db)):
    """每个 cube 的逐动 + 停顿 + 阶段时间窗 (前端 3D 回放用)"""
    sess = db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, f"session {session_id} not found")

    cubes = list(db.scalars(
        select(Cube).where(Cube.session_id == session_id).order_by(Cube.started_at)
    ))

    cube_payloads = []
    for c in cubes:
        # moves
        moves = list(db.scalars(
            select(MoveEvent).where(MoveEvent.solve_id == c.id).order_by(MoveEvent.seq)
        ))
        # pauses
        pauses = list(db.scalars(
            select(PauseEvent).where(PauseEvent.solve_id == c.id).order_by(PauseEvent.seq)
        ))
        # stages
        st = db.scalar(select(SolveStages).where(SolveStages.solve_id == c.id))
        cube_payloads.append({
            "solve_id": c.id,
            "seq": cubes.index(c) + 1,
            "scramble": c.scramble,
            "started_at": c.started_at,
            "ended_at": c.ended_at,
            "total_time_ms": c.total_time_ms,
            "penalty_ms": c.penalty_ms,
            "is_dnf": c.is_dnf,
            "notes": c.notes,
            "move_count": c.move_count,
            "moves": [
                {"seq": m.seq, "move": m.move_text, "timestamp_ms": m.timestamp_ms,
                 "stage_label": m.stage_label}
                for m in moves
            ],
            "pauses": [
                {"seq": p.seq, "start_ms": p.start_ms, "end_ms": p.end_ms,
                 "duration_ms": p.duration_ms, "before_seq": p.before_move_seq,
                 "after_seq": p.after_move_seq, "stage_label": p.stage_label,
                 "type": p.type}
                for p in pauses
            ],
            "stages": {
                "cross_dur_ms": st.cross_dur_ms if st else None,
                "f2l_dur_ms":   st.f2l_dur_ms   if st else None,
                "oll_dur_ms":   st.oll_dur_ms   if st else None,
                "pll_dur_ms":   st.pll_dur_ms   if st else None,
                "f2l_pairs":    st.f2l_pairs    if st else None,
                "confidence":   st.confidence   if st else None,
            } if st else None,
        })

    stats = db.scalar(select(SessionStats).where(SessionStats.session_id == session_id))
    ai = db.scalar(
        select(AIReport)
        .where(AIReport.session_id == session_id, AIReport.status == "ok")
        .order_by(desc(AIReport.created_at)).limit(1)
    )

    return {
        "session": {
            "id": sess.id, "user_id": sess.user_id, "name": sess.name,
            "target_size": sess.target_size, "started_at": sess.started_at,
            "ended_at": sess.ended_at, "cube_count": sess.cube_count, "status": sess.status,
        },
        "stats": stats.to_dict() if stats and hasattr(stats, "to_dict") else None,
        "ai_report": {
            "id": ai.id, "model": ai.model, "bottleneck": ai.bottleneck,
            "confidence": ai.confidence, "parsed": ai.parsed_json,
            "created_at": ai.created_at,
        } if ai else None,
        "cubes": cube_payloads,
    }


# ── CSV 导出 ──────────────────────────────────────────
def _to_csv_bytes(rows: list[dict], fieldnames: list[str]) -> bytes:
    """带 UTF-8 BOM (Excel 友好)"""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        # 展平 dict (一维)
        flat = {}
        for k, v in r.items():
            if isinstance(v, (dict, list)):
                import json
                flat[k] = json.dumps(v, ensure_ascii=False)
            else:
                flat[k] = v
        writer.writerow(flat)
    # BOM 让 Excel 正确识别 UTF-8
    return ("﻿" + buf.getvalue()).encode("utf-8")


@router.get("/api/sessions/{session_id}/export.csv")
def export_session_csv(session_id: int, db: Session = Depends(_get_db)):
    """一个 session 的所有 solve 一行一条"""
    sess = db.get(TrainingSession, session_id)
    if not sess:
        raise HTTPException(404, f"session {session_id} not found")
    cubes = list(db.scalars(
        select(Cube).where(Cube.session_id == session_id).order_by(Cube.started_at)
    ))

    rows = []
    for idx, c in enumerate(cubes, start=1):
        st = db.scalar(select(SolveStages).where(SolveStages.solve_id == c.id))
        rows.append({
            "seq": idx,
            "solve_id": c.id,
            "started_at_iso": datetime.fromtimestamp(c.started_at/1000, tz=timezone.utc).isoformat() if c.started_at else "",
            "scramble": c.scramble,
            "total_time_ms": c.total_time_ms,
            "penalty_ms": c.penalty_ms,
            "is_dnf": c.is_dnf,
            "move_count": c.move_count,
            "cross_ms":  st.cross_dur_ms if st else "",
            "f2l_ms":    st.f2l_dur_ms   if st else "",
            "oll_ms":    st.oll_dur_ms   if st else "",
            "pll_ms":    st.pll_dur_ms   if st else "",
            "f2l_pairs": st.f2l_pairs    if st else "",
            "stage_confidence": st.confidence if st else "",
            "notes": c.notes or "",
            "source": c.source,
        })
    body = _to_csv_bytes(rows, [
        "seq", "solve_id", "started_at_iso", "scramble",
        "total_time_ms", "penalty_ms", "is_dnf", "move_count",
        "cross_ms", "f2l_ms", "oll_ms", "pll_ms", "f2l_pairs", "stage_confidence",
        "notes", "source",
    ])
    fname = f"session_{session_id}_solves.csv"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/dashboard/export/today.csv")
def export_today_csv(user_id: int, db: Session = Depends(_get_db)):
    """今日 dashboard 一行 (含 daily goal / AI 摘要 / 训练项计数)"""
    day_zero = _today_zero_ms()
    goal = db.scalar(
        select(DailyGoal).where(DailyGoal.user_id == user_id, DailyGoal.goal_date == day_zero)
    )
    cur = repo.get_open_session(db, user_id)
    ai = db.scalar(
        select(AIReport).where(AIReport.user_id == user_id, AIReport.status == "ok")
        .order_by(desc(AIReport.created_at)).limit(1)
    )
    today_tasks = list(db.scalars(
        select(TrainingTask).where(TrainingTask.user_id == user_id, TrainingTask.created_at >= day_zero)
    ))
    done = sum(1 for t in today_tasks if t.status == "done")

    rows = [{
        "user_id": user_id,
        "date_iso": datetime.fromtimestamp(day_zero/1000, tz=timezone.utc).date().isoformat(),
        "goal_kind":   goal.target_kind   if goal else "",
        "goal_value":  goal.target_value  if goal else "",
        "goal_completed": goal.completed_value if goal else "",
        "goal_achieved":  goal.is_achieved     if goal else "",
        "current_session_id":   cur.id          if cur else "",
        "current_session_count": cur.cube_count if cur else "",
        "latest_ai_bottleneck":  ai.bottleneck   if ai else "",
        "latest_ai_confidence":  ai.confidence   if ai else "",
        "training_tasks_total":  len(today_tasks),
        "training_tasks_done":    done,
    }]
    body = _to_csv_bytes(rows, [
        "user_id", "date_iso",
        "goal_kind", "goal_value", "goal_completed", "goal_achieved",
        "current_session_id", "current_session_count",
        "latest_ai_bottleneck", "latest_ai_confidence",
        "training_tasks_total", "training_tasks_done",
    ])
    fname = f"dashboard_{user_id}_{day_zero}.csv"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/api/training-export.csv")
def export_training_csv(user_id: int, db: Session = Depends(_get_db)):
    """某用户所有训练项 (含 config_json) 一行一条.
    路径用 training-export.csv (连字符) 避开 training.py 里的 /{task_id} 数字路由冲突"""
    rows = list(db.scalars(
        select(TrainingTask).where(TrainingTask.user_id == user_id)
        .order_by(TrainingTask.created_at)
    ))
    data = []
    for t in rows:
        data.append({
            "id": t.id, "category": t.category, "rule_id": t.rule_id or "",
            "title": t.title, "description": t.description or "",
            "target_metric": t.target_metric or "",
            "duration_min": t.duration_min or "",
            "status": t.status,
            "scheduled_for_iso": (datetime.fromtimestamp(t.scheduled_for/1000, tz=timezone.utc).date().isoformat()
                                  if t.scheduled_for else ""),
            "completed_at_iso":  (datetime.fromtimestamp(t.completed_at/1000, tz=timezone.utc).isoformat()
                                  if t.completed_at else ""),
            "config_json": t.config_json or "",
            "result_json": t.result_json or "",
            "created_at_iso": (datetime.fromtimestamp(t.created_at/1000, tz=timezone.utc).isoformat()
                               if t.created_at else ""),
        })
    body = _to_csv_bytes(data, [
        "id", "category", "rule_id", "title", "description", "target_metric",
        "duration_min", "status", "scheduled_for_iso", "completed_at_iso",
        "config_json", "result_json", "created_at_iso",
    ])
    fname = f"training_tasks_user_{user_id}.csv"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _today_zero_ms() -> int:
    t = time.gmtime()
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, 0)) * 1000)
