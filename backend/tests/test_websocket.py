"""
WebSocket 集成测试 - 用真 uvicorn + websockets 客户端
(避开 TestClient.websocket_connect 在 sync-route fire-and-forget 时的死锁)
"""
import os
import json
import time
import threading
import subprocess
import sys
import socket
import asyncio
import urllib.request
import pytest


# 检查 websockets 库
try:
    import websockets
except ImportError:
    pytest.skip("websockets not installed", allow_module_level=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    """启动一个真的 uvicorn 服务器"""
    port = _free_port()
    db_path = f"/tmp/ws_e2e_{port}.db"
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["LLM_API_KEY"] = "sk-test-placeholder"

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    base_url = f"http://127.0.0.1:{port}"
    # 等待 server 起来
    for _ in range(30):
        try:
            urllib.request.urlopen(f"{base_url}/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        raise RuntimeError("server failed to start")

    yield base_url
    proc.terminate()
    proc.wait(timeout=5)
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass


def _http_post(url: str, data: dict) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _http_get(url: str) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_websocket_broadcasts_solve_started(server):
    user = _http_post(f"{server}/api/users", {"username": f"ws_{int(time.time()*1000)}"})
    uid = user["id"]

    async def runner():
        async with websockets.connect(f"ws://127.0.0.1:{server.split(':')[-1]}/ws/user/{uid}") as ws:
            # 触发事件
            _http_post(f"{server}/api/solves/start",
                       {"user_id": uid, "scramble": "R U"})
            msg = await asyncio.wait_for(ws.recv(), timeout=3)
            return json.loads(msg)

    msg = asyncio.run(runner())
    assert msg["event"] == "solve_started"
    assert msg["data"]["scramble"] == "R U"


def test_websocket_broadcasts_move_recorded(server):
    user = _http_post(f"{server}/api/users", {"username": f"ws2_{int(time.time()*1000)}"})
    uid = user["id"]
    solve = _http_post(f"{server}/api/solves/start", {"user_id": uid})
    cube_id = solve["cube_id"]

    async def runner():
        async with websockets.connect(f"ws://127.0.0.1:{server.split(':')[-1]}/ws/user/{uid}") as ws:
            # 跳过 solve_started
            await ws.recv()
            # 触发 move_recorded
            _http_post(f"{server}/api/solves/{cube_id}/moves",
                       {"move": "R", "timestamp_ms": 100})
            msg = await asyncio.wait_for(ws.recv(), timeout=3)
            return json.loads(msg)

    msg = asyncio.run(runner())
    assert msg["event"] == "move_recorded"
    assert msg["data"]["move"] == "R"
    assert msg["data"]["seq"] == 0


def test_websocket_session_channel(server):
    user = _http_post(f"{server}/api/users", {"username": f"ws3_{int(time.time()*1000)}"})
    uid = user["id"]
    solve = _http_post(f"{server}/api/solves/start", {"user_id": uid})
    cube_id = solve["cube_id"]
    session_id = solve["session_id"]
    port = server.split(":")[-1]

    async def runner():
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws/session/{session_id}") as ws:
            await ws.recv()  # skip solve_started
            _http_post(f"{server}/api/solves/{cube_id}/moves",
                       {"move": "U", "timestamp_ms": 200})
            msg = await asyncio.wait_for(ws.recv(), timeout=3)
            return json.loads(msg)

    msg = asyncio.run(runner())
    assert msg["event"] == "move_recorded"


def test_websocket_session_closed(server):
    user = _http_post(f"{server}/api/users", {"username": f"ws4_{int(time.time()*1000)}"})
    uid = user["id"]
    sess = _http_post(f"{server}/api/sessions", {"user_id": uid})
    sid = sess["id"]

    async def runner():
        async with websockets.connect(f"ws://127.0.0.1:{server.split(':')[-1]}/ws/user/{uid}") as ws:
            _http_post(f"{server}/api/sessions/{sid}/close")
            msg = await asyncio.wait_for(ws.recv(), timeout=3)
            return json.loads(msg)

    msg = asyncio.run(runner())
    assert msg["event"] == "session_closed"
    assert msg["data"]["session_id"] == sid


def test_websocket_global_broadcast(server):
    user = _http_post(f"{server}/api/users", {"username": f"ws5_{int(time.time()*1000)}"})
    uid = user["id"]

    async def runner():
        async with websockets.connect(f"ws://127.0.0.1:{server.split(':')[-1]}/ws") as ws:
            _http_post(f"{server}/api/solves/start", {"user_id": uid})
            msg = await asyncio.wait_for(ws.recv(), timeout=3)
            return json.loads(msg)

    msg = asyncio.run(runner())
    assert msg["event"] == "solve_started"


def test_ai_async_returns_immediately(server):
    user = _http_post(f"{server}/api/users", {"username": f"ai_{int(time.time()*1000)}"})
    uid = user["id"]
    sess = _http_post(f"{server}/api/sessions", {"user_id": uid})
    sid = sess["id"]
    r = _http_post(f"{server}/api/ai/sessions/{sid}/analyze?user_level=初学", {})
    assert "session_id" in r
    assert "websocket" in r
