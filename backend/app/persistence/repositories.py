"""
Repository 模式: 封装对 ORM 的访问, 业务层不直接写 SQL
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session

from app.persistence.models import (
    User, TrainingSession, Cube, MoveEvent, SolveStages,
    PauseEvent, SessionStats, AIReport, TrainingTask, DailyGoal,
    FormulaSet, FormulaCase, FormulaAlg,
)


# ── User ─────────────────────────────────────────────────
def get_or_create_user(s: Session, username: str, **kwargs) -> User:
    u = s.scalar(select(User).where(User.username == username))
    if u:
        return u
    u = User(username=username, **kwargs)
    s.add(u)
    s.flush()
    return u


# ── TrainingSession ─────────────────────────────────────
def get_open_session(s: Session, user_id: int) -> Optional[TrainingSession]:
    return s.scalar(
        select(TrainingSession)
        .where(TrainingSession.user_id == user_id, TrainingSession.status == "open")
        .order_by(TrainingSession.started_at.desc())
        .limit(1)
    )

def create_session(s: Session, user_id: int, target_size: int = 12, name: str | None = None) -> TrainingSession:
    sess = TrainingSession(
        user_id=user_id,
        target_size=target_size,
        name=name,
        started_at=func.now_ms() if False else int(__import__("time").time() * 1000),
        status="open",
    )
    s.add(sess)
    s.flush()
    return sess

def close_session(s: Session, session_id: int) -> None:
    sess = s.get(TrainingSession, session_id)
    if not sess:
        return
    sess.status = "closed"
    sess.ended_at = int(__import__("time").time() * 1000)

def increment_session_count(s: Session, session_id: int) -> None:
    sess = s.get(TrainingSession, session_id)
    if not sess:
        return
    sess.cube_count = (sess.cube_count or 0) + 1


# ── Cube ─────────────────────────────────────────────────
def create_cube(s: Session, **kwargs) -> Cube:
    c = Cube(**kwargs)
    s.add(c)
    s.flush()
    return c

def get_cube(s: Session, cube_id: int) -> Optional[Cube]:
    return s.get(Cube, cube_id)

def list_cubes_by_session(s: Session, session_id: int) -> list[Cube]:
    return list(s.scalars(
        select(Cube)
        .where(Cube.session_id == session_id)
        .order_by(Cube.started_at.asc())
    ))


# ── MoveEvent ────────────────────────────────────────────
def next_move_seq(s: Session, solve_id: int) -> int:
    cur = s.scalar(select(func.coalesce(func.max(MoveEvent.seq), -1)).where(MoveEvent.solve_id == solve_id))
    # coalesce 已保证 NULL → -1, 所以 cur 一定不是 None
    return int(cur) + 1

def add_move(s: Session, **kwargs) -> MoveEvent:
    m = MoveEvent(**kwargs)
    s.add(m)
    s.flush()
    return m

def list_moves(s: Session, solve_id: int) -> list[MoveEvent]:
    return list(s.scalars(
        select(MoveEvent).where(MoveEvent.solve_id == solve_id).order_by(MoveEvent.seq)
    ))

def backfill_move_stages(s: Session, solve_id: int, stage_ranges: dict[str, tuple[int, int]]) -> int:
    """
    stage_ranges = {"cross": (0, 1500), "f2l": (1500, 7600), ...}
    把每个 move 的 stage_label 回填
    """
    moves = list_moves(s, solve_id)
    n = 0
    for m in moves:
        for label, (lo, hi) in stage_ranges.items():
            if lo <= m.timestamp_ms <= hi:
                m.stage_label = label
                n += 1
                break
    s.flush()
    return n


# ── SolveStages ──────────────────────────────────────────
def upsert_stages(s: Session, solve_id: int, **kwargs) -> SolveStages:
    obj = s.scalar(select(SolveStages).where(SolveStages.solve_id == solve_id))
    if obj:
        for k, v in kwargs.items():
            setattr(obj, k, v)
    else:
        obj = SolveStages(solve_id=solve_id, **kwargs)
        s.add(obj)
    s.flush()
    return obj


# ── PauseEvent ───────────────────────────────────────────
def replace_pauses(s: Session, solve_id: int, pauses: list[dict]) -> int:
    s.execute(delete(PauseEvent).where(PauseEvent.solve_id == solve_id))
    for p in pauses:
        s.add(PauseEvent(solve_id=solve_id, **p))
    s.flush()
    return len(pauses)

def list_pauses_by_session(s: Session, session_id: int) -> list[PauseEvent]:
    return list(s.scalars(
        select(PauseEvent).join(Cube, PauseEvent.solve_id == Cube.id)
        .where(Cube.session_id == session_id)
        .order_by(PauseEvent.solve_id, PauseEvent.seq)
    ))


# ── SessionStats ─────────────────────────────────────────
def upsert_session_stats(s: Session, session_id: int, **kwargs) -> SessionStats:
    obj = s.scalar(select(SessionStats).where(SessionStats.session_id == session_id))
    if obj:
        for k, v in kwargs.items():
            setattr(obj, k, v)
    else:
        obj = SessionStats(session_id=session_id, **kwargs)
        s.add(obj)
    s.flush()
    return obj


# ── AIReport ─────────────────────────────────────────────
def create_ai_report(s: Session, **kwargs) -> AIReport:
    a = AIReport(**kwargs)
    s.add(a)
    s.flush()
    return a

def latest_ai_for_session(s: Session, session_id: int) -> Optional[AIReport]:
    return s.scalar(
        select(AIReport)
        .where(AIReport.session_id == session_id, AIReport.status == "ok")
        .order_by(AIReport.created_at.desc())
        .limit(1)
    )


# ── TrainingTask ─────────────────────────────────────────
def add_training_task(s: Session, **kwargs) -> TrainingTask:
    t = TrainingTask(**kwargs)
    s.add(t)
    s.flush()
    return t

def add_training_tasks(s: Session, tasks: list[dict]) -> list[int]:
    ids = []
    for t in tasks:
        obj = TrainingTask(**t)
        s.add(obj)
        s.flush()
        ids.append(obj.id)
    return ids

def list_tasks_for_user_today(s: Session, user_id: int) -> list[TrainingTask]:
    # 简化: 查 created_at 在今日的所有任务
    import time
    day_start = (int(time.time()) // 86400) * 86400 * 1000
    return list(s.scalars(
        select(TrainingTask)
        .where(TrainingTask.user_id == user_id, TrainingTask.created_at >= day_start)
        .order_by(TrainingTask.created_at.asc())
    ))

def task_exists_recent(s: Session, user_id: int, rule_id: str, since_ms: int) -> bool:
    return s.scalar(
        select(func.count(TrainingTask.id))
        .where(TrainingTask.user_id == user_id,
               TrainingTask.rule_id == rule_id,
               TrainingTask.created_at >= since_ms)
    ) > 0


# ── DailyGoal ────────────────────────────────────────────
def get_today_goal(s: Session, user_id: int, today_zero_ms: int) -> Optional[DailyGoal]:
    return s.scalar(
        select(DailyGoal)
        .where(DailyGoal.user_id == user_id, DailyGoal.goal_date == today_zero_ms)
    )

def upsert_daily_goal(s: Session, user_id: int, goal_date: int, **kwargs) -> DailyGoal:
    g = get_today_goal(s, user_id, goal_date)
    if g:
        for k, v in kwargs.items():
            setattr(g, k, v)
    else:
        g = DailyGoal(user_id=user_id, goal_date=goal_date, **kwargs)
        s.add(g)
    s.flush()
    return g


# ── Formula Library ─────────────────────────────────────────
def list_formula_sets(s: Session) -> list[FormulaSet]:
    return list(s.scalars(
        select(FormulaSet).order_by(FormulaSet.code)
    ))


def get_formula_set_by_code(s: Session, code: str) -> Optional[FormulaSet]:
    return s.scalar(select(FormulaSet).where(FormulaSet.code == code))


def get_formula_set_with_cases(s: Session, code: str) -> Optional[FormulaSet]:
    fset = get_formula_set_by_code(s, code)
    if not fset:
        return None
    # 预加载 cases.algs
    _ = list(fset.cases)  # trigger lazy load
    return fset


def get_formula_case(s: Session, case_id: int) -> Optional[FormulaCase]:
    return s.get(FormulaCase, case_id)


def search_formula_cases(s: Session, q: str, *, set_code: str | None = None, limit: int = 50) -> list[FormulaCase]:
    stmt = select(FormulaCase)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(FormulaCase.name).like(like) | func.lower(FormulaCase.code).like(like))
    if set_code:
        stmt = stmt.join(FormulaSet, FormulaCase.set_id == FormulaSet.id).where(FormulaSet.code == set_code)
    stmt = stmt.order_by(FormulaCase.id).limit(limit)
    return list(s.scalars(stmt))


def list_formula_cases_by_set(s: Session, set_code: str) -> list[FormulaCase]:
    """按 set code 拿全部 case, 顺序按 position_in_set"""
    return list(s.scalars(
        select(FormulaCase)
        .join(FormulaSet, FormulaCase.set_id == FormulaSet.id)
        .where(FormulaSet.code == set_code)
        .order_by(FormulaCase.position_in_set)
    ))


def formula_case_ids_by_codes(s: Session, set_code: str, codes: list[str]) -> list[int]:
    """按 (set, code) 拿 id 列表, 保持输入顺序, 找不到的跳过"""
    if not codes:
        return []
    cases = list_formula_cases_by_set(s, set_code)
    by_code = {c.code: c.id for c in cases}
    return [by_code[c] for c in codes if c in by_code]
