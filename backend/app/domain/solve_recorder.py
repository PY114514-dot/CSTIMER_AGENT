"""
完整 solve 流程: 接收 scramble + 模拟的 move 序列, 写入 DB, 自动后处理
"""
from __future__ import annotations
import time
import random
from typing import Optional

from app.domain.cube_model import Move, parse_move, parse_moves, generate_random_scramble
from app.domain.cfop_detector import CFOPStageDetector
from app.domain.pause_analyzer import PauseAnalyzer
from app.domain.move_efficiency import MoveEfficiency
from app.persistence import repositories as repo
from app.persistence.db import SessionLocal


def _now_ms() -> int:
    return int(time.time() * 1000)


class SolveRecorder:
    """模拟一次完整 solve: scramble + 解法 + 完成 → 写库 + 后处理"""

    def __init__(self, pause_threshold_ms: int = 500):
        self.detector = CFOPStageDetector()
        self.pause_analyzer = PauseAnalyzer(threshold_ms=pause_threshold_ms)
        self.eff = MoveEfficiency()

    def start_solve(self, user_id: int, scramble: str | None = None) -> dict:
        if scramble is None:
            scramble = generate_random_scramble(seed=random.randint(0, 1 << 31))
        with SessionLocal() as s:
            sess = repo.get_open_session(s, user_id)
            if not sess:
                sess = repo.create_session(s, user_id=user_id, target_size=12,
                                            name=f"auto-{_now_ms()}")
            cube = repo.create_cube(
                s,
                user_id=user_id,
                session_id=sess.id,
                puzzle_type="333",
                scramble=scramble,
                started_at=_now_ms(),
                ended_at=_now_ms(),  # 占位
                total_time_ms=0,
                move_count=0,
            )
            s.commit()
            cube_id = cube.id
            session_id = sess.id
        return {"cube_id": cube_id, "session_id": session_id, "scramble": scramble}

    def add_move(self, cube_id: int, move_text: str) -> dict:
        mv = parse_move(move_text)
        absolute = _now_ms()
        with SessionLocal() as s:
            cube = repo.get_cube(s, cube_id)
            if not cube:
                raise ValueError(f"cube {cube_id} not found")
            seq = repo.next_move_seq(s, cube_id)
            relative = absolute - cube.started_at
            repo.add_move(
                s,
                solve_id=cube_id,
                seq=seq,
                move_text=str(mv),
                is_smart_turn=False,
                timestamp_ms=relative,
                absolute_ms=absolute,
            )
            s.commit()
        return {"seq": seq, "move": str(mv)}

    def finish_solve(self, cube_id: int) -> dict:
        with SessionLocal() as s:
            cube = repo.get_cube(s, cube_id)
            if not cube:
                raise ValueError(f"cube {cube_id} not found")
            # 如果 demo/导入模式已设置 total_time_ms, 则不覆盖; 否则用实时差
            if cube.total_time_ms <= 0:
                total_ms = _now_ms() - cube.started_at
                cube.ended_at = _now_ms()
                cube.total_time_ms = total_ms
            else:
                total_ms = cube.total_time_ms
                cube.ended_at = cube.started_at + total_ms

            moves = repo.list_moves(s, cube_id)
            moves_with_ts = [(parse_move(m.move_text), m.timestamp_ms) for m in moves]

            # 1. 阶段识别
            stages = self.detector.detect(moves_with_ts, total_ms, cube.scramble)
            repo.upsert_stages(s, cube_id, **stages.dur_dict(),
                                f2l_pairs=stages.f2l_pairs,
                                detected_method=stages.method,
                                confidence=stages.confidence)

            # 2. 停顿分析
            label_ranges = stages.as_label_ranges(total_ms)
            moves_with_seq = [(parse_move(m.move_text), m.timestamp_ms, m.seq) for m in moves]
            pauses = self.pause_analyzer.analyze(moves_with_seq, label_ranges)
            repo.replace_pauses(s, cube_id, [p.to_dict() for p in pauses])

            # 3. 回填 move.stage_label
            repo.backfill_move_stages(s, cube_id, label_ranges)

            # 4. 更新 cube 派生字段
            cube.move_count = len(moves)

            # 5. Session 计数
            if cube.session_id:
                repo.increment_session_count(s, cube.session_id)
                sess = s.get(__import__("app.persistence.models", fromlist=["TrainingSession"]).TrainingSession,
                              cube.session_id)
                session_id = cube.session_id
            else:
                session_id = None

            s.commit()
        return {
            "cube_id": cube_id,
            "session_id": session_id,
            "total_time_ms": total_ms,
            "move_count": len(moves),
            "stage_confidence": stages.confidence,
            "pause_count": len(pauses),
        }
