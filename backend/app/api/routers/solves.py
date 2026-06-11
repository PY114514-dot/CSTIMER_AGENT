"""
Solves Router: start / move / finish
"""
from __future__ import annotations
import asyncio
import time
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.api.schemas import (
    SolveStartReq, MoveReq, SolveResp, MoveAck, SolveFinishResp,
)
from app.api.ws import ws_manager
from app.domain.solve_recorder import SolveRecorder
from app.domain.cube_model import parse_move, generate_random_scramble
from app.persistence import repositories as repo
from app.persistence.db import SessionLocal


router = APIRouter(prefix="/api/solves", tags=["solves"])


def _get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _now_ms() -> int:
    return int(time.time() * 1000)


@router.post("/start", response_model=SolveResp)
def start_solve(req: SolveStartReq, db: Session = Depends(_get_db)) -> SolveResp:
    """开始一次 solve: 创建 cube + 返回 scramble, 前端开始计时"""
    user = db.get(__import__("app.persistence.models", fromlist=["User"]).User, req.user_id)
    if not user:
        raise HTTPException(404, f"user {req.user_id} not found")

    # session: 用现有 open session 或新建
    sess = None
    if req.session_id:
        sess = db.get(__import__("app.persistence.models", fromlist=["TrainingSession"]).TrainingSession, req.session_id)
        if not sess or sess.user_id != req.user_id:
            raise HTTPException(404, f"session {req.session_id} not found")
    if not sess:
        sess = repo.get_open_session(db, req.user_id)
    if not sess:
        sess = repo.create_session(db, user_id=req.user_id, target_size=12,
                                    name=f"auto-{_now_ms()}")

    scramble = req.scramble or generate_random_scramble()
    cube = repo.create_cube(
        db,
        user_id=req.user_id,
        session_id=sess.id,
        puzzle_type=req.puzzle_type,
        scramble=scramble,
        started_at=_now_ms(),
        ended_at=_now_ms(),
        total_time_ms=0,
        move_count=0,
    )
    db.commit()

    # 广播: solve_started
    ws_manager.send_to_user(req.user_id, "solve_started", {
        "cube_id": cube.id, "session_id": sess.id,
        "scramble": scramble, "started_at": cube.started_at,
    })
    if sess.id:
        ws_manager.send_to_session(sess.id, "solve_started", {
            "cube_id": cube.id, "scramble": scramble,
        })

    return SolveResp(
        cube_id=cube.id,
        session_id=sess.id,
        scramble=scramble,
        started_at=cube.started_at,
    )


@router.post("/{cube_id}/moves", response_model=MoveAck)
def add_move(cube_id: int, req: MoveReq, db: Session = Depends(_get_db)) -> MoveAck:
    """录入一次转动 (前端按键时调用)"""
    try:
        mv = parse_move(req.move)
    except ValueError as e:
        raise HTTPException(400, f"invalid move: {e}")

    cube = repo.get_cube(db, cube_id)
    if not cube:
        raise HTTPException(404, f"solve {cube_id} not found")

    seq = repo.next_move_seq(db, cube_id)
    ts = req.timestamp_ms if req.timestamp_ms is not None else (_now_ms() - cube.started_at)
    repo.add_move(
        db,
        solve_id=cube_id,
        seq=seq,
        move_text=str(mv),
        is_smart_turn=req.is_smart_turn,
        timestamp_ms=ts,
        absolute_ms=cube.started_at + ts,
    )
    db.commit()

    # 广播: move_recorded
    ws_manager.send_to_user(cube.user_id, "move_recorded", {
        "cube_id": cube_id, "seq": seq, "move": str(mv),
        "timestamp_ms": ts, "session_id": cube.session_id,
    })
    if cube.session_id:
        ws_manager.send_to_session(cube.session_id, "move_recorded", {
            "cube_id": cube_id, "seq": seq, "move": str(mv),
        })

    return MoveAck(seq=seq, move=str(mv), timestamp_ms=ts)


@router.post("/{cube_id}/finish", response_model=SolveFinishResp)
def finish_solve(cube_id: int, db: Session = Depends(_get_db)) -> SolveFinishResp:
    """完成 solve: 触发阶段识别 / 停顿分析 / Session 计数"""
    cube = repo.get_cube(db, cube_id)
    if not cube:
        raise HTTPException(404, f"solve {cube_id} not found")
    user_id = cube.user_id
    session_id = cube.session_id
    db.close()  # 让 recorder 用自己的 session

    recorder = SolveRecorder()
    result = recorder.finish_solve(cube_id)

    # 广播: solve_finished
    ws_manager.send_to_user(user_id, "solve_finished", {
        "cube_id": cube_id, "session_id": session_id,
        "total_time_ms": result["total_time_ms"],
        "move_count": result["move_count"],
        "pause_count": result["pause_count"],
        "stage_confidence": result["stage_confidence"],
    })
    if session_id:
        ws_manager.send_to_session(session_id, "solve_finished", {
            "cube_id": cube_id, "total_time_ms": result["total_time_ms"],
            "move_count": result["move_count"],
            "pause_count": result["pause_count"],
        })

    return SolveFinishResp(
        cube_id=result["cube_id"],
        session_id=result["session_id"],
        total_time_ms=result["total_time_ms"],
        move_count=result["move_count"],
        stage_confidence=result["stage_confidence"],
        pause_count=result["pause_count"],
    )
