"""
3x3 魔方 facelet 状态机 - 6 个外层面的置换 (无 wide/slice/rotation)

设计思路: 用"已验证的"置换表 - 通过 cstimer 的 4 个标准不变量 (R^4=id, R R'=id,
sexy x 6 = id, Sune 后 OLL) 来验证 perm 正确性. 错了就改.

每面置换 9 个贴纸: 中心固定, 4 角 0/2/6/8 顺时针循环, 4 边 1/3/5/7 顺时针循环
(对 3x3 块本身), 同时牵动邻面的 12 个贴纸.

为了避免手算出错, 改用"3x3 块内 perm" + "邻面循环"两个独立的部分组合.
"""
from __future__ import annotations
import re
import random
from dataclasses import dataclass
from typing import Iterable

# 已还原状态
SOLVED_FACELET = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"

# 6 个面在 facelet 字符串中的起始索引
FACE_START = {"U": 0, "R": 9, "F": 18, "D": 27, "L": 36, "B": 45}

# 3x3 块内部 顺时针 90° perm (4 角 + 4 边循环, 中心不动)
# 位置: 0 1 2
#        3 4 5
#        6 7 8
# 顺时针后: 0->2, 1->5, 2->8, 3->0, 5->1, 6->6, 7->3, 8->7
# 写为 "perm[i] = 旧位置" (新位置 i 来自旧位置 perm[i]):
#  新 0 = 旧 6, 新 1 = 旧 3, 新 2 = 旧 0, 新 3 = 旧 7, 新 4 = 旧 4,
#  新 5 = 旧 1, 新 6 = 旧 8, 新 7 = 旧 5, 新 8 = 旧 2
_FACE3_CW = [6, 3, 0, 7, 4, 1, 8, 5, 2]


def _face_cw(face: str) -> list[int]:
    """对单个面的 9 个贴纸顺时针 90° 后的置换 (新位置 = 旧位置)"""
    s = FACE_START[face]
    return [s + _FACE3_CW[i] for i in range(9)]


# 邻面 12 个贴纸的循环 (新位置 = 旧位置)
# U 顺时针: 4 个面顶行 (F[0..2], R[0..2], B[0..2], L[0..2]) 循环 F<-L<-B<-R
# 即: F top = L top, R top = F top, B top = R top, L top = B top
NEIGHBOR_CYCLES: dict[str, list[tuple[list[int], list[int]]]] = {
    "U": [
        # 每个循环: (新位置列表, 旧位置列表) - 两两对应
        ([18, 19, 20], [36, 37, 38]),   # F top = L top
        ([9, 10, 11],   [18, 19, 20]),  # R top = F top
        ([45, 46, 47],  [9, 10, 11]),   # B top = R top
        ([36, 37, 38],  [45, 46, 47]),  # L top = B top
    ],
    "R": [
        # R 顺时针: F right col <- U right col, U right col <- B left col(rev),
        #           B left col(rev) <- D right col, D right col <- F right col
        ([20, 23, 26],  [2, 5, 8]),            # F right col = U right col
        ([2, 5, 8],     [53, 50, 47]),         # U right col = B right col (reversed)
        ([53, 50, 47],  [29, 32, 35]),         # B right col (reversed) = D right col
        ([29, 32, 35],  [20, 23, 26]),         # D right col = F right col
    ],
    "F": [
        # F 顺时针: U bottom <- L right col(rev), R left col <- U bottom,
        #           D top(rev) <- R left col, L right col(rev) <- D top(rev)
        ([6, 7, 8],     [44, 41, 38]),         # U bottom = L right col (reversed)
        ([9, 12, 15],   [6, 7, 8]),            # R left col = U bottom
        ([29, 28, 27],  [9, 12, 15]),          # D top (reversed) = R left col
        ([44, 41, 38],  [29, 28, 27]),         # L right col (reversed) = D top (reversed)
    ],
    "D": [
        # D 顺时针: F bottom <- L bottom, L bottom <- B bottom, B bottom <- R bottom, R bottom <- F bottom
        ([24, 25, 26],  [42, 43, 44]),         # F bottom = L bottom
        ([42, 43, 44],  [51, 52, 53]),         # L bottom = B bottom
        ([51, 52, 53],  [33, 34, 35]),         # B bottom = R bottom
        ([33, 34, 35],  [24, 25, 26]),         # R bottom = F bottom
    ],
    "L": [
        # L 顺时针: U left <- F left, F left <- D left, D left <- B right(rev), B right(rev) <- U left
        ([0, 3, 6],     [18, 21, 24]),         # U left = F left
        ([18, 21, 24],  [27, 30, 33]),         # F left = D left
        ([27, 30, 33],  [53, 50, 47]),         # D left = B right col (reversed)
        ([53, 50, 47],  [0, 3, 6]),            # B right col (reversed) = U left
    ],
    "B": [
        # B 顺时针: U top <- L left, L left <- D bottom(rev),
        #          D bottom(rev) <- R right(rev), R right(rev) <- U top
        ([0, 1, 2],     [36, 39, 42]),         # U top = L left
        ([36, 39, 42],  [35, 34, 33]),         # L left = D bottom (reversed)
        ([35, 34, 33],  [35, 32, 29]),         # D bottom (rev) = R right (reversed)
        ([35, 32, 29],  [0, 1, 2]),            # R right (reversed) = U top
    ],
}


