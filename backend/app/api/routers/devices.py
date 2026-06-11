"""
智能魔方设备管理 + 计时状态机 API
  GET    /api/devices                 -> 列出当前用户已配对设备
  POST   /api/devices                 -> 手动配对 (输入 MAC / brand / model)
  PATCH  /api/devices/{id}            -> 改昵称 / model
  DELETE /api/devices/{id}            -> 解绑
  POST   /api/devices/{id}/connect    -> 连上, ws_manager 绑事件回调
  POST   /api/devices/{id}/scramble   -> 触发打乱, 推 state event
  POST   /api/devices/{id}/inspect    -> 触发观察倒计时
  POST   /api/devices/{id}/start      -> 触发开始计时
  POST   /api/devices/{id}/stop       -> 触发结束计时 (检测复原)
  POST   /api/devices/{id}/apply-move -> 录入单动 (供 v1 simulator UI 按钮 或 v2 真硬件 WS 转发)
  POST   /api/devices/{id}/reset      -> 重置 (回到 idle)
"""
from __future__ import annotations
import logging
import re
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.persistence import repositories as repo
from app.persistence.db import SessionLocal
from app.persistence.models import CubeDevice, Cube, MoveEvent
from app.services.cube_device import cube_device_service, SimulatorAdapter
from app.api.ws import ws_manager
from app.domain.cube_model import apply_moves_facelet, parse_move, is_solved
from app.domain.cfop_detector import CFOPStageDetector
from app.domain.pause_analyzer import PauseAnalyzer
from app.domain.move_efficiency import MoveEfficiency

logger = logging.getLogger("cstimer-coach.devices")
router = APIRouter(prefix="/api/devices", tags=["devices"])

# MAC 校验: XX:XX:XX:XX:XX:XX (12 个十六进制)
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")


# ── Schemas ────────────────────────────────────────
class DeviceCreateReq(BaseModel):
    brand: str = Field(..., description="gan/moyu/qiyi/gocube/giiker/manual")
    mac_address: Optional[str] = Field(None, description="XX:XX:XX:XX:XX:XX, 留空 = simulator")
    model: Optional[str] = None
    nickname: Optional[str] = None
    protocol: Optional[str] = "manual"
    adapter: Optional[str] = "simulator"

    @field_validator("mac_address")
    @classmethod
    def _v_mac(cls, v: Optional[str]):
        if v is None or v == "":
            return None
        v = v.strip().upper()
        if not MAC_RE.match(v):
            raise ValueError(f"invalid MAC format: {v} (expected XX:XX:XX:XX:XX:XX)")
        return v


class DeviceResp(BaseModel):
    id: int
    brand: Optional[str]
    model: Optional[str]
    mac_address: Optional[str]
    nickname: Optional[str]
    protocol: str
    adapter: str
    battery_pct: Optional[int]
    state: str
    last_event_at: Optional[int]
    paired_at: Optional[int]
    last_sync_at: Optional[int]


class ApplyMoveReq(BaseModel):
    move: str

# ── helpers ────────────────────────────────────────
def _to_resp(d: CubeDevice) -> DeviceResp:
    return DeviceResp(
        id=d.id, brand=d.brand, model=d.model, mac_address=d.mac_address,
        nickname=d.nickname, protocol=d.protocol, adapter=d.adapter,
        battery_pct=d.battery_pct, state=d.state, last_event_at=d.last_event_at,
        paired_at=d.paired_at, last_sync_at=d.last_sync_at,
    )


def _get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


