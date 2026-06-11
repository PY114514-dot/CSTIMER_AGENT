"""
CFOP 阶段识别器

替代/参考 cstimer cubeutil.js 中的 getCFOPProgress / getProgress
对每一次复原的 move 序列, 重放魔方状态, 在每次 move 后探测阶段进度,
确定每个阶段结束的时间戳.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from app.domain.cube_model import (
    Move, apply_move_facelet, apply_moves_facelet,
    is_solved, get_progress_code, SOLVED_FACELET,
    _is_cross_solved, _is_oll_done, _count_solved_f2l_pairs,
    generate_random_scramble,
)


@dataclass
class StageRanges:
    """一个 solve 的 4 个阶段时间窗 (相对 started_at 的毫秒)"""
    cross_end: Optional[int]
    f2l_end:   Optional[int]
    oll_end:   Optional[int]
    pll_end:   Optional[int]
    f2l_pairs: int
    method: str = "cfop"
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "cross_end": self.cross_end,
            "f2l_end":   self.f2l_end,
            "oll_end":   self.oll_end,
            "pll_end":   self.pll_end,
            "f2l_pairs": self.f2l_pairs,
            "method":    self.method,
            "confidence": self.confidence,
        }

    def as_label_ranges(self, total_ms: int) -> dict[str, tuple[int, int]]:
        """把时间窗转换为 move_events.stage_label 的回填区间"""
        out: dict[str, tuple[int, int]] = {}
        boundaries = [0,
                      self.cross_end if self.cross_end is not None else total_ms,
                      self.f2l_end   if self.f2l_end   is not None else total_ms,
                      self.oll_end   if self.oll_end   is not None else total_ms,
                      self.pll_end   if self.pll_end   is not None else total_ms]
        labels = ["cross", "f2l", "oll", "pll"]
        for i, label in enumerate(labels):
            lo = boundaries[i]
            hi = boundaries[i + 1] if boundaries[i + 1] is not None else total_ms
            out[label] = (lo, hi)
        return out

    def dur_dict(self) -> dict[str, Optional[int]]:
        c = self.cross_end
        f = self.f2l_end
        o = self.oll_end
        p = self.pll_end
        return {
            "cross_dur_ms": c - 0 if c is not None else None,
            "f2l_dur_ms":   (f - c) if (f is not None and c is not None) else None,
            "oll_dur_ms":   (o - f) if (o is not None and f is not None) else None,
            "pll_dur_ms":   (p - o) if (p is not None and o is not None) else None,
        }


class CFOPStageDetector:
    """
    三层回退策略:
      L1 启发式 (默认, 走魔方状态机)
      L2 用户手动标记 (暂不实现, 留接口)
      L3 LLM 校正 (在 AICoach 阶段可选)
    """

    def detect(self,
               moves_with_ts: list[tuple[Move, int]],
               total_time_ms: int,
               scramble_text: Optional[str] = None) -> StageRanges:
        """
        moves_with_ts: [(Move, timestamp_ms_relative_to_start), ...]
        total_time_ms: solve 总时长 (用于边界兜底)
        scramble_text: 原始 scramble 字符串 (用于从还原态开始重放)
        """
        return self._heuristic(moves_with_ts, total_time_ms, scramble_text)

    def _heuristic(self,
                   moves_with_ts: list[tuple[Move, int]],
                   total_time_ms: int,
                   scramble_text: Optional[str]) -> StageRanges:
        """
        从已还原状态出发, 先用 scramble 把魔方打乱到解前状态,
        然后顺序 apply moves, 在每个 move 之后探测阶段进度.

        关键改进: 跟踪"之前处于什么状态", 当 cross/F2L/OLL 刚完成时记录时间.
        """
        if scramble_text:
            scr_state = apply_moves_facelet(SOLVED_FACELET, _parse_loose(scramble_text))
        else:
            scr_state = SOLVED_FACELET

        state = scr_state
        cross_end = f2l_end = oll_end = pll_end = None
        max_f2l_pairs = 0

        prev_cross = _is_cross_solved(state)
        prev_oll = _is_oll_done(state)
        prev_solved = is_solved(state)

        for mv, ts in moves_with_ts:
            state = apply_move_facelet(state, mv)
            cur_cross = _is_cross_solved(state)
            cur_oll = _is_oll_done(state)
            cur_solved = is_solved(state)

            if cur_solved:
                pll_end = ts    # 持续更新到最后 solved 时刻
            if cur_oll:
                oll_end = ts
            if cur_cross:
                cross_end = ts  # 持续更新到最后一次 cross 完成的时刻

            prev_cross, prev_oll, prev_solved = cur_cross, cur_oll, cur_solved

            pairs = _count_solved_f2l_pairs(state)
            if pairs > max_f2l_pairs:
                max_f2l_pairs = pairs
            if pairs == 4:
                f2l_end = ts     # 持续更新到 f2l 4 对 home 的最后时刻

        if pll_end is None and is_solved(state):
            pll_end = moves_with_ts[-1][1] if moves_with_ts else total_time_ms

        confidence = self._confidence(cross_end, f2l_end, oll_end, pll_end, len(moves_with_ts))

        return StageRanges(
            cross_end=cross_end,
            f2l_end=f2l_end,
            oll_end=oll_end,
            pll_end=pll_end,
            f2l_pairs=max_f2l_pairs,
            method="cfop",
            confidence=confidence,
        )

    def _confidence(self, cross_end, f2l_end, oll_end, pll_end, n_moves) -> float:
        if n_moves < 5:
            return 0.3
        score = 0.0
        if cross_end is not None: score += 0.2
        if f2l_end is not None:   score += 0.3
        if oll_end is not None:   score += 0.3
        if pll_end is not None:   score += 0.2
        return min(1.0, score)


def _parse_loose(scr: str) -> list[Move]:
    """容错解析 scramble 字符串, 跳过无效 token"""
    from app.domain.cube_model import parse_moves, parse_move
    out: list[Move] = []
    for tok in scr.strip().split():
        tok = tok.strip("()[]")
        try:
            out.append(parse_move(tok))
        except ValueError:
            try:
                out.extend(parse_moves(tok))
            except ValueError:
                continue
    return out
