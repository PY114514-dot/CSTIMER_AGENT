"""
智能魔方设备抽象层 + Simulator 适配器 (v1)

设计:
  - CubeAdapter: 抽象, 所有适配器 (simulator / webbluetooth / serial) 都实现这套
  - CubeDeviceService: 单用户单设备, 跑一个状态机 (idle/scrambling/inspecting/solving/solved)
  - 事件通过 app.api.ws.ws_manager 广播到前端 (move 事件 + state 变化)

v1: SimulatorAdapter
  - 用户在前端点 "打乱" / "开始" / "还原" 按钮, 适配器生成对应事件
  - 走 python 自家的 cube_model 真实模拟 (apply_moves_facelet), 复原检测用 is_solved()

v2: WebBluetoothAdapter (留给未来)
  - 通过 ws_proxy 把 cstimer JS 协议包暴露到前端, 前端 Web Bluetooth 直连
  - 后端只接受 WS 事件流
"""
from __future__ import annotations
import abc
import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

from app.domain.cube_model import (
    apply_moves_facelet, is_solved,
    generate_random_scramble, parse_moves, SOLVED_FACELET,
)
# SOLVED_FACELET is a str of 54 chars (6 faces x 9 stickers)
SOLVED_FACELET_STR = SOLVED_FACELET if isinstance(SOLVED_FACELET, str) else ''.join(SOLVED_FACELET)

logger = logging.getLogger("cstimer-coach.cube_device")


# ── 事件类型 ────────────────────────────────────────
@dataclass
class MoveEvent:
    move: str               # e.g. "R", "U'", "F2"
    timestamp_ms: int       # relative to session start
    absolute_ms: int
    stage_label: Optional[str] = None  # 由 stage detector 后填

@dataclass
class StateEvent:
    state: str              # idle / scrambling / inspecting / solving / solved
    timestamp_ms: int

@dataclass
class BatteryEvent:
    pct: int
    timestamp_ms: int

CubeEvent = MoveEvent | StateEvent | BatteryEvent


# ── 抽象适配器 ──────────────────────────────────────
class CubeAdapter(abc.ABC):
    """每个用户/会话持有一个 Adapter 实例"""

    def __init__(self, device_id: int, user_id: int):
        self.device_id = device_id
        self.user_id = user_id
        self.state = "idle"  # idle / scrambling / inspecting / solving / solved
        self.battery_pct: Optional[int] = None
        # facelet: 54 字符 (6 face x 9 sticker)
        self.facelet: str = SOLVED_FACELET_STR
        # 当前累计 move 列表 (按发生顺序)
        self.moves: list[MoveEvent] = []
        # 事件回调 (注册时给一个, 走 ws_manager)
        self.on_event: Optional[Callable[[CubeEvent], Awaitable[None]]] = None
        # 倒计时 (ms) - 用于 inspect 阶段超时自动转 solving
        self.inspect_deadline_ms: Optional[int] = None
        # 适配器内部 task
        self._task: Optional[asyncio.Task] = None

    @abc.abstractmethod
    async def connect(self) -> None: ...
    @abc.abstractmethod
    async def disconnect(self) -> None: ...
    @abc.abstractmethod
    async def start_scramble(self) -> list[str]: ...   # 返回 scramble 字符串列表
    @abc.abstractmethod
    async def start_inspection(self, duration_ms: int = 15_000) -> None: ...
    @abc.abstractmethod
    async def start_timing(self) -> None: ...
    @abc.abstractmethod
    async def stop_timing(self) -> None: ...
    @abc.abstractmethod
    async def reset(self) -> None: ...

    async def emit(self, ev: CubeEvent) -> None:
        if self.on_event:
            try:
                await self.on_event(ev)
            except Exception as e:
                logger.warning(f"emit error: {e}")


