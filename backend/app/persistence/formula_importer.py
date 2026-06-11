"""
公式库数据源: CubingApp / slsj31/algdb (GitHub)

约定:
  - 数据由两层 "case code" 字典归一化 (PLL 21 / OLL 57 / F2L 41)
  - 拉取时使用 urllib + 重试 + 磁盘缓存
  - 解析 alg 字符串复用 app.domain.cube_model.parse_moves 算 move_count
"""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from app.domain.cube_model import parse_moves
from app.persistence.models import FormulaSet, FormulaCase, FormulaAlg
from app.persistence.formula_i18n import recognition_for, set_display_name

# ── 源配置 ───────────────────────────────────────────────────
GITHUB_RAW = "https://raw.githubusercontent.com/slsj31/algdb/main/algSets"
SOURCE_TAG = "cubingapp/algdb"

# 仅 3x3 起步; 其他 puzzle 后续再加
DEFAULT_FILES: list[tuple[str, str, str]] = [
    # (filename in repo, set code, display_name)
    ("PLL.json",          "PLL",  "3x3 PLL (21)"),
    ("OLL.json",          "OLL",  "3x3 OLL (57)"),
    ("F2L.json",          "F2L",  "3x3 F2L (41)"),
    ("CMLL.json",         "CMLL", "3x3 CMLL (Roux)"),
    ("OLLCP.json",        "OLLCP","3x3 OLLCP"),
    ("COLL.json",         "COLL", "3x3 COLL"),
    ("ZBLL.json",         "ZBLL", "3x3 ZBLL"),
    ("Winter Variation.json", "WV", "3x3 Winter Variation"),
]


# ── case-code 归一化映射 ────────────────────────────────────
# key: set_code, value: { lowercased case name -> normalized code }
# 只在已知 case 上用, 未命中保留 slugify 后的 name 兜底
PLL_CODE_MAP: dict[str, str] = {
    "aa perm": "Aa", "ab perm": "Ab",
    "e perm":  "E",
    "f perm":  "F",
    "ga perm": "Ga", "gb perm": "Gb", "gc perm": "Gc", "gd perm": "Gd",
    "h perm":  "H",
    "ja perm": "Ja", "jb perm": "Jb",
    "na perm": "Na", "nb perm": "Nb",
    "ra perm": "Ra", "rb perm": "Rb",
    "t perm":  "T",
    "ua perm": "Ua", "ub perm": "Ub",
    "v perm":  "V",
    "y perm":  "Y",
    "z perm":  "Z",
}

# OLL 编号固定为 "OLL-<n>"; F2L 用 "F2L-<n>"
OLL_PREFIX = "OLL"
F2L_PREFIX = "F2L"


# ── recognition 文本特征 (jperm 风格, 训练时方便人脑记忆) ────
PLL_RECOGNITION: dict = {}

OLL_SUBSET: dict = {}


# ── 抓取层 ─────────────────────────────────────────────────
class FormulaFetchError(Exception):
    pass


def _http_get_json(url: str, *, timeout: int = 20) -> dict:
    """带 3 次重试的 JSON GET, 无 tenacity 依赖 (避免循环)"""
    last: Exception | None = None
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cstimer-coach/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise FormulaFetchError(f"HTTP {resp.status} for {url}")
                return json.load(resp)
        except (urllib.error.URLError, FormulaFetchError, json.JSONDecodeError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise FormulaFetchError(f"failed GET {url}: {last}")


def fetch_set_json(filename: str, *, cache_dir: str | None = None) -> dict:
    """带磁盘缓存的拉取, 失败抛 FormulaFetchError"""
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, filename.replace(" ", "_"))
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass  # 损坏, 重拉
    url = GITHUB_RAW + "/" + urllib.parse.quote(filename)
    data = _http_get_json(url)
    if cache_dir:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except OSError:
            pass
    return data


# ── 解析层 ─────────────────────────────────────────────────
@dataclass
class ParsedCase:
    name: str
    code: str
    recognition: str | None
    algs: list[tuple[str, int | None]]   # (alg_text, move_count)


def _slug_code(name: str, set_code: str) -> str:
    """兜底归一化: 'Aa perm' -> 'Aa perm' 但 set_code 走自己字典时忽略"""
    n = name.strip()
    if set_code == "PLL":
        return PLL_CODE_MAP.get(n.lower(), n)
    if set_code == "OLL":
        # name 通常是 "OLL 21"
        return n if n.upper().startswith("OLL") else f"OLL {n}"
    if set_code == "F2L":
        return n if n.upper().startswith("F2L") else f"F2L {n}"
    return n


def _recognition_for(code: str, set_code: str) -> str | None:
    """DB 里存英文 (国际通用), 前端按 lang 翻译"""
    return recognition_for(set_code, code, lang="en")


def _safe_move_count(alg: str) -> int | None:
    try:
        return len(parse_moves(alg))
    except Exception:
        return None


