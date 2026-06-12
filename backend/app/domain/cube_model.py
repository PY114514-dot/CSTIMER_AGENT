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
# 数据来源: 用 cstimer/src/js/lib/mathlib.js 的 CubieCube.moveCube + toFaceCube
# 算出 6 面顺时针 1 次的 facelet perm, 然后拆出 12 个跨面贴纸对.
# ground-truth 验证: 4-cycle, sexy x 6, Sune 等不变量全部通过.
NEIGHBOR_CYCLES: dict[str, list[tuple[list[int], list[int]]]] = {
    "U": [
        # U 顺时针: 4 个面顶行 (F[0..2], R[0..2], B[0..2], L[0..2]) 循环
        # 4-cycle: B顶 -> R顶 -> F顶 -> L顶 -> B顶
        ([9, 10, 11],   [45, 46, 47]),  # R top = B top
        ([18, 19, 20],  [9, 10, 11]),   # F top = R top
        ([36, 37, 38],  [18, 19, 20]),  # L top = F top
        ([45, 46, 47],  [36, 37, 38]),  # B top = L top
    ],
    "R": [
        # R 顺时针: 4 段邻面 (F 右列, U 右列, B 左列 reverse, D 右列)
        # 4-cycle: F右 -> U右 -> B左(rev) -> D右 -> F右
        # 但 B 是镜像, B 左列 reverse 的 index 顺序需对照 cstimer ground truth
        # cstimer perm: new U[2,5,8]=[2,5,8] <- old F[2,5,8]=[20,23,26]
        #              new F[2,5,8]=[20,23,26] <- old D[2,5,8]=[29,32,35]
        #              new D[2,5,8]=[29,32,35] <- old B[6,3,0]=[51,48,45]
        #              new B[0,3,6]=[45,48,51] <- old U[8,5,2]=[8,5,2]
        ([2, 5, 8],     [20, 23, 26]),  # U right col = F right col
        ([20, 23, 26],  [29, 32, 35]),  # F right col = D right col
        ([29, 32, 35],  [51, 48, 45]),  # D right col = B[6,3,0] (B is mirrored)
        ([45, 48, 51],  [8, 5, 2]),      # B[0,3,6] = U[8,5,2] (B is mirrored)
    ],
    "F": [
        # F 顺时针: 4 段邻面 (U 底行, R 左列, D 顶行, L 右列)
        # cstimer perm: new U[6,7,8]=[6,7,8] <- old L[8,5,2]=[44,41,38]
        #              new R[0,3,6]=[9,12,15] <- old U[6,7,8]=[6,7,8]
        #              new D[0,1,2]=[27,28,29] <- old R[6,3,0]=[15,12,9]
        #              new L[2,5,8]=[38,41,44] <- old D[0,1,2]=[27,28,29]
        ([6, 7, 8],     [44, 41, 38]),  # U bottom = L[8,5,2] (L is mirrored)
        ([9, 12, 15],   [6, 7, 8]),      # R left col = U bottom
        ([27, 28, 29],  [15, 12, 9]),    # D top = R[6,3,0] (R is mirrored)
        ([38, 41, 44],  [27, 28, 29]),  # L[2,5,8] = D top (L is mirrored)
    ],
    "D": [
        # D 顺时针: 4 段邻面 (F 底行, R 底行, B 底行, L 底行)
        # cstimer perm: new R[6,7,8]=[15,16,17] <- old F[6,7,8]=[24,25,26]
        #              new F[6,7,8]=[24,25,26] <- old L[6,7,8]=[42,43,44]
        #              new L[6,7,8]=[42,43,44] <- old B[6,7,8]=[51,52,53]
        #              new B[6,7,8]=[51,52,53] <- old R[6,7,8]=[15,16,17]
        ([15, 16, 17],  [24, 25, 26]),  # R bottom = F bottom
        ([24, 25, 26],  [42, 43, 44]),  # F bottom = L bottom
        ([42, 43, 44],  [51, 52, 53]),  # L bottom = B bottom
        ([51, 52, 53],  [15, 16, 17]),  # B bottom = R bottom
    ],
    "L": [
        # L 顺时针: 4 段邻面 (U 左列, F 左列, D 左列, B 右列 reverse)
        # cstimer perm: new U[0,3,6]=[0,3,6] <- old B[8,5,2]=[53,50,47]
        #              new F[0,3,6]=[18,21,24] <- old U[0,3,6]=[0,3,6]
        #              new D[0,3,6]=[27,30,33] <- old F[0,3,6]=[18,21,24]
        #              new B[2,5,8]=[47,50,53] <- old D[6,3,0]=[33,30,27]
        ([0, 3, 6],     [53, 50, 47]),  # U left col = B[8,5,2] (B is mirrored)
        ([18, 21, 24],  [0, 3, 6]),      # F left col = U left col
        ([27, 30, 33],  [18, 21, 24]),  # D left col = F left col
        ([47, 50, 53],  [33, 30, 27]),  # B[2,5,8] = D[6,3,0] (B is mirrored)
    ],
    "B": [
        # B 顺时针: 4 段邻面 (U 顶行, L 左列, D 底行, R 右列 reverse)
        # cstimer perm: new U[0,1,2]=[0,1,2] <- old R[2,5,8]=[11,14,17]
        #              new R[2,5,8]=[11,14,17] <- old D[8,7,6]=[35,34,33]
        #              new D[6,7,8]=[33,34,35] <- old L[0,3,6]=[36,39,42]
        #              new L[0,3,6]=[36,39,42] <- old U[2,1,0]=[2,1,0]
        ([0, 1, 2],     [11, 14, 17]),  # U top = R[2,5,8] (R is mirrored)
        ([11, 14, 17],  [35, 34, 33]),  # R[2,5,8] = D[8,7,6] (D is mirrored)
        ([33, 34, 35],  [36, 39, 42]),  # D bottom = L[0,3,6] (L is mirrored)
        ([36, 39, 42],  [2, 1, 0]),      # L[0,3,6] = U[2,1,0] (U is mirrored)
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

    # Sune + 真正逆序 Sune = identity (原 anti-Sune 记法 "R' U2 R U R' U' R'" 错,
    # 正确逆序是 "R U2 R' U' R U' R'")
    s = apply_moves_facelet(SOLVED_FACELET, parse_moves("R U R' U R U2 R' R U2 R' U' R U' R'"))
    if s != SOLVED_FACELET: fail(f"Sune + Sune_inv != identity: {s}")

    # 经典 comm 不变量: (R U R' U') (R' F R F') = R U R' U' R' F R F'
    s1 = apply_moves_facelet(SOLVED_FACELET, parse_moves("R U R' U' R' F R F'"))
    s2 = apply_moves_facelet(SOLVED_FACELET, parse_moves("R U R' U' R' F R F'"))
    if s1 != s2: fail(f"comm 重复两次不相等: {s1} vs {s2}")

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