# ── Simulator Adapter (v1) ──────────────────────────
class SimulatorAdapter(CubeAdapter):
    """
    软件模拟 - 不连真硬件
    - 打乱: 真用 generate_random_scramble + apply_moves_facelet
    - 观察: 倒计时, 结束自动转 solving
    - 计时: 收到 stop_timing 立即停, 推一个 state=solved
    - 用户也可以手动 apply 一个 move (前端 3D 旋转按钮) -> 转成 MoveEvent 推
    """

    def __init__(self, device_id: int, user_id: int, *, seed: Optional[int] = None):
        super().__init__(device_id, user_id)
        self.rng = random.Random(seed)
        self.session_start_ms: int = 0       # 计时起点
        self.current_scramble: str = ""
        self._inspect_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        self.state = "idle"
        self.battery_pct = 100  # 假装满电
        await self.emit(BatteryEvent(pct=100, timestamp_ms=int(time.time()*1000)))
        await self.emit(StateEvent(state="idle", timestamp_ms=int(time.time()*1000)))

    async def disconnect(self) -> None:
        if self._inspect_task:
            self._inspect_task.cancel()
            self._inspect_task = None
        self.state = "idle"
        await self.emit(StateEvent(state="idle", timestamp_ms=int(time.time()*1000)))

    async def start_scramble(self) -> list[str]:
        """生成真随机 scramble, 应用到 facelet, 推一个 state=scrambling + state=idle"""
        await self.emit(StateEvent(state="scrambling", timestamp_ms=int(time.time()*1000)))
        self.facelet = SOLVED_FACELET_STR
        self.moves = []
        self.session_start_ms = 0
        self.current_scramble = generate_random_scramble(seed=self.rng.randint(0, 1<<31))
        # 应用到内部 facelet (一次性传整 list)
        from app.domain.cube_model import parse_moves
        self.facelet = apply_moves_facelet(self.facelet, parse_moves(self.current_scramble))
        self.state = "idle"
        await self.emit(StateEvent(state="idle", timestamp_ms=int(time.time()*1000)))
        return self.current_scramble.split()

    async def start_inspection(self, duration_ms: int = 15_000) -> None:
        """观察阶段: 倒计时 duration_ms, 期间用户可自由看魔方 (但前端的 3D 是用户控制)"""
        if self.state != "idle":
            logger.warning(f"start_inspection from {self.state}, ignored")
            return
        self.state = "inspecting"
        deadline = int(time.time()*1000) + duration_ms
        self.inspect_deadline_ms = deadline
        await self.emit(StateEvent(state="inspecting", timestamp_ms=int(time.time()*1000)))

        async def _countdown():
            try:
                while True:
                    now = int(time.time() * 1000)
                    remaining = max(0, deadline - now)
                    if remaining <= 0:
                        # 默认超时 -> 自动开始计时 (按 WCA 规则, 15s 后没动手 = DNF)
                        # 这里我们用 8s 友好超时
                        if self.state == "inspecting":
                            await self.start_timing()
                        return
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                return
        self._inspect_task = asyncio.create_task(_countdown())

    async def start_timing(self) -> None:
        """开始计时 (真正的 solve 起点)"""
        if self._inspect_task:
            self._inspect_task.cancel()
            self._inspect_task = None
        if self.state not in ("inspecting", "idle"):
            return
        self.state = "solving"
        self.session_start_ms = int(time.time() * 1000)
        self.moves = []
        # facelet 在打乱后保持
        await self.emit(StateEvent(state="solving", timestamp_ms=self.session_start_ms))

    async def stop_timing(self) -> None:
        """结束计时: 检测是否复原, 推 state=solved / state=incomplete"""
        if self.state != "solving":
            return
        solved = is_solved(self.facelet)
        if solved:
            self.state = "solved"
            await self.emit(StateEvent(state="solved", timestamp_ms=int(time.time()*1000)))
        else:
            # 没复原: 标记为未完成但不结束, 让用户继续
            logger.info(f"device {self.device_id} not solved yet, stays in solving")

    async def reset(self) -> None:
        """重置: 回到 idle, 清空 facelet/moves"""
        if self._inspect_task:
            self._inspect_task.cancel()
            self._inspect_task = None
        self.facelet = SOLVED_FACELET_STR
        self.moves = []
        self.state = "idle"
        self.session_start_ms = 0
        self.current_scramble = ""
        await self.emit(StateEvent(state="idle", timestamp_ms=int(time.time()*1000)))

    async def apply_move(self, move: str) -> None:
        """前端 3D 旋转按钮调用, 或 (v2) 真硬件 BLE 推过来的事件"""
        if not self.session_start_ms:
            # 没在计时, 记录到 moves 但不发 event (UI 不应出现这种情况)
            return
        from app.domain.cube_model import parse_move
        try:
            m = parse_move(move)
        except ValueError:
            return
        # 应用到内部 facelet (保证 is_solved 检测正确, 单动包成 list)
        self.facelet = apply_moves_facelet(self.facelet, [m])
        now = int(time.time() * 1000)
        rel = now - self.session_start_ms
        ev = MoveEvent(move=str(m), timestamp_ms=rel, absolute_ms=now)
        self.moves.append(ev)
        await self.emit(ev)
        # 自动检测复原 (避免手动 stop)
        if self.state == "solving" and is_solved(self.facelet):
            self.state = "solved"
            await self.emit(StateEvent(state="solved", timestamp_ms=now))


# ── 设备会话管理 (单进程内, 每用户最多 1 个活动设备) ──
class CubeDeviceService:
    """单例, 管理 user_id -> adapter 映射"""

    def __init__(self):
        self._adapters: dict[tuple[int, int], CubeAdapter] = {}  # (user_id, device_id) -> adapter

    def get_or_create(self, *, user_id: int, device_id: int, brand: str = "manual",
                      adapter_type: str = "simulator") -> CubeAdapter:
        key = (user_id, device_id)
        if key not in self._adapters:
            # v1: 只支持 simulator
            self._adapters[key] = SimulatorAdapter(device_id, user_id)
        return self._adapters[key]

    def drop(self, *, user_id: int, device_id: int) -> None:
        key = (user_id, device_id)
        if key in self._adapters:
            ad = self._adapters.pop(key)
            # 不同步 disconnect (异步), 留给 WSManager 释放
            logger.info(f"dropped adapter {key}")


# 全局单例
cube_device_service = CubeDeviceService()
