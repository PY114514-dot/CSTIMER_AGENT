"""
Formula Library 单元测试
- parse_set_payload / slug_code / upsert 幂等
- HTTP seed 端点
- 路由查询 (set / case / search)
"""
import os
import json
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

# 在 import app 前设置环境
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LLM_API_KEY", "sk-test-placeholder")

import app.persistence.db as db_mod
from app.persistence.db import Base
from app.persistence import models  # noqa
from app.persistence.formula_importer import (
    parse_set_payload, upsert_set, upsert_case, import_one_set,
    _slug_code, _recognition_for, _guess_fingertricks,
)
from app.persistence.formula_i18n import PLL_RECOGNITION, recognition_for


# ── 解析层 (无 DB) ──────────────────────────────────────────
def test_slug_code_pll_lookup():
    assert _slug_code("Aa perm", "PLL") == "Aa"
    assert _slug_code("ab perm", "PLL") == "Ab"      # case-insensitive
    assert _slug_code("T perm",  "PLL") == "T"
    assert _slug_code("E perm",  "PLL") == "E"


def test_slug_code_oll_uses_oll_prefix():
    assert _slug_code("OLL 21", "OLL") == "OLL 21"
    assert _slug_code("21",     "OLL") == "OLL 21"


def test_slug_code_f2l_uses_f2l_prefix():
    assert _slug_code("F2L 1", "F2L") == "F2L 1"
    assert _slug_code("Pair 3", "F2L") == "F2L Pair 3"


def test_recognition_for_known():
    assert _recognition_for("Aa", "PLL") is not None
    assert "corner" in _recognition_for("Aa", "PLL").lower()
    assert _recognition_for("H", "PLL") is not None


def test_recognition_i18n_bilingual():
    """i18n 模块: zh 与 en 都能拿到"""
    from app.persistence.formula_i18n import recognition_for
    assert recognition_for("PLL", "Aa", "zh") == "两个邻角互换"
    assert recognition_for("PLL", "Aa", "en") == "two adjacent corners swapped"
    # 未知 case 返 None
    assert recognition_for("PLL", "NOPE", "en") is None
    # F2L 走 _default
    assert "F2L" in (recognition_for("F2L", "F2L 99", "zh") or "")


def test_parse_set_payload_basic():
    payload = {
        "puzzle": "3x3",
        "cases": [
            {"name": "Aa perm", "algs": ["R U R' U'", "L' U' L U"]},
            {"name": "T perm",  "algs": ["R U R' U' R' F R2 U' R' F'"]},
            {"name": "junk",    "algs": []},            # 空 algs 跳过
            {"name": "OLL 21",  "algs": ["R U R' U R U2 R'"]},
        ],
    }
    out = parse_set_payload(payload, "PLL")  # 3 个: Aa/T/OLL 21 (junk 跳过)
    out2 = parse_set_payload(payload, "OLL")  # 3 个: OLL 前缀会被加到非 OLL 开头上
    assert len(out) == 3
    assert out[0].code == "Aa"
    assert out[0].recognition == PLL_RECOGNITION["Aa"]["en"]
    assert len(out[0].algs) == 2
    assert out[0].algs[0][1] == 4
    assert out[0].algs[1][1] == 4
    # 集合内 OLL 编号 case 拿真实 recognition, 非 OLL 编号的拿不到 -> None
    oll21 = next(c for c in out2 if c.code == "OLL 21")
    assert oll21.recognition is not None
    assert len(out2) == 3


def test_fingertricks_guess():
    assert _guess_fingertricks("M2 U' M2 U2 M2 U' M2") == "m2"
    assert _guess_fingertricks("R U R' U'") == "standard"
    assert _guess_fingertricks("y R U R' U'") == "y-rotated"
    assert _guess_fingertricks("x R U R'") == "xz-rotated"


