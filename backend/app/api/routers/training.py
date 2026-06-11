"""
Training Router: 训练项查询/完成
"""
from __future__ import annotations
import json
import time
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import TrainingTaskResp, TrainingTaskDoneReq
from app.persistence import repositories as repo
from app.persistence.db import SessionLocal
from app.persistence.models import TrainingTask


router = APIRouter(prefix="/api/training", tags=["training"])


def _get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_resp(t: TrainingTask) -> TrainingTaskResp:
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


@router.get("/today", response_model=list[TrainingTaskResp])
def list_today(user_id: int = Query(...), db: Session = Depends(_get_db)):
    tasks = repo.list_tasks_for_user_today(db, user_id)
    return [_to_resp(t) for t in tasks]


@router.get("/{task_id}", response_model=TrainingTaskResp)
def get_task(task_id: int, db: Session = Depends(_get_db)):
    t = db.get(TrainingTask, task_id)
    if not t:
        raise HTTPException(404, f"task {task_id} not found")
    return _to_resp(t)


@router.post("/{task_id}/done", response_model=TrainingTaskResp)
def mark_done(task_id: int, req: TrainingTaskDoneReq, db: Session = Depends(_get_db)):
    t = db.get(TrainingTask, task_id)
    if not t:
        raise HTTPException(404, f"task {task_id} not found")
    t.status = "done"
    t.completed_at = _now_ms()
    t.result_json = json.dumps(req.result, ensure_ascii=False)
    db.commit()
    return _to_resp(t)


@router.post("/{task_id}/skip", response_model=TrainingTaskResp)
def mark_skip(task_id: int, db: Session = Depends(_get_db)):
    t = db.get(TrainingTask, task_id)
    if not t:
        raise HTTPException(404, f"task {task_id} not found")
    t.status = "skipped"
    db.commit()
    return _to_resp(t)
