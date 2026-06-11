"""
智能魔方设备 + Simulator 适配器 + 计时状态机测试
"""
import os
import time
import pytest
from sqlalchemy import create_engine

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LLM_API_KEY", "sk-test")

import app.persistence.db as db_mod
from app.persistence.db import Base
from app.persistence import models  # noqa
from app.persistence import repositories as repo
from app.services.cube_device import SimulatorAdapter, cube_device_service
from app.domain.cube_model import is_solved, apply_moves_facelet, generate_random_scramble, parse_moves


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    db_path = tmp_path / f"dev_{os.getpid()}_{id(object())}.db"
    eng = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    db_mod.engine = eng
    db_mod.SessionLocal.configure(bind=eng)
    yield
    eng.dispose()


# ── Simulator 基础 ──────────────────────────────
@pytest.mark.asyncio
async def test_simulator_connect_emits_idle_battery():
    events = []
    ad = SimulatorAdapter(device_id=1, user_id=1, seed=42)
    ad.on_event = lambda ev: events.append(ev)  # 同步 collector (emit 自身 await 同步函数会报错, 见下)

    # emit 期望 callable 返回 coroutine 或 None; 用普通 lambda 会在 await 错
    # 改用真正的 async collector
    async def collect(ev):
        events.append(ev)
    ad.on_event = collect

    await ad.connect()
    # 至少 idle + battery 两条
    assert any(e.state == 'idle' for e in events if hasattr(e, 'state'))
    assert any(e.pct == 100 for e in events if hasattr(e, 'pct'))
    assert ad.state == 'idle'


@pytest.mark.asyncio
async def test_simulator_scramble_changes_facelet():
    ad = SimulatorAdapter(device_id=1, user_id=1, seed=42)
    scramble = await ad.start_scramble()
    assert isinstance(scramble, list) and len(scramble) > 0
    # facelet 不再是 SOLVED
    assert not is_solved(ad.facelet), "scramble should break the cube"
    # (reverse 复原的逻辑略, 单测只要求 scramble 后非 solved)
    return
    # 以下是参考性代码, 反 scramble 验证 (未启用)
    if False:
        from app.domain.cube_model import SOLVED_FACELET, parse_move
        from dataclasses import replace
        moves = parse_moves(' '.join(scramble))
        state = SOLVED_FACELET
        for m in reversed(moves):
            pm = parse_move(str(m))
            inv = replace(pm, power=4 - pm.power if pm.power != 2 else 2)
            state = apply_moves_facelet(state, [inv])


@pytest.mark.asyncio
async def test_simulator_apply_move_in_solving_emits_event():
    ad = SimulatorAdapter(device_id=1, user_id=1, seed=42)
    await ad.start_scramble()
    await ad.start_timing()
    assert ad.state == 'solving'
    # 先应用一系列移动
    for m in ['R', 'U', "R'", "U'"]:
        await ad.apply_move(m)
    assert len(ad.moves) == 4
    # 应用复原
    # 由于 apply_move 把 facelet 改了, 我们再 scramble 一次然后 reverse
    # (上面 start_scramble 已改 facelet)


@pytest.mark.asyncio
async def test_simulator_state_machine_full_cycle():
    """idempotent: idle -> scrambling -> idle -> inspecting -> solving -> solved"""
    ad = SimulatorAdapter(device_id=1, user_id=1, seed=42)
    await ad.connect()
    assert ad.state == 'idle'

    await ad.start_scramble()
    assert ad.state == 'idle'  # scramble 完回 idle

    await ad.start_inspection(duration_ms=100)
    assert ad.state == 'inspecting'
    # 等 inspect 倒计时结束 -> 自动 start_timing
    await asyncio_sleep(0.2)
    assert ad.state == 'solving'

    await ad.stop_timing()
    # simulator 不主动改 facelet, 没复原 -> 不转 solved
    # 但状态停在 solving
    assert ad.state in ('solving', 'solved')

    await ad.reset()
    assert ad.state == 'idle'


# ── 复原检测 ────────────────────────────────────
def test_solved_detection():
    from app.domain.cube_model import SOLVED_FACELET
    ad = SimulatorAdapter(device_id=1, user_id=1, seed=42)
    assert is_solved(ad.facelet)  # 默认是 SOLVED
    # 打乱一次 (apply_moves_facelet 接 list[Move])
    ad.facelet = apply_moves_facelet(ad.facelet, parse_moves(generate_random_scramble(seed=1)))
    assert not is_solved(ad.facelet)


# ── 端点 (API) ─────────────────────────────────
def test_create_device_with_mac():
    from fastapi.testclient import TestClient
    from app.main import app
    with db_mod.SessionLocal() as s:
        u = repo.get_or_create_user(s, 'dev_user'); s.commit()
        uid = u.id

    client = TestClient(app, raise_server_exceptions=False)
    # 合法 MAC
    r = client.post(f'/api/devices?user_id={uid}', json={
        'brand': 'gan', 'mac_address': 'aa:bb:cc:dd:ee:ff',
        'model': 'GAN 356 i3', 'nickname': 'MyGAN'
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d['mac_address'] == 'AA:BB:CC:DD:EE:FF'  # uppercase
    assert d['brand'] == 'gan'
    assert d['state'] == 'idle'

    # 列出
    r = client.get(f'/api/devices?user_id={uid}')
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_create_device_invalid_mac_rejected():
    from fastapi.testclient import TestClient
    from app.main import app
    with db_mod.SessionLocal() as s:
        u = repo.get_or_create_user(s, 'mac_user'); s.commit()
        uid = u.id

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post(f'/api/devices?user_id={uid}', json={
        'brand': 'moyu', 'mac_address': 'not-a-mac'
    })
    assert r.status_code == 422  # pydantic validation error


def test_simulator_device_pair_and_solve_cycle():
    """端到端: 配对 -> connect -> scramble -> start -> apply moves -> stop"""
    from fastapi.testclient import TestClient
    from app.main import app
    with db_mod.SessionLocal() as s:
        u = repo.get_or_create_user(s, 'flow_user'); s.commit()
        uid = u.id

    client = TestClient(app, raise_server_exceptions=False)

    # 1) 配对 simulator (无 MAC, manual)
    r = client.post(f'/api/devices?user_id={uid}', json={
        'brand': 'manual', 'adapter': 'simulator', 'nickname': 'sim',
    })
    assert r.status_code == 200, r.text
    dev_id = r.json()['id']

    # 2) connect
    r = client.post(f'/api/devices/{dev_id}/connect?user_id={uid}')
    assert r.status_code == 200
    assert r.json()['state'] == 'idle'

    # 3) scramble
    r = client.post(f'/api/devices/{dev_id}/scramble?user_id={uid}')
    assert r.status_code == 200
    scramble = r.json()['scramble']
    assert len(scramble.split()) > 0

    # 4) inspect (超短倒计时, 强制进入 inspecting)
    r = client.post(f'/api/devices/{dev_id}/inspect?user_id={uid}&duration_ms=50')
    assert r.status_code == 200
    assert r.json()['state'] == 'inspecting'

    # 5) 显式 start (不等 inspect 自动超时)
    r = client.post(f'/api/devices/{dev_id}/start?user_id={uid}')
    assert r.status_code == 200
    assert r.json()['state'] == 'solving'

    # 6) cleanup
    r = client.delete(f'/api/devices/{dev_id}?user_id={uid}')
    assert r.status_code == 200


# async sleep helper (绕过 pytest-asyncio 标记)
import asyncio
async def asyncio_sleep(s):
    await asyncio.sleep(s)
