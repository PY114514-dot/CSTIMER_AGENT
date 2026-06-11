"""
WebSocket 真实环境手动验证脚本 (非 pytest, 避免死锁)
用法: python scripts/test_websocket_manual.py
需要: pip install websockets
"""
import os
import sys
import json
import time
import asyncio
import socket
import subprocess
import urllib.request

import websockets


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _http(url, method="GET", data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


async def wait_event(port, uid, expect_event, trigger_fn, timeout=5):
    """连接 WS, 触发事件, 等一个事件"""
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws/user/{uid}") as ws:
        # 触发
        trigger_fn()
        # 等目标事件 (跳过别的)
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=end - time.time())
                obj = json.loads(msg)
                if obj["event"] == expect_event:
                    return obj
            except asyncio.TimeoutError:
                return None
        return None


def main():
    port = _free_port()
    db_path = f"/tmp/ws_manual_{port}.db"
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["LLM_API_KEY"] = "sk-test-placeholder"
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    ws_base = f"ws://127.0.0.1:{port}"

    # 等 server 起来
    for _ in range(30):
        try:
            urllib.request.urlopen(f"{base}/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.3)
    print(f"[ok] server up at {base}")

    try:
        # 1. 用户
        user = _http(f"{base}/api/users", "POST", {"username": f"wsm{int(time.time()*1000)}"})
        uid = user["id"]
        print(f"[ok] user created uid={uid}")

        # 2. test: solve_started 事件
        async def test_solve_started():
            return await wait_event(port, uid, "solve_started",
                lambda: _http(f"{base}/api/solves/start", "POST", {"user_id": uid}),
                timeout=5)

        result = asyncio.run(test_solve_started())
        assert result is not None, "solve_started event not received"
        assert result["data"]["scramble"]
        print(f"[ok] solve_started received: scramble={result['data']['scramble'][:30]}...")

        # 3. test: move_recorded 事件
        solve = _http(f"{base}/api/solves/start", "POST", {"user_id": uid})
        cube_id = solve["cube_id"]

        async def test_move_recorded():
            return await wait_event(port, uid, "move_recorded",
                lambda: _http(f"{base}/api/solves/{cube_id}/moves", "POST",
                               {"move": "R", "timestamp_ms": 100}),
                timeout=5)

        result = asyncio.run(test_move_recorded())
        assert result is not None, "move_recorded not received"
        assert result["data"]["move"] == "R"
        assert result["data"]["seq"] == 0
        print(f"[ok] move_recorded received: move=R seq=0")

        # 4. test: solve_finished 事件
        async def test_solve_finished():
            return await wait_event(port, uid, "solve_finished",
                lambda: _http(f"{base}/api/solves/{cube_id}/finish", "POST", {}),
                timeout=10)

        result = asyncio.run(test_solve_finished())
        assert result is not None, "solve_finished not received"
        assert result["data"]["cube_id"] == cube_id
        assert result["data"]["move_count"] >= 1
        print(f"[ok] solve_finished received: move_count={result['data']['move_count']}")

        # 5. test: session_closed 事件
        sess = _http(f"{base}/api/sessions", "POST", {"user_id": uid})
        sid = sess["id"]

        async def test_session_closed():
            return await wait_event(port, uid, "session_closed",
                lambda: _http(f"{base}/api/sessions/{sid}/close", "POST", {}),
                timeout=5)

        result = asyncio.run(test_session_closed())
        assert result is not None, "session_closed not received"
        print(f"[ok] session_closed received")

        # 6. test: 全局广播
        async def test_global():
            async with websockets.connect(f"{ws_base}/ws") as ws:
                # 先在后台线程触发事件
                import threading
                threading.Thread(
                    target=lambda: _http(f"{base}/api/solves/start", "POST", {"user_id": uid}),
                    daemon=True
                ).start()
                msg = await asyncio.wait_for(ws.recv(), timeout=8)
                return json.loads(msg)

        result = asyncio.run(test_global())
        assert result["event"] == "solve_started", f"got: {result}"
        print(f"[ok] global broadcast received solve_started")

        # 7. test: session 频道
        solve = _http(f"{base}/api/solves/start", "POST", {"user_id": uid})
        cube_id = solve["cube_id"]
        session_id = solve["session_id"]

        async def test_session_channel():
            async with websockets.connect(f"{ws_base}/ws/session/{session_id}") as ws:
                _http(f"{base}/api/solves/{cube_id}/moves", "POST",
                      {"move": "U", "timestamp_ms": 200})
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                return json.loads(msg)

        result = asyncio.run(test_session_channel())
        assert result["event"] == "move_recorded"
        print(f"[ok] session channel received move_recorded")

        # 8. test: AI 异步分析 endpoint 立即返回
        sess = _http(f"{base}/api/sessions", "POST", {"user_id": uid})
        sid = sess["id"]
        t0 = time.time()
        r = _http(f"{base}/api/ai/sessions/{sid}/analyze?user_level=初学", "POST", {})
        elapsed = time.time() - t0
        assert "session_id" in r, f"bad response: {r}"
        assert elapsed < 1.0, f"async endpoint took {elapsed:.2f}s, should be < 1s"
        print(f"[ok] AI async endpoint returned in {elapsed*1000:.0f}ms (no blocking)")

        print()
        print("=" * 50)
        print("ALL WEBSOCKET TESTS PASSED")
        print("=" * 50)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            os.unlink(db_path)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
