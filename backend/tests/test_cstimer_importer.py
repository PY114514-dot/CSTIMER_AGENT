"""
测试 cstimer 导入器
"""
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    import os
    db_path = tmp_path / f"test_import_{os.getpid()}_{id(object())}.db"
    from app.persistence.db import Base
    from app.persistence import models  # noqa
    eng = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    TestSession = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)

    import app.persistence.db as db_mod
    db_mod.SessionLocal.configure(bind=eng)
    db_mod.engine = eng
    yield
    db_mod.SessionLocal.configure(bind=db_mod._original_engine)


def test_parse_export_json(tmp_path):
    # 构造一个最小 cstimer 导出 (time_array 是 list)
    export = {
        "properties": {"useIns": "a"},
        "session1": [
            [[0, 12000], "R U R' U'", "", 100],
            [[0, 11500], "F R U R' U' F'", "", 200],
            [[-1, 0],    "D' L' D L", "", 300],   # DNF (penalty=-1)
        ],
        "session2": [],
    }
    f = tmp_path / "export.json"
    f.write_text(json.dumps(export), encoding="utf-8")

    from app.persistence.cstimer_importer import parse_export_json
    parsed = parse_export_json(str(f))
    assert 1 in parsed["sessions"]
    assert len(parsed["sessions"][1]) == 3
    assert parsed["sessions"][1][2][0][0] == -1  # DNF


def test_import_from_file(tmp_path):
    export = {
        "properties": {},
        "session1": [
            [[0, 10000], "R U R' U'", "", 100],
            [[0, 10500], "R U R' U'", "", 200],
        ],
    }
    f = tmp_path / "export.json"
    f.write_text(json.dumps(export), encoding="utf-8")

    from app.persistence.cstimer_importer import import_from_file
    from app.persistence.db import SessionLocal
    from app.persistence.models import Cube, TrainingSession
    sessions = import_from_file(str(f), username="importer")
    assert len(sessions) == 1
    with SessionLocal() as s:
        cubes = list(s.query(Cube).all())
        assert len(cubes) == 2
        assert all(c.session_id == sessions[0].id for c in cubes)
