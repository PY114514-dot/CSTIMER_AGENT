"""
cstimer 数据导入器
参考 cstimer export.js 的 JSON 格式: { properties, session1, session2, ... }
times[i] = [time, scramble, comment, date_offset, extension?]
time[0] = penalty (0 / 2000 / -1)
time[1..n] = cumulative phase end-time in ms
"""
from __future__ import annotations
import json
import time
from typing import Iterable
from sqlalchemy.orm import Session

from app.persistence import repositories as repo
from app.persistence import db as _db_mod
from app.persistence.models import (
    User, TrainingSession, Cube, MoveEvent, SolveStages, PauseEvent,
    now_ms,
)


def _ms(sec: int) -> int:
    """cstimer 的 date_offset 单位是秒"""
    return sec * 1000 if sec else 0


def _now_ms() -> int:
    return int(time.time() * 1000)


def import_user(s: Session, username: str = "imported", display_name: str | None = None) -> User:
    return repo.get_or_create_user(s, username, display_name=display_name)


def _open_or_create_session(s: Session, user_id: int, target_size: int = 12) -> TrainingSession:
    sess = repo.get_open_session(s, user_id)
    if sess:
        return sess
    return repo.create_session(s, user_id=user_id, target_size=target_size,
                                name=f"imported-{_now_ms()}")


def import_session_data(s: Session,
                        user: User,
                        session_index: int,
                        times: list[list],
                        default_target_size: int = 12,
                        ) -> TrainingSession:
    """
    导入一个 cstimer session 的 times 数组
    """
    sess = _open_or_create_session(s, user.id, default_target_size)

    base_time = _now_ms() - len(times) * 20_000   # 倒推 20s/把
    cum_offset = 0

    for idx, t in enumerate(times):
        if not t or not isinstance(t, list):
            continue
        if len(t) < 2:
            continue
        time_arr = t[0]
        scramble = t[1] if len(t) > 1 else ""
        comment = t[2] if len(t) > 2 else ""
        date_offset = t[3] if len(t) > 3 else 0

        # time_arr 形态: [penalty, total_ms] 或 [penalty, phaseN, ..., phase1]
        # 但某些 cstimer 配置下 time_arr 直接是数字
        if isinstance(time_arr, list):
            if len(time_arr) < 1:
                continue
            penalty = time_arr[0] or 0
            total_ms = time_arr[-1] or 0
        elif isinstance(time_arr, (int, float)):
            penalty = 0
            total_ms = int(time_arr)
        else:
            continue
        is_dnf = (penalty == -1)

        started_at = base_time + idx * 20_000
        ended_at = started_at + int(total_ms)

        cube = repo.create_cube(
            s,
            user_id=user.id,
            session_id=sess.id,
            puzzle_type="333",
            scramble=scramble or "(no scramble)",
            started_at=started_at,
            ended_at=ended_at,
            total_time_ms=int(total_ms),
            penalty_ms=int(penalty),
            move_count=0,  # cstimer 不存 move 序列, 留 0
            is_dnf=is_dnf,
            notes=comment,
            source="cstimer_import",
        )
        sess.cube_count = (sess.cube_count or 0) + 1

    s.flush()
    return sess


def parse_export_json(path: str) -> dict:
    """读取 cstimer 导出的 .json 文件, 返回 {session_idx_int: [times...] }"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sessions: dict[int, list] = {}
    for k, v in data.items():
        if k.startswith("session") and k[len("session"):].isdigit():
            idx = int(k[len("session"):])
            sessions[idx] = v
    return {
        "properties": data.get("properties", {}),
        "sessions": sessions,
    }


def import_from_file(path: str, username: str = "imported") -> list[TrainingSession]:
    parsed = parse_export_json(path)
    out: list[TrainingSession] = []
    with _db_mod.SessionLocal() as s:
        user = import_user(s, username)
        for idx, times in parsed["sessions"].items():
            if not times:
                continue
            sess = import_session_data(s, user, idx, times)
            out.append(sess)
        s.commit()
    return out
