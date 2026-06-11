"""
每日目标管理器 + 智能推荐
"""
from __future__ import annotations
import time
from typing import Optional

from app.persistence import repositories as repo
from app.persistence.db import SessionLocal


def _today_zero_ms_utc() -> int:
    t = time.gmtime()
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, 0)) * 1000)


class DailyGoalManager:
    DEFAULT_TARGET = 12

    def today_goal(self, user_id: int) -> Optional[dict]:
        day = _today_zero_ms_utc()
        with SessionLocal() as s:
            g = repo.get_today_goal(s, user_id, day)
        if not g:
            return None
        return {
            "id": g.id,
            "goal_date": g.goal_date,
            "target_kind": g.target_kind,
            "target_value": g.target_value,
            "completed_value": g.completed_value,
            "is_achieved": g.is_achieved,
            "recommended": g.recommended,
            "achievement_ratio": (g.completed_value / g.target_value) if g.target_value else 0.0,
        }

    def recommend_for_today(self, user_id: int) -> dict:
        """根据近 7 日达成率, 推荐今日目标"""
        with SessionLocal() as s:
            from app.persistence.models import DailyGoal
            from sqlalchemy import select, desc
            recent = list(s.scalars(
                select(DailyGoal)
                .where(DailyGoal.user_id == user_id)
                .order_by(desc(DailyGoal.goal_date))
                .limit(7)
            ))
        if recent:
            ratios = [(g.completed_value / g.target_value) if g.target_value else 0
                      for g in recent]
            avg_ratio = sum(ratios) / len(ratios)
            avg_target = sum(g.target_value for g in recent) / len(recent)
            if avg_ratio >= 1.0:
                suggested = int(avg_target * 1.1)
            elif avg_ratio < 0.6:
                suggested = int(avg_target * 0.9)
            else:
                suggested = int(avg_target)
        else:
            suggested = self.DEFAULT_TARGET

        day = _today_zero_ms_utc()
        with SessionLocal() as s:
            g = repo.upsert_daily_goal(
                s, user_id=user_id, goal_date=day,
                target_kind="count",
                target_value=suggested,
                recommended=True,
            )
            s.commit()
        return {
            "id": g.id,
            "target_value": g.target_value,
            "recommended": True,
        }

    def update_progress(self, user_id: int) -> dict:
        """根据今日 solve 数量更新进度"""
        day = _today_zero_ms_utc()
        with SessionLocal() as s:
            from app.persistence.models import Cube
            from sqlalchemy import select, func
            n = s.scalar(
                select(func.count(Cube.id))
                .where(Cube.user_id == user_id,
                       Cube.started_at >= day,
                       Cube.is_dnf == False)
            ) or 0
            g = repo.upsert_daily_goal(
                s, user_id=user_id, goal_date=day,
                completed_value=int(n),
                is_achieved=int(n) >= 12,
            )
            s.commit()
        return {"completed_value": g.completed_value, "is_achieved": g.is_achieved}