# ── 事件回调: 写库 + WS 广播 ──────────────────────
async def _device_event_handler(user_id: int, device_id: int, ev):
    """CubeAdapter 事件 → 写库 + WS 广播 + (move) 阶段回填"""
    from app.services.cube_device import MoveEvent, StateEvent, BatteryEvent

    now = int(time.time() * 1000)
    with SessionLocal() as s:
        dev = s.get(CubeDevice, device_id)
        if dev:
            dev.last_event_at = now
            if isinstance(ev, StateEvent):
                dev.state = ev.state
            elif isinstance(ev, BatteryEvent):
                dev.battery_pct = ev.pct
            s.commit()

    # WS 广播到该 user
    payload = {
        "device_id": device_id,
        "ts": now,
    }
    if isinstance(ev, MoveEvent):
        payload["event"] = "cube_move"
        payload["data"] = {
            "move": ev.move,
            "timestamp_ms": ev.timestamp_ms,
            "absolute_ms": ev.absolute_ms,
        }
    elif isinstance(ev, StateEvent):
        payload["event"] = "cube_state"
        payload["data"] = {"state": ev.state, "ts": ev.timestamp_ms}
    elif isinstance(ev, BatteryEvent):
        payload["event"] = "cube_battery"
        payload["data"] = {"pct": ev.pct}
    else:
        return
    await ws_manager.broadcast(payload["event"], payload["data"])


# ── 列出设备 ────────────────────────────────────────
@router.get("", response_model=list[DeviceResp])
def list_devices(user_id: int, db: Session = Depends(_get_db)):
    rows = list(db.scalars(
        select(CubeDevice).where(CubeDevice.user_id == user_id).order_by(desc(CubeDevice.paired_at))
    ))
    return [_to_resp(r) for r in rows]


# ── 手动配对 ────────────────────────────────────────
@router.post("", response_model=DeviceResp)
def create_device(user_id: int, req: DeviceCreateReq, db: Session = Depends(_get_db)):
    now = int(time.time() * 1000)
    d = CubeDevice(
        user_id=user_id, brand=req.brand, model=req.model,
        mac_address=req.mac_address, nickname=req.nickname,
        protocol=req.protocol or "manual",
        adapter=req.adapter or "simulator",
        battery_pct=None, state="idle",
        paired_at=now, last_sync_at=now,
    )
    db.add(d); db.commit(); db.refresh(d)
    return _to_resp(d)


# ── 改昵称 / model ──────────────────────────────────
class DeviceUpdateReq(BaseModel):
    nickname: Optional[str] = None
    model: Optional[str] = None

@router.patch("/{device_id}", response_model=DeviceResp)
def update_device(device_id: int, req: DeviceUpdateReq, user_id: int, db: Session = Depends(_get_db)):
    d = db.get(CubeDevice, device_id)
    if not d or d.user_id != user_id:
        raise HTTPException(404, "device not found")
    if req.nickname is not None: d.nickname = req.nickname
    if req.model is not None: d.model = req.model
    d.last_sync_at = int(time.time() * 1000)
    db.commit(); db.refresh(d)
    return _to_resp(d)


# ── 解绑 ────────────────────────────────────────────
@router.delete("/{device_id}")
def delete_device(device_id: int, user_id: int, db: Session = Depends(_get_db)):
    d = db.get(CubeDevice, device_id)
    if not d or d.user_id != user_id:
        raise HTTPException(404, "device not found")
    cube_device_service.drop(user_id=user_id, device_id=device_id)
    db.delete(d); db.commit()
    return {"ok": True}


# ── 连上 / 准备推送事件 ────────────────────────────
@router.post("/{device_id}/connect")
async def connect_device(device_id: int, user_id: int, db: Session = Depends(_get_db)):
    d = db.get(CubeDevice, device_id)
    if not d or d.user_id != user_id:
        raise HTTPException(404, "device not found")
    adapter = cube_device_service.get_or_create(
        user_id=user_id, device_id=device_id, brand=d.brand or "manual",
        adapter_type=d.adapter,
    )
    adapter.on_event = lambda ev: _device_event_handler(user_id, device_id, ev)
    await adapter.connect()
    return {"ok": True, "state": adapter.state, "battery_pct": adapter.battery_pct}


# ── 打乱 / 观察 / 开始 / 停止 / 重置 ───────────────
@router.post("/{device_id}/scramble")
async def scramble_device(device_id: int, user_id: int, db: Session = Depends(_get_db)):
    d = db.get(CubeDevice, device_id)
    if not d or d.user_id != user_id:
        raise HTTPException(404, "device not found")
    adapter = cube_device_service.get_or_create(user_id=user_id, device_id=device_id)
    scramble_moves = await adapter.start_scramble()
    return {"ok": True, "scramble": " ".join(scramble_moves)}