def test_parse_set_payload_f2l_variants():
    """F2L case 嵌套 variants, 选 Front Right 的 algs 作首选"""
    payload = {
        "puzzle": "3x3",
        "cases": [
            {
                "name": "F2L 1",
                "variants": [
                    {"name": "Front Right", "algs": ["R U R'", "R U2 R' U' R U R'"]},
                    {"name": "Front Left",  "algs": ["L' U' L"]},
                ],
            },
        ],
    }
    out = parse_set_payload(payload, "F2L")
    assert len(out) == 1
    case = out[0]
    assert case.code == "F2L 1"
    # 首选: FR 的 2 条; 之后: FL 的 1 条
    assert len(case.algs) == 3
    assert case.algs[0][0] == "R U R'"
    assert case.algs[1][0] == "R U2 R' U' R U R'"
    assert case.algs[2][0] == "L' U' L"


# ── 入库层 (用临时 SQLite) ──────────────────────────────────
@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    db_path = tmp_path / f"formula_test_{os.getpid()}_{id(object())}.db"
    eng = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    db_mod.engine = eng
    db_mod.SessionLocal.configure(bind=eng)
    yield
    eng.dispose()


def test_upsert_set_and_case_idempotent():
    with db_mod.SessionLocal() as s:
        fs = upsert_set(s, code="PLL", puzzle="3x3", display_name="PLL")
        s.flush()
        # 二次 upsert 应拿到同一行
        fs2 = upsert_set(s, code="PLL", puzzle="3x3", display_name="PLL")
        s.flush()
        assert fs.id == fs2.id


def test_import_one_set_creates_cases_and_algs():
    """用 cache 文件模拟网络, 验证幂等"""
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "PLL.json"), "w", encoding="utf-8") as f:
        json.dump({
            "puzzle": "3x3",
            "cases": [
                {"name": "Aa perm", "algs": ["R U R' U'", "L' U' L U"]},
                {"name": "H perm",  "algs": ["M2 U' M2 U2 M2 U' M2"]},
            ],
        }, f, ensure_ascii=False)

    with db_mod.SessionLocal() as s:
        r = import_one_set(s, filename="PLL.json", set_code="PLL", display_name="PLL", cache_dir=tmp)
        assert r["case_count"] == 2
        assert r["alg_count"] == 3
        s.commit()
    # 再次导入 (幂等)
    with db_mod.SessionLocal() as s:
        r2 = import_one_set(s, filename="PLL.json", set_code="PLL", display_name="PLL", cache_dir=tmp)
        assert r2["case_count"] == 2
        assert r2["alg_count"] == 3


# ── 路由层 ──────────────────────────────────────────────────
@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def test_formulas_endpoints_empty(client):
    r = client.get("/api/formulas/sets")
    assert r.status_code == 200
    assert r.json() == []

    r = client.get("/api/formulas/sets/PLL")
    assert r.status_code == 404


def test_formulas_seed_with_cache_and_query(client):
    """用真实 slsj31/algdb 上拉一次, 然后用路由查"""
    # 准备一个仿真 cache 文件
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "PLL.json"), "w", encoding="utf-8") as f:
        json.dump({
            "puzzle": "3x3",
            "cases": [
                {"name": "Aa perm", "algs": ["R U R' U'"]},
                {"name": "H perm",  "algs": ["M2 U' M2 U2 M2 U' M2"]},
            ],
        }, f, ensure_ascii=False)

    r = client.post(f"/api/formulas/seed?only=PLL&cache_dir={tmp}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body[0]["set_code"] == "PLL"
    assert body[0]["case_count"] == 2

    r = client.get("/api/formulas/sets")
    assert r.status_code == 200
    codes = [x["code"] for x in r.json()]
    assert "PLL" in codes

    r = client.get("/api/formulas/sets/PLL")
    assert r.status_code == 200
    detail = r.json()
    assert detail["case_count"] == 2
    case_codes = [c["code"] for c in detail["cases"]]
    assert "Aa" in case_codes and "H" in case_codes

    r = client.get("/api/formulas/search?q=aa")
    assert r.status_code == 200
    assert any(c["code"] == "Aa" for c in r.json())

    r = client.get("/api/formulas/search?q=&set=PLL")
    assert r.status_code == 200
    assert len(r.json()) == 2