def build_outer_perm(face: str, power: int) -> list[int]:
    """构造外层面 (face, power) 的 54 贴纸置换.

    规则: new_state[i] = old_state[perm[i]]
    """
    if face not in "URFDLB":
        return list(range(54))
    # 多次 90° 顺时针合成
    p = list(range(54))
    for _ in range(power):
        p_new = p[:]
        # 1. 当前面 9 个贴纸顺时针: 把 9 个 3x3 块内部 perm 应用
        fcw = _face_cw(face)
        for new_local in range(9):
            # 旧 local 位置是 _FACE3_CW[new_local]
            old_local = _FACE3_CW[new_local]
            new_global = FACE_START[face] + new_local
            old_global = FACE_START[face] + old_local
            p_new[new_global] = p[old_global]
        # 2. 邻面循环
        for new_pos_list, old_pos_list in NEIGHBOR_CYCLES[face]:
            for npos, opos in zip(new_pos_list, old_pos_list):
                p_new[npos] = p[opos]
        p = p_new
    return p


# 预生成 6 面 × 3 power
PERMS: dict[tuple[str, int], list[int]] = {}
for _f in "URFDLB":
    for _p in (1, 2, 3):
        PERMS[(_f, _p)] = build_outer_perm(_f, _p)


# ─────────────────────────────────────────────────────────
# Move
# ─────────────────────────────────────────────────────────
MOVE_RE = re.compile(r"^\s*([URFDLB]w?|[EMSyxz]|2-2[URFDLB]w)(['2]?)(?:@(\d+))?\s*$")


@dataclass(frozen=True)
class Move:
    face: str
    power: int
    timestamp_ms: int = 0

    def __str__(self) -> str:
        suf = "" if self.power == 1 else ("'" if self.power == 3 else "2")
        return f"{self.face}{suf}"

    @property
    def is_outer_turn(self) -> bool:
        return len(self.face) == 1 and self.face in "URFDLB"

    @property
    def is_unsupported(self) -> bool:
        return self.face in ("Uw", "Rw", "Fw", "Dw", "Lw", "Bw",
                              "M", "E", "S", "x", "y", "z")


def parse_move(text: str) -> Move:
    m = MOVE_RE.match(text)
    if not m:
        raise ValueError(f"invalid move notation: {text!r}")
    face, suffix, ts = m.group(1), m.group(2), m.group(3)
    if suffix == "":
        power = 1
    elif suffix == "'":
        power = 3
    else:
        power = 2
    return Move(face=face, power=power, timestamp_ms=int(ts) if ts else 0)


def parse_moves(text: str) -> list[Move]:
    out: list[Move] = []
    for tok in text.strip().split():
        tok = tok.strip("()[]")
        if tok:
            out.append(parse_move(tok))
    return out


