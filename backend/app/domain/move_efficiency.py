"""
转动效率分析
检测: 抵消 (R R' = 0), 重复 (R R R = R')
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

from app.domain.cube_model import Move


@dataclass
class MoveStats:
    raw: int
    effective: int
    waste: int
    cross_moves: int
    f2l_moves: int
    oll_moves: int
    pll_moves: int
    f2l_per_pair: float

    def to_dict(self) -> dict:
        return {
            "raw_moves": self.raw,
            "effective_moves": self.effective,
            "waste_moves": self.waste,
            "cross_moves": self.cross_moves,
            "f2l_moves": self.f2l_moves,
            "oll_moves": self.oll_moves,
            "pll_moves": self.pll_moves,
            "f2l_per_pair": self.f2l_per_pair,
        }


# 简易取消: 同面相邻合并, 不考虑中层/外层的块关系
# power 编码: 1=顺 90°, 2=180°, 3=逆 90° (270°)
# 4 个 1 = (1+1+1+1) mod 4 = 0 -> 抵消
# 3 个 1 = (1+1+1) mod 4 = 3 -> 逆 90°
# 1 + 3 = 0 -> 抵消
def _power_add(a: int, b: int) -> int:
    # 在 mod-4 群上加法: 1+1+1+1=0, 但我们要用 0 表示"无"
    # a, b in {1, 2, 3} (无 0)
    # 0 仅表示"抵消", 不可与 1/2/3 复合
    if a == 0:
        return b
    if b == 0:
        return a
    s = (a + b) % 4
    return s if s != 0 else 0


def _face_key(move: Move) -> str:
    """用于抵消的等价 key (U 和 U' 都映射到 'U')"""
    if len(move.face) == 2 and move.face[1] == "w":
        return move.face
    return move.face


def cancel_moves(moves: Iterable[Move]) -> list[Move]:
    """简化的面内抵消, 输出残余的 move 列表 (不重建 cube state)"""
    out: list[tuple[str, int]] = []
    for m in moves:
        if not m.is_outer_turn and not m.is_wide_turn:
            # 中层切片/整体旋转不参与本算法
            out.append((_face_key(m), m.power))
            continue
        key = _face_key(m)
        if out and out[-1][0] == key:
            merged = _power_add(out[-1][1], m.power)
            if merged == 0:
                out.pop()
            else:
                out[-1] = (key, merged)
        else:
            out.append((key, m.power))
    return [Move(face=k, power=p) for k, p in out]


class MoveEfficiency:
    def analyze(self,
                moves_with_ts: list[tuple[Move, int]],
                stage_ranges: dict[str, tuple[int, int]]) -> MoveStats:
        raw_moves = [m for m, _ in moves_with_ts]
        effective = cancel_moves(raw_moves)
        waste = len(raw_moves) - len(effective)

        cross_m = sum(1 for m, ts in moves_with_ts
                      if stage_ranges.get("cross", (0, 0))[0] <= ts <= stage_ranges.get("cross", (0, 0))[1])
        f2l_m = sum(1 for m, ts in moves_with_ts
                    if stage_ranges.get("f2l", (0, 0))[0] < ts <= stage_ranges.get("f2l", (0, 0))[1])
        oll_m = sum(1 for m, ts in moves_with_ts
                    if stage_ranges.get("oll", (0, 0))[0] < ts <= stage_ranges.get("oll", (0, 0))[1])
        pll_m = sum(1 for m, ts in moves_with_ts
                    if stage_ranges.get("pll", (0, 0))[0] < ts <= stage_ranges.get("pll", (0, 0))[1])

        # F2L 对数
        _, hi = stage_ranges.get("f2l", (0, 0))
        # 粗略: hi > 0 ? 4 : 0  -- 由调用方传入
        return MoveStats(
            raw=len(raw_moves),
            effective=len(effective),
            waste=waste,
            cross_moves=cross_m,
            f2l_moves=f2l_m,
            oll_moves=oll_m,
            pll_moves=pll_m,
            f2l_per_pair=(f2l_m / 4.0) if f2l_m > 0 else 0.0,
        )