@router.post("/{device_id}/inspect")
async def inspect_device(device_id: int, user_id: int, db: Session = Depends(_get_db),
                        duration_ms: int = 15_000):
    d = db.get(CubeDevice, device_id)
    if not d or d.user_id != user_id:
        raise HTTPException(404, "device not found")
    adapter = cube_device_service.get_or_create(user_id=user_id, device_id=device_id)
    await adapter.start_inspection(duration_ms=duration_ms)
    return {"ok": True, "state": adapter.state, "deadline_ms": adapter.inspect_deadline_ms}


@router.post("/{device_id}/start")
async def start_device(device_id: int, user_id: int, db: Session = Depends(_get_db)):
    """开始计时: 创建 solve, 把后续 move 写到 moves 表"""
    d = db.get(CubeDevice, device_id)
    if not d or d.user_id != user_id:
        raise HTTPException(404, "device not found")
    adapter = cube_device_service.get_or_create(user_id=user_id, device_id=device_id)
    if not adapter.session_start_ms:
        await adapter.start_timing()
    # 创建 cube 记录, 把 adapter 后续产生的 move 写到这里
    with SessionLocal() as s:
        sess = repo.get_open_session(s, user_id)
        if not sess:
            sess = repo.create_session(s, user_id=user_id)
        cube = repo.create_cube(
            s,
            user_id=user_id, session_id=sess.id, puzzle_type="333",
            scramble=getattr(adapter, 'current_scramble', '') or "(simulator)",
            started_at=adapter.session_start_ms,
            ended_at=0,
            total_time_ms=0, move_count=0,
            source=f"device:{d.brand}",
        )
        s.commit()
        # 后续 move 写这里
        adapter._current_cube_id = cube.id
    return {"ok": True, "state": adapter.state, "cube_id": adapter._current_cube_id}