def apply_move_facelet(state: str, move: Move) -> str:
    if move.is_unsupported:
        return state
    key = (move.face, move.power)
    if key not in PERMS:
        return state
    p = PERMS[key]
    chars = list(state)
    new_chars = [""] * 54
    for new_pos in range(54):
        new_chars[new_pos] = chars[p[new_pos]]
    return "".join(new_chars)


def apply_moves_facelet(state: str, moves: Iterable[Move]) -> str:
    for m in moves:
        state = apply_move_facelet(state, m)
    return state


# ─────────────────────────────────────────────────────────
# 还原度判定
# ─────────────────────────────────────────────────────────
def is_solved(state: str) -> bool:
    return state == SOLVED_FACELET


def _is_face_uniform(state: str, face: str) -> bool:
    s = FACE_START[face]
    chunk = state[s:s + 9]
    return all(c == chunk[0] for c in chunk)


def _is_cross_solved(state: str) -> bool:
    return (state[28] == "D" and state[30] == "D" and state[32] == "D" and state[34] == "D")


def _is_oll_done(state: str) -> bool:
    return _is_face_uniform(state, "U")


def _count_solved_f2l_pairs(state: str) -> int:
    return sum(1 for ch in (state[28], state[30], state[34], state[32]) if ch == "D")


def get_progress_code(state: str) -> int:
    if is_solved(state):
        return 0
    if _is_oll_done(state):
        return 1
    if _count_solved_f2l_pairs(state) == 4:
        return 2
    if _is_cross_solved(state):
        return 3
    return 4


# ─────────────────────────────────────────────────────────
# 自检
# ─────────────────────────────────────────────────────────
def _self_check() -> bool:
    ok = True
    def fail(msg):
        nonlocal ok
        print(f"[SELF-CHECK] FAIL: {msg}")
        ok = False

    for face in "URFDLB":
        s = apply_moves_facelet(SOLVED_FACELET, parse_moves(f"{face} {face} {face} {face}"))
        if s != SOLVED_FACELET: fail(f"{face}^4 != identity: {s}")
        s = apply_moves_facelet(SOLVED_FACELET, parse_moves(f"{face} {face}'"))
        if s != SOLVED_FACELET: fail(f"{face} {face}' != identity: {s}")

    # sexy x 6 = identity
    s = apply_moves_facelet(SOLVED_FACELET, parse_moves(" ".join(["R U R' U'"] * 6)))
    if s != SOLVED_FACELET: fail(f"sexy x 6 != identity: {s}")

    # Sune OLL
    s = apply_moves_facelet(SOLVED_FACELET, parse_moves("R U R' U R U2 R'"))
    if not _is_oll_done(s): fail(f"Sune not OLL done: {s}")

    # Sune + anti-Sune = identity
    s = apply_moves_facelet(SOLVED_FACELET, parse_moves("R U R' U R U2 R' R' U2 R U R' U' R'"))
    if s != SOLVED_FACELET: fail(f"Sune + anti-Sune != identity: {s}")

    # 一些 cross 测试: 只做 R 不动 cross
    s = apply_moves_facelet(SOLVED_FACELET, parse_moves("R R' R R'"))
    if s != SOLVED_FACELET: fail(f"R R' R R' != identity: {s}")

    if ok:
        print("[SELF-CHECK] all cube model perms pass")
    return ok


try:
    _self_check()
except Exception as e:
    print(f"[SELF-CHECK] exception: {e}")


# ─────────────────────────────────────────────────────────
# 打乱生成
# ─────────────────────────────────────────────────────────
def generate_random_scramble(length: int = 20, seed: int | None = None) -> str:
    rng = random.Random(seed)
    axes = ["U", "R", "F", "D", "L", "B"]
    suffixes = ["", "'", "2"]
    out: list[str] = []
    last_axis = ""
    while len(out) < length:
        axis = rng.choice([a for a in axes if a != last_axis])
        suf = rng.choice(suffixes)
        out.append(axis + suf)
        last_axis = axis
    return " ".join(out)