def parse_set_payload(payload: dict, set_code: str) -> list[ParsedCase]:
    """从 upstream JSON 抽 cases

    支持两种 case 结构:
      1) {"name": "Aa perm", "algs": [...]}                # PLL/OLL/CMLL...
      2) {"name": "F2L 1", "variants": [{"name":"FR","algs":[...]}, ...]}
                                                          # F2L

    F2L 选 "Front Right" variant 的首选 alg 作为 seq=0, 其余 algs (同 variant 或其它 variant)
    都保留但归到 alt 序列 (1..N), 避免训练执行页里首选混乱
    """
    cases_raw = payload.get("cases") or []
    out: list[ParsedCase] = []
    for idx, c in enumerate(cases_raw):
        name = c.get("name") or f"{set_code} #{idx+1}"

        alg_pairs: list[tuple[str, int | None]] = []
        if isinstance(c.get("algs"), list):
            for a in c["algs"]:
                if not isinstance(a, str) or not a.strip():
                    continue
                alg_pairs.append((a.strip(), _safe_move_count(a)))
        elif isinstance(c.get("variants"), list):
            # 优先选 Front Right variant 的所有 algs 作首选序列; 其它 variant 拼接在后面
            preferred: list[tuple[str, int | None]] = []
            fallback: list[tuple[str, int | None]] = []
            for v in c["variants"]:
                vname = (v.get("name") or "").lower()
                bucket = preferred if vname == "front right" else fallback
                for a in (v.get("algs") or []):
                    if not isinstance(a, str) or not a.strip():
                        continue
                    bucket.append((a.strip(), _safe_move_count(a)))
            alg_pairs = preferred + fallback
        if not alg_pairs:
            continue

        code = _slug_code(name, set_code)
        rec = _recognition_for(code, set_code)
        out.append(ParsedCase(name=name, code=code, recognition=rec, algs=alg_pairs))
    return out


# ── 入库层 ─────────────────────────────────────────────────
def upsert_set(s: Session, *, code: str, puzzle: str, display_name: str, source: str = SOURCE_TAG) -> FormulaSet:
    obj = s.query(FormulaSet).filter(FormulaSet.code == code).one_or_none()
    now = int(time.time() * 1000)
    if obj is None:
        obj = FormulaSet(code=code, puzzle=puzzle, display_name=display_name, source=source, fetched_at=now)
        s.add(obj)
        s.flush()
    else:
        obj.puzzle = puzzle
        obj.display_name = display_name
        obj.source = source
        obj.fetched_at = now
        s.flush()
    return obj


def _mirror_of(code: str, set_code: str) -> str | None:
    if set_code != "PLL":
        return None
    pair = {
        "Aa": "Ab", "Ab": "Aa",
        "Ga": "Gb", "Gb": "Ga", "Gc": "Gd", "Gd": "Gc",
        "Ja": "Jb", "Jb": "Ja",
        "Na": "Nb", "Nb": "Na",
        "Ra": "Rb", "Rb": "Ra",
        "Ua": "Ub", "Ub": "Ua",
    }
    return pair.get(code)


def _is_symmetric(code: str, set_code: str) -> bool:
    if set_code == "PLL":
        return code in {"E", "H", "Z"}  # 已知 self-symmetric
    return False


def upsert_case(s: Session, *, fset: FormulaSet, parsed: ParsedCase, position: int, set_code: str) -> FormulaCase:
    obj = (
        s.query(FormulaCase)
        .filter(FormulaCase.set_id == fset.id, FormulaCase.code == parsed.code)
        .one_or_none()
    )
    if obj is None:
        obj = FormulaCase(
            set_id=fset.id,
            name=parsed.name,
            code=parsed.code,
            recognition=parsed.recognition,
            mirror_of=_mirror_of(parsed.code, set_code),
            position_in_set=position,
            is_symmetric=_is_symmetric(parsed.code, set_code),
        )
        s.add(obj)
        s.flush()
    else:
        obj.name = parsed.name
        obj.recognition = parsed.recognition
        obj.mirror_of = _mirror_of(parsed.code, set_code)
        obj.is_symmetric = _is_symmetric(parsed.code, set_code)
        s.flush()

    # 重建 algs (幂等, 简单粗暴: 清空再插, 数量通常 <= 5)
    s.query(FormulaAlg).filter(FormulaAlg.case_id == obj.id).delete()
    for i, (alg_text, mv) in enumerate(parsed.algs):
        s.add(FormulaAlg(
            case_id=obj.id, seq=i, alg_text=alg_text,
            fingertricks=_guess_fingertricks(alg_text),
            move_count=mv, is_canonical=True,
        ))
    s.flush()
    return obj


def _guess_fingertricks(alg: str) -> str | None:
    """粗略识别: M2-only / 含 M2 / 含 y/z/x 旋转 / 普通"""
    t = alg.strip()
    if t.startswith("M2") and " " not in t.replace("M2", "", 1).strip() and "M'" not in t and "M " not in t and t.count("M2") <= 1:
        return "m2-only"
    if "M2" in t:
        return "m2"
    if t.startswith("y") or " y " in t or t.startswith("y2"):
        return "y-rotated"
    if t.startswith("x") or t.startswith("z"):
        return "xz-rotated"
    return "standard"


def import_one_set(s: Session, *, filename: str, set_code: str, display_name: str, cache_dir: str | None) -> dict:
    payload = fetch_set_json(filename, cache_dir=cache_dir)
    puzzle = payload.get("puzzle") or "3x3"
    fset = upsert_set(s, code=set_code, puzzle=puzzle, display_name=display_name)
    parsed = parse_set_payload(payload, set_code)
    for i, p in enumerate(parsed, start=1):
        upsert_case(s, fset=fset, parsed=p, position=i, set_code=set_code)
    fset.case_count = len(parsed)
    s.flush()
    return {
        "set_code": set_code,
        "case_count": len(parsed),
        "alg_count": sum(len(p.algs) for p in parsed),
    }


def import_all(s: Session, *,
               files: Iterable[tuple[str, str, str]] | None = None,
               cache_dir: str | None = None) -> list[dict]:
    out: list[dict] = []
    for f in (files or DEFAULT_FILES):
        out.append(import_one_set(s, filename=f[0], set_code=f[1], display_name=f[2], cache_dir=cache_dir))
    s.commit()
    return out