@router.post("/{device_id}/stop")
async def stop_device(device_id: int, user_id: int, db: Session = Depends(_get_db)):
    """结束计时: 算总时长, 跑阶段检测 + 停顿分析, 写 stages/pauses"""
    d = db.get(CubeDevice, device_id)
    if not d or d.user_id != user_id:
        raise HTTPException(404, "device not found")
    adapter = cube_device_service.get_or_create(user_id=user_id, device_id=device_id)
    if not hasattr(adapter, '_current_cube_id') or not adapter._current_cube_id:
        raise HTTPException(400, "no active cube to stop")
    cube_id = adapter._current_cube_id
    now = int(time.time() * 1000)
    total_ms = now - adapter.session_start_ms if adapter.session_start_ms else 0
    with SessionLocal() as s:
        cube = s.get(Cube, cube_id)
        if not cube:
            raise HTTPException(404, "cube not found")
        cube.ended_at = now
        cube.total_time_ms = total_ms
        cube.move_count = len(adapter.moves)
        # 写 move_events (apply_move 时已经写过, 这里只补缺失的, 幂等)
        existing = list(s.scalars(
            select(MoveEvent.seq).where(MoveEvent.solve_id == cube_id).order_by(MoveEvent.seq)
        ))
        existing_set = set(existing)
        for i, m in enumerate(adapter.moves):
            if i in existing_set:
                continue
            s.add(MoveEvent(
                solve_id=cube_id, seq=i, move_text=m.move,
                is_smart_turn=False, timestamp_ms=m.timestamp_ms,
                absolute_ms=m.absolute_ms, stage_label=None,
            ))
        s.commit()

        # 阶段检测 + 停顿 + 效率 (复用 solve_recorder 思路)
        if len(adapter.moves) >= 3:
            moves_with_ts = [(parse_move(m.move), m.timestamp_ms) for m in adapter.moves]
            try:
                detector = CFOPStageDetector()
                stages = detector.detect(moves_with_ts, total_ms, getattr(adapter, 'current_scramble', None))
                repo.upsert_stages(s, cube_id, **stages.dur_dict(),
                                    f2l_pairs=stages.f2l_pairs,
                                    detected_method=stages.method,
                                    confidence=stages.confidence)
                # 停顿
                pa = PauseAnalyzer(threshold_ms=500)
                moves_with_seq = [(parse_move(m.move), m.timestamp_ms, i) for i, m in enumerate(adapter.moves)]
                label_ranges = stages.as_label_ranges(total_ms)
                repo.replace_pauses(s, cube_id, [p.to_dict() for p in pa.analyze(moves_with_seq, label_ranges)])
                # 回填 stage_label
                repo.backfill_move_stages(s, cube_id, label_ranges)
                # 算 effective moves
                eff = MoveEfficiency()
                stats = eff.analyze(moves_with_ts, label_ranges)
                # 简单: 把 effective 写到 cube 的某字段 (这里没建字段, 仅返回给前端)
                s.commit()
            except Exception as e:
                logger.warning(f"stage/pause detect failed: {e}")
        # 关闭 session 计数
        if cube.session_id:
            sess = s.get(__import__('app.persistence.models', fromlist=['TrainingSession']).TrainingSession, cube.session_id)
            if sess:
                sess.cube_count = (sess.cube_count or 0) + 1
        s.commit()
        # 检测是否复原
        solved = is_solved(adapter.facelet)
        if solved:
            adapter.state = "solved"
        # 取 cube 详情
        from app.api.routers.sessions import _to_task_resp
        from app.persistence.models import TrainingTask
        tasks = list(s.scalars(select(TrainingTask).where(TrainingTask.user_id == user_id,
                                                          TrainingTask.created_at >= now - 86400000)))
        return {
            "ok": True,
            "state": adapter.state,
            "solved": solved,
            "total_time_ms": total_ms,
            "move_count": len(adapter.moves),
            "cube_id": cube_id,
        }


@router.post("/{device_id}/reset")
async def reset_device(device_id: int, user_id: int, db: Session = Depends(_get_db)):
    d = db.get(CubeDevice, device_id)
    if not d or d.user_id != user_id:
        raise HTTPException(404, "device not found")
    adapter = cube_device_service.get_or_create(user_id=user_id, device_id=device_id)
    await adapter.reset()
    if hasattr(adapter, '_current_cube_id'):
        delattr(adapter, '_current_cube_id')
    return {"ok": True, "state": adapter.state}


@router.post("/{device_id}/apply-move")
async def apply_move_device(device_id: int, req: ApplyMoveReq,
                            user_id: int, db: Session = Depends(_get_db)):
    """录入单动 (v1: simulator 3D UI; v2: 真硬件 WS 转发)"""
    d = db.get(CubeDevice, device_id)
    if not d or d.user_id != user_id:
        raise HTTPException(404, "device not found")
    adapter = cube_device_service.get_or_create(user_id=user_id, device_id=device_id)
    await adapter.apply_move(req.move)
    # 实时写库: 真硬件模式下 move 是硬件推过来的, simulator 下是前端按钮 -> 也走这里
    if hasattr(adapter, '_current_cube_id') and adapter._current_cube_id:
        cube_id = adapter._current_cube_id
        with SessionLocal() as s:
            seq = len(adapter.moves) - 1  # 已 add 过了
            if seq >= 0:
                last = adapter.moves[-1]
                # 幂等: 避免重复
                existing = s.scalar(
                    select(MoveEvent).where(MoveEvent.solve_id == cube_id, MoveEvent.seq == seq)
                )
                if not existing:
                    s.add(MoveEvent(
                        solve_id=cube_id, seq=seq, move_text=last.move,
                        is_smart_turn=False, timestamp_ms=last.timestamp_ms,
                        absolute_ms=last.absolute_ms, stage_label=None,
                    ))
                    s.commit()
    return {"ok": True, "state": adapter.state, "move_count": len(adapter.moves)}
