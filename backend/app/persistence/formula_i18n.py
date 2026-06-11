"""
公式库 i18n 字典
- 所有非英文文本 (recognition, display_name 描述) 都用双语
- ALG 字符串本身永远是英文 (国际标准)
- case.name 也保留英文 (e.g. "Aa perm"), UI 层可加中文别名
"""
from __future__ import annotations

# case.code -> { "zh": 中文识别, "en": 英文识别, "alias_zh": 中文别名 }
PLL_RECOGNITION = {
    "Aa": {"zh": "两个邻角互换", "en": "two adjacent corners swapped"},
    "Ab": {"zh": "两个对角互换", "en": "two diagonal corners swapped"},
    "E":  {"zh": "三条边互换 + 角块不动", "en": "three edges cycled, corners untouched"},
    "F":  {"zh": "前 1 + 后 1 / 一条邻边", "en": "front+back swap (one edge pair)"},
    "Ga": {"zh": "两角 + 两对边", "en": "two corners + two opposite edge pairs"},
    "Gb": {"zh": "两角 + 两条邻边", "en": "two corners + two adjacent edges"},
    "Gc": {"zh": "两角 + 两条对边", "en": "two corners + two opposite edges"},
    "Gd": {"zh": "两角 + 两条边反向", "en": "two corners + two edges reversed"},
    "H":  {"zh": "对边互换", "en": "opposite edge swap"},
    "Ja": {"zh": "两邻角 + 一边反向", "en": "two adjacent corners + one edge reversed"},
    "Jb": {"zh": "两邻角 + 一边", "en": "two adjacent corners + one edge"},
    "Na": {"zh": "两角 + 两条反向边", "en": "two corners + two opposite-direction edges"},
    "Nb": {"zh": "两角 + 两条邻边", "en": "two corners + two adjacent edges"},
    "Ra": {"zh": "一边反向 + 角块不动", "en": "one edge reversed, corners untouched"},
    "Rb": {"zh": "一边正向 + 角块不动", "en": "one edge forward, corners untouched"},
    "T":  {"zh": "两邻角 + 头部边反向", "en": "T-shape: two adjacent corners + head edge reversed"},
    "Ua": {"zh": "三边循环正向 (逆时针)", "en": "three edges cycle clockwise (Ua)"},
    "Ub": {"zh": "三边循环反向", "en": "three edges cycle counter-clockwise (Ub)"},
    "V":  {"zh": "两邻角 + 头部边正向", "en": "V-shape: two adjacent corners + head edge forward"},
    "Y":  {"zh": "两角 + 一条邻边 + 头部对边", "en": "Y-shape: two corners + adjacent + opposite edges"},
    "Z":  {"zh": "对边互换 + 一边反向", "en": "Z-shape: opposite edge swap + one edge reversed"},
}

# OLL case.code -> i18n (case.code 形如 "OLL 21")
OLL_RECOGNITION = {
    "OLL 1":  {"zh": "无任何边定向 (全 dot)", "en": "no edges oriented (all dot)"},
    "OLL 21": {"zh": "H (两条对边已定向)", "en": "H: two opposite edges already oriented"},
    "OLL 22": {"zh": "H 变体", "en": "H variant"},
    "OLL 23": {"zh": "U (两条邻边已定向)", "en": "U: two adjacent edges oriented"},
    "OLL 24": {"zh": "U 变体", "en": "U variant"},
    "OLL 25": {"zh": "U 镜像", "en": "U mirror"},
    "OLL 26": {"zh": "U 镜像", "en": "U mirror"},
    "OLL 27": {"zh": "U 镜像", "en": "U mirror"},
    "OLL 28": {"zh": "U 镜像", "en": "U mirror"},
    "OLL 33": {"zh": "T (三边 + 角对)", "en": "T-shape: three edges + corner pair"},
    "OLL 45": {"zh": "F (全边翻转, L 形)", "en": "F: all edges flipped, L-shape"},
    "OLL 55": {"zh": "全角定向 (skip)", "en": "all corners oriented (skip)"},
    "OLL 56": {"zh": "全角定向 (skip 变体)", "en": "all corners oriented (skip variant)"},
    "OLL 57": {"zh": "全角定向 (skip 变体)", "en": "all corners oriented (skip variant)"},
}

# F2L case.code -> i18n (case.code 形如 "F2L 1")
F2L_RECOGNITION = {
    # 不细分, 给通用描述
    "_default": {"zh": "F2L 基础对 (corner-edge pair)", "en": "F2L basic pair (corner-edge)"},
}

# set_code -> display_name 双语
SET_DISPLAY_NAMES = {
    "PLL":   {"zh": "3x3 顶层 PLL (21 个)", "en": "3x3 PLL (21 cases)"},
    "OLL":   {"zh": "3x3 顶层 OLL (57 个)", "en": "3x3 OLL (57 cases)"},
    "F2L":   {"zh": "3x3 F2L (41 对)", "en": "3x3 F2L (41 pairs)"},
    "CMLL":  {"zh": "3x3 CMLL (Roux 法)", "en": "3x3 CMLL (Roux method)"},
    "OLLCP": {"zh": "3x3 OLLCP (角块预定向)", "en": "3x3 OLLCP (corner pre-orient)"},
    "COLL":  {"zh": "3x3 COLL (V 群)", "en": "3x3 COLL (V group)"},
    "ZBLL":  {"zh": "3x3 ZBLL", "en": "3x3 ZBLL"},
    "WV":    {"zh": "3x3 Winter Variation", "en": "3x3 Winter Variation"},
}


def recognition_for(set_code: str, case_code: str, lang: str = "zh") -> str | None:
    """按 set_code/case_code/lang 返回识别描述. 找不到返 None."""
    table = {
        "PLL": PLL_RECOGNITION,
        "OLL": OLL_RECOGNITION,
        "F2L": F2L_RECOGNITION,
    }.get(set_code)
    if not table:
        return None
    entry = table.get(case_code) or table.get("_default")
    if not entry:
        return None
    if lang == "en":
        return entry.get("en")
    return entry.get("zh") or entry.get("en")


def set_display_name(set_code: str, lang: str = "zh") -> str | None:
    """返回 set 的人类可读名 (双语)"""
    entry = SET_DISPLAY_NAMES.get(set_code)
    if not entry:
        return None
    return entry.get(lang) or entry.get("zh")
