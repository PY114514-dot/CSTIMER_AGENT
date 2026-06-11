"""
Session 聚合器

参考 cstimer stats/timestat.js 的 TimeStat (mean/avg, trim, DNF 传播)
但增加了 AI 分析所需的 stage / pause 维度汇总
"""
from __future__ import annotations
import json
import math
import statistics
from dataclasses import dataclass
from typing import Iterable

from app.persistence.models import Cube
from app.persistence.repositories import list_moves, list_pauses_by_session
from app.persistence.db import SessionLocal


@dataclass
class SessionSummary:
    session_id: int
    solve_count: int
    dnf_count: int
    avg_total_ms: int | None
    best_ms: int | None
    worst_ms: int | None
    std_dev_ms: int | None
    avg3_ms: int | None
    avg5_ms: int | None
    avg12_ms: int | None
    avg_cross_ms: int | None
    avg_f2l_ms:   int | None
    avg_oll_ms:   int | None
    avg_pll_ms:   int | None
    avg_moves: float | None
    avg_pause_ms: int | None
    pause_count: int | None
    pause_stage_dist: dict[str, float]
    pause_type_dist: dict[str, float]
    speed_trend: float | None
    first_half_ms: int | None
    second_half_ms: int | None
    longest_pause_ms: int | None
    longest_pause_stage: str | None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "solve_count": self.solve_count,
            "dnf_count": self.dnf_count,
            "avg_total_ms": self.avg_total_ms,
            "best_ms": self.best_ms,
            "worst_ms": self.worst_ms,
            "std_dev_ms": self.std_dev_ms,
            "avg3_ms": self.avg3_ms,
            "avg5_ms": self.avg5_ms,
            "avg12_ms": self.avg12_ms,
            "avg_cross_ms": self.avg_cross_ms,
            "avg_f2l_ms": self.avg_f2l_ms,
            "avg_oll_ms": self.avg_oll_ms,
            "avg_pll_ms": self.avg_pll_ms,
            "avg_moves": self.avg_moves,
            "avg_pause_ms": self.avg_pause_ms,
            "pause_count": self.pause_count,
            "pause_stage_dist": self.pause_stage_dist,
            "pause_type_dist": self.pause_type_dist,
            "speed_trend": self.speed_trend,
            "first_half_ms": self.first_half_ms,
            "second_half_ms": self.second_half_ms,
            "longest_pause_ms": self.longest_pause_ms,
            "longest_pause_stage": self.longest_pause_stage,
        }


def _trimmed_mean(xs: list[int], trim: int) -> int | None:
    if not xs:
        return None
    if len(xs) <= trim * 2:
        return int(statistics.mean(xs))
    s = sorted(xs)
    return int(statistics.mean(s[trim:-trim]) if (s[trim:-trim]) else 0)


def _mean_or_none(xs: list[int]) -> int | None:
    return int(statistics.mean(xs)) if xs else None


class SessionAggregator:
    """汇总一个 Session 的所有指标"""

    def aggregate(self, session_id: int) -> SessionSummary:
        with SessionLocal() as s:
            from app.persistence.models import TrainingSession, SolveStages
            sess = s.get(TrainingSession, session_id)
            if not sess:
                raise ValueError(f"session {session_id} not found")
            cubes: list[Cube] = list(s.scalars(
                __import__("sqlalchemy").select(Cube)
                .where(Cube.session_id == session_id)
                .order_by(Cube.started_at.asc())
            ))

            ok_cubes = [c for c in cubes if not c.is_dnf and c.penalty_ms != -1]
            dnf_count = len(cubes) - len(ok_cubes)

            totals = [c.total_time_ms for c in ok_cubes]
            stages = [c.stages for c in ok_cubes if c.stages]
            pauses = list_pauses_by_session(s, session_id)

            # 阶段均值
            avg_cross = _mean_or_none([st.cross_dur_ms for st in stages if st and st.cross_dur_ms is not None])
            avg_f2l   = _mean_or_none([st.f2l_dur_ms   for st in stages if st and st.f2l_dur_ms   is not None])
            avg_oll   = _mean_or_none([st.oll_dur_ms   for st in stages if st and st.oll_dur_ms   is not None])
            avg_pll   = _mean_or_none([st.pll_dur_ms   for st in stages if st and st.pll_dur_ms   is not None])

            avg_moves = (statistics.mean([c.move_count for c in ok_cubes])
                         if ok_cubes else None)

            # 停顿
            durations = [p.duration_ms for p in pauses]
            avg_pause = _mean_or_none(durations)
            stage_counter: dict[str, int] = {}
            type_counter: dict[str, int] = {}
            for p in pauses:
                key = p.stage_label or "post"
                stage_counter[key] = stage_counter.get(key, 0) + p.duration_ms
                type_counter[p.type] = type_counter.get(p.type, 0) + p.duration_ms
            total_pause = sum(stage_counter.values()) or 1
            stage_dist = {k: round(v / total_pause, 3) for k, v in stage_counter.items()}
            type_dist = {k: round(v / total_pause, 3) for k, v in type_counter.items()}

            # 速率趋势
            n = len(totals)
            first_half = second_half = None
            trend = None
            if n >= 2:
                half = n // 2
                first_half = int(statistics.mean(totals[:half]))
                second_half = int(statistics.mean(totals[half:]))
                trend = round(second_half / max(1, first_half), 3)

            longest = max(pauses, key=lambda p: p.duration_ms, default=None)

            # 标准差
            std_dev = int(statistics.pstdev(totals)) if len(totals) >= 2 else None

            summary = SessionSummary(
                session_id=session_id,
                solve_count=len(cubes),
                dnf_count=dnf_count,
                avg_total_ms=_mean_or_none(totals),
                best_ms=min(totals) if totals else None,
                worst_ms=max(totals) if totals else None,
                std_dev_ms=std_dev,
                avg3_ms=_trimmed_mean(totals, 1),
                avg5_ms=_trimmed_mean(totals, 2),
                avg12_ms=_trimmed_mean(totals, 2) if len(totals) >= 12 else None,
                avg_cross_ms=avg_cross,
                avg_f2l_ms=avg_f2l,
                avg_oll_ms=avg_oll,
                avg_pll_ms=avg_pll,
                avg_moves=avg_moves,
                avg_pause_ms=avg_pause,
                pause_count=len(pauses),
                pause_stage_dist=stage_dist,
                pause_type_dist=type_dist,
                speed_trend=trend,
                first_half_ms=first_half,
                second_half_ms=second_half,
                longest_pause_ms=longest.duration_ms if longest else None,
                longest_pause_stage=longest.stage_label if longest else None,
            )
        return summary
