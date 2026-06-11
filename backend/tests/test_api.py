"""
FastAPI 路由层集成测试
"""
import os
import json
import pytest
import tempfile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 在 import app 前设置环境
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LLM_API_KEY", "sk-test-placeholder")

import app.persistence.db as db_mod
from app.persistence.db import Base
from app.persistence import models  # noqa


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    """每个测试用临时文件, 显式 init_db (绕开 lifespan)"""
    db_path = tmp_path / f"api_test_{os.getpid()}_{id(object())}.db"
    eng = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    db_mod.engine = eng
    db_mod.SessionLocal.configure(bind=eng)
    yield
    eng.dispose()


@pytest.fixture
def client():
    from app.main import app
    # 绕开 lifespan, 直接用 (因为 fixture 已经建表)
    return TestClient(app, raise_server_exceptions=False)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


def test_root(client):
    # / 现在返 SPA HTML (前端 dist 加载时); 元信息挪到 /api/info
    r = client.get("/")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    if "text/html" in ct:
        # 前端 dist 已构建 (在 dev/CI 都会)
        assert "<!doctype" in r.text.lower() or "<html" in r.text.lower()
    else:
        # 兼容: 无 dist 时 / 走 catch-all 也返 200 但不是 HTML
        body = r.json()
        assert "CSTIMER" in body.get("name", "")


def test_api_info(client):
    r = client.get("/api/info")
    assert r.status_code == 200
    body = r.json()
    assert "CSTIMER" in body["name"]


def test_user_crud(client):
    r = client.post("/api/users", json={"username": "alice", "display_name": "Alice"})
    assert r.status_code == 200, r.text
    user = r.json()
    uid = user["id"]
    assert user["username"] == "alice"

    r = client.get(f"/api/users/{uid}")
    assert r.status_code == 200
    assert r.json()["id"] == uid

    # 重复 username 不会创建
    r = client.post("/api/users", json={"username": "alice"})
    assert r.json()["id"] == uid


def test_solve_lifecycle(client):
    # 1. 创建用户
    r = client.post("/api/users", json={"username": "bob"})
    uid = r.json()["id"]

    # 2. start solve
    r = client.post("/api/solves/start", json={"user_id": uid, "scramble": "R U R' U'"})
    assert r.status_code == 200, r.text
    solve = r.json()
    cube_id = solve["cube_id"]
    assert solve["scramble"] == "R U R' U'"

    # 3. add moves
    for i, mv in enumerate(["R", "U", "R'", "U'"]):
        r = client.post(f"/api/solves/{cube_id}/moves",
                        json={"move": mv, "timestamp_ms": 1000 * (i + 1)})
        assert r.status_code == 200, r.text
        assert r.json()["seq"] == i

    # 4. finish
    r = client.post(f"/api/solves/{cube_id}/finish")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["move_count"] == 4
    assert body["total_time_ms"] >= 0


def test_session_aggregate_and_training(client):
    # 用户
    r = client.post("/api/users", json={"username": "carol"})
    uid = r.json()["id"]

    # 创建 session
    r = client.post("/api/sessions", json={"user_id": uid, "target_size": 3})
    assert r.status_code == 200
    sess_id = r.json()["id"]

    # 模拟 3 把
    for i in range(3):
        r = client.post("/api/solves/start",
                        json={"user_id": uid, "session_id": sess_id})
        cube_id = r.json()["cube_id"]
        for j, mv in enumerate(["R", "U", "R'", "U'"]):
            client.post(f"/api/solves/{cube_id}/moves",
                        json={"move": mv, "timestamp_ms": 200 * (j + 1) + i * 1000})
        r = client.post(f"/api/solves/{cube_id}/finish")
        assert r.status_code == 200

    # 关闭 session
    r = client.post(f"/api/sessions/{sess_id}/close")
    assert r.status_code == 200
    assert r.json()["status"] == "closed"

    # 聚合
    r = client.post(f"/api/sessions/{sess_id}/aggregate")
    assert r.status_code == 200
    stats = r.json()["stats"]
    assert stats["solve_count"] == 3
    assert stats["avg_total_ms"] is not None

    # 生成训练项
    r = client.post(f"/api/sessions/{sess_id}/generate-training")
    assert r.status_code == 200
    body = r.json()
    assert "training_tasks" in body
    # 3 把太少, 可能没有规则触发, 但不应崩


def test_session_detail(client):
    r = client.post("/api/users", json={"username": "dave"})
    uid = r.json()["id"]
    r = client.post("/api/sessions", json={"user_id": uid})
    sid = r.json()["id"]
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["session"]["id"] == sid
    assert "cubes" in body
    assert "training_tasks" in body


def test_dashboard_today(client):
    r = client.post("/api/users", json={"username": "eve"})
    uid = r.json()["id"]
    r = client.get(f"/api/dashboard/today?user_id={uid}")
    assert r.status_code == 200
    body = r.json()
    assert "date" in body
    assert "training_tasks" in body
    assert "trend_30" in body


def test_recommend_goal(client):
    r = client.post("/api/users", json={"username": "frank"})
    uid = r.json()["id"]
    r = client.post(f"/api/dashboard/recommend-goal?user_id={uid}")
    assert r.status_code == 200
    assert "target_value" in r.json()


def test_training_mark_done(client):
    r = client.post("/api/users", json={"username": "gina"})
    uid = r.json()["id"]
    # 手动插一条训练项
    from app.persistence import repositories as repo
    with db_mod.SessionLocal() as s:
        ids = repo.add_training_tasks(s, [{
            "user_id": uid,
            "category": "f2l",
            "title": "test task",
            "target_metric": "f2l_obs",
            "duration_min": 10,
            "status": "pending",
        }])
        s.commit()
        task_id = ids[0]

    # 标完成
    r = client.post(f"/api/training/{task_id}/done", json={"result": {"self_rating": 4}})
    assert r.status_code == 200
    assert r.json()["status"] == "done"


def test_import_cstimer(client, tmp_path):
    export = {
        "properties": {},
        "session1": [
            [[0, 12000], "R U R' U'", "", 100],
            [[0, 11500], "F R U R' U' F'", "", 200],
        ],
    }
    f = tmp_path / "export.json"
    f.write_text(json.dumps(export), encoding="utf-8")

    with open(f, "rb") as fp:
        r = client.post(
            "/api/import/cstimer",
            files={"file": ("export.json", fp, "application/json")},
            data={"username": "importer"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sessions_imported"] >= 1
    assert body["cubes_imported"] >= 2


def test_invalid_move_rejected(client):
    r = client.post("/api/users", json={"username": "hank"})
    uid = r.json()["id"]
    r = client.post("/api/solves/start", json={"user_id": uid})
    cube_id = r.json()["cube_id"]
    r = client.post(f"/api/solves/{cube_id}/moves", json={"move": "Q"})
    assert r.status_code == 400
