"""
停顿分析器
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from app.domain.cube_model import Move


@dataclass
class Pause:
    seq: int
    start_ms: int
    end_ms: int
    duration_ms: int
    before_move_seq: int
    after_move_seq: int
    stage_label: Optional[str]
    type: str  # observe / think / lockup

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "before_move_seq": self.before_move_seq,
            "after_move_seq": self.after_move_seq,
            "stage_label": self.stage_label,
            "type": self.type,
        }


class PauseAnalyzer:
    """在 move 时间戳流上识别停顿区间"""
    DEFAULT_THRESHOLD_MS = 500

    def __init__(self, threshold_ms: int = DEFAULT_THRESHOLD_MS):
        self.threshold_ms = threshold_ms

    def analyze(self,
                moves_with_ts: list[tuple[Move, int, int]],
                stage_ranges: dict[str, tuple[int, int]],
                ) -> list[Pause]:
        """
        moves_with_ts: [(Move, timestamp_ms_relative, seq), ...]   seq 是 move 在 solve 中的次序
        stage_ranges: {"cross": (0,1500), "f2l": (1500,7600), ...}
        """
        pauses: list[Pause] = []
        if len(moves_with_ts) < 2:
            return pauses

        for i in range(1, len(moves_with_ts)):
            prev_mv, prev_ts, prev_seq = moves_with_ts[i - 1]
            nxt_mv,  nxt_ts,  nxt_seq  = moves_with_ts[i]
            gap = nxt_ts - prev_ts
            if gap < self.threshold_ms:
                continue

            stage = self._resolve_stage(prev_ts, stage_ranges)
            ptype = self._classify(gap, prev_ts, nxt_ts, stage_ranges)
            pauses.append(Pause(
                seq=len(pauses),
                start_ms=prev_ts,
                end_ms=nxt_ts,
                duration_ms=gap,
                before_move_seq=prev_seq,
                after_move_seq=nxt_seq,
                stage_label=stage,
                type=ptype,
            ))
        return pauses

    def _resolve_stage(self, t: int, ranges: dict[str, tuple[int, int]]) -> str:
        for label, (lo, hi) in ranges.items():
            if lo <= t <= hi:
                return label
        return "post"

    def _classify(self, gap: int, prev_ts: int, nxt_ts: int, ranges: dict[str, tuple[int, int]]) -> str:
        prev_stage = self._resolve_stage(prev_ts, ranges)
        next_stage = self._resolve_stage(nxt_ts, ranges)
        if prev_stage != next_stage:
            return "observe"
        if gap >= 2000:
            return "lockup"
        return "think"