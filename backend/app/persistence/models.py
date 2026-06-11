"""
SQLAlchemy ORM 模型 - 完全对应 docs/02-database-schema.md

设计原则:
- 时间统一存毫秒整数 (BIGINT) UTC
- 主键 BigInteger 自增
- JSON 字段在 SQLite 存 TEXT, 后续切 PG 时可改 JSONB
- move_events.stage_label / pause_events.stage_label 在写入时为 NULL,
  由 CFOPStageDetector 后处理回填
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    BigInteger, Boolean, Integer, String, Text, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.persistence.db import Base


def now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


# 主键: BigInteger 在 PG 上是 BIGSERIAL, 在 SQLite 上必须用 Integer 才会自动 AUTOINCREMENT
PKType = BigInteger().with_variant(Integer(), "sqlite")


# ─────────────────────────────────────────────────────────────
# User
# ─────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id:            Mapped[int]      = mapped_column(PKType, primary_key=True)
    username:      Mapped[str]      = mapped_column(String(64), nullable=False, unique=True)
    display_name:  Mapped[Optional[str]] = mapped_column(String(128))
    timezone:      Mapped[str]      = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    avg_level:     Mapped[Optional[str]] = mapped_column(String(32))
    created_at:    Mapped[int]      = mapped_column(BigInteger, nullable=False, default=now_ms)
    settings_json: Mapped[str]      = mapped_column(Text, nullable=False, default="{}")


# ─────────────────────────────────────────────────────────────
# Session (训练 Session, 默认 12 次一包)
# ─────────────────────────────────────────────────────────────
class TrainingSession(Base):
    __tablename__ = "sessions"

    id:           Mapped[int]   = mapped_column(PKType, primary_key=True)
    user_id:      Mapped[int]   = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name:         Mapped[Optional[str]] = mapped_column(String(128))
    target_size:  Mapped[int]   = mapped_column(Integer, nullable=False, default=12)
    is_auto:      Mapped[bool]  = mapped_column(Boolean, nullable=False, default=True)
    started_at:   Mapped[int]   = mapped_column(BigInteger, nullable=False)
    ended_at:     Mapped[Optional[int]] = mapped_column(BigInteger)
    cube_count:   Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    status:       Mapped[str]   = mapped_column(String(16), nullable=False, default="open")  # open/closed/archived

    cubes: Mapped[list["Cube"]] = relationship(back_populates="session")

    __table_args__ = (Index("idx_sessions_user_time", "user_id", "started_at"),)


# ─────────────────────────────────────────────────────────────
# Cube (单次复原汇总, 事实表)
# ─────────────────────────────────────────────────────────────
class Cube(Base):
    __tablename__ = "cubes"

    id:            Mapped[int]   = mapped_column(PKType, primary_key=True)
    user_id:       Mapped[int]   = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id:    Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    puzzle_type:   Mapped[str]   = mapped_column(String(8), nullable=False, default="333")
    scramble:      Mapped[str]   = mapped_column(Text, nullable=False)
    started_at:    Mapped[int]   = mapped_column(BigInteger, nullable=False)
    ended_at:      Mapped[int]   = mapped_column(BigInteger, nullable=False)
    total_time_ms: Mapped[int]   = mapped_column(Integer, nullable=False)
    penalty_ms:    Mapped[int]   = mapped_column(Integer, nullable=False, default=0)  # 0 / 2000 / -1(DNF)
    move_count:    Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    is_dnf:        Mapped[bool]  = mapped_column(Boolean, nullable=False, default=False)
    notes:         Mapped[Optional[str]] = mapped_column(Text)
    source:        Mapped[str]   = mapped_column(String(32), nullable=False, default="manual")
    created_at:    Mapped[int]   = mapped_column(BigInteger, nullable=False, default=now_ms)

    session: Mapped[Optional[TrainingSession]] = relationship(back_populates="cubes")
    moves:   Mapped[list["MoveEvent"]] = relationship(back_populates="cube", cascade="all, delete-orphan")
    stages:  Mapped[Optional["SolveStages"]] = relationship(back_populates="cube", uselist=False, cascade="all, delete-orphan")
    pauses:  Mapped[list["PauseEvent"]] = relationship(back_populates="cube", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_cubes_user_started", "user_id", "started_at"),
        Index("idx_cubes_session", "session_id"),
    )


# ─────────────────────────────────────────────────────────────
# MoveEvent (每次转动一行)
# ─────────────────────────────────────────────────────────────
class MoveEvent(Base):
    __tablename__ = "move_events"

    id:           Mapped[int]   = mapped_column(PKType, primary_key=True)
    solve_id:     Mapped[int]   = mapped_column(ForeignKey("cubes.id", ondelete="CASCADE"), nullable=False)
    seq:          Mapped[int]   = mapped_column(Integer, nullable=False)
    move_text:    Mapped[str]   = mapped_column(String(16), nullable=False)
    is_smart_turn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timestamp_ms: Mapped[int]   = mapped_column(BigInteger, nullable=False)  # relative to started_at
    absolute_ms:  Mapped[int]   = mapped_column(BigInteger, nullable=False)
    stage_label:  Mapped[Optional[str]] = mapped_column(String(8))  # cross/f2l/oll/pll, NULL until backfilled

    cube: Mapped["Cube"] = relationship(back_populates="moves")

    __table_args__ = (
        UniqueConstraint("solve_id", "seq", name="uq_moves_solve_seq"),
        Index("idx_moves_solve", "solve_id"),
    )


# ─────────────────────────────────────────────────────────────
# SolveStages (每 solve 一行, 4 个阶段耗时)
# ─────────────────────────────────────────────────────────────
class SolveStages(Base):
    __tablename__ = "solve_stages"

    id:             Mapped[int]  = mapped_column(PKType, primary_key=True)
    solve_id:       Mapped[int]  = mapped_column(ForeignKey("cubes.id", ondelete="CASCADE"), unique=True, nullable=False)
    cross_dur_ms:   Mapped[Optional[int]] = mapped_column(Integer)
    f2l_dur_ms:     Mapped[Optional[int]] = mapped_column(Integer)
    oll_dur_ms:     Mapped[Optional[int]] = mapped_column(Integer)
    pll_dur_ms:     Mapped[Optional[int]] = mapped_column(Integer)
    f2l_pairs:      Mapped[Optional[int]] = mapped_column(Integer)
    detected_method: Mapped[Optional[str]] = mapped_column(String(16), default="cfop")
    confidence:     Mapped[Optional[float]] = mapped_column()

    cube: Mapped["Cube"] = relationship(back_populates="stages")


# ─────────────────────────────────────────────────────────────
# PauseEvent (停顿)
# ─────────────────────────────────────────────────────────────
class PauseEvent(Base):
    __tablename__ = "pause_events"

    id:             Mapped[int]  = mapped_column(PKType, primary_key=True)
    solve_id:       Mapped[int]  = mapped_column(ForeignKey("cubes.id", ondelete="CASCADE"), nullable=False)
    seq:            Mapped[int]  = mapped_column(Integer, nullable=False)
    start_ms:       Mapped[int]  = mapped_column(BigInteger, nullable=False)
    end_ms:         Mapped[int]  = mapped_column(BigInteger, nullable=False)
    duration_ms:    Mapped[int]  = mapped_column(Integer, nullable=False)
    before_move_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    after_move_seq: Mapped[int]  = mapped_column(Integer, nullable=False)
    stage_label:    Mapped[Optional[str]] = mapped_column(String(8))
    type:           Mapped[str]  = mapped_column(String(16), nullable=False, default="observe")

    cube: Mapped["Cube"] = relationship(back_populates="pauses")

    __table_args__ = (Index("idx_pause_stage", "stage_label"),)


# ─────────────────────────────────────────────────────────────
# SessionStats
# ─────────────────────────────────────────────────────────────
class SessionStats(Base):
    __tablename__ = "session_stats"

    id:              Mapped[int] = mapped_column(PKType, primary_key=True)
    session_id:      Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, nullable=False)
    avg_total_ms:    Mapped[Optional[int]] = mapped_column(Integer)
    best_ms:         Mapped[Optional[int]] = mapped_column(Integer)
    worst_ms:        Mapped[Optional[int]] = mapped_column(Integer)
    std_dev_ms:      Mapped[Optional[int]] = mapped_column(Integer)
    avg3_ms:         Mapped[Optional[int]] = mapped_column(Integer)
    avg5_ms:         Mapped[Optional[int]] = mapped_column(Integer)
    avg12_ms:        Mapped[Optional[int]] = mapped_column(Integer)
    avg_cross_ms:    Mapped[Optional[int]] = mapped_column(Integer)
    avg_f2l_ms:      Mapped[Optional[int]] = mapped_column(Integer)
    avg_oll_ms:      Mapped[Optional[int]] = mapped_column(Integer)
    avg_pll_ms:      Mapped[Optional[int]] = mapped_column(Integer)
    avg_moves:       Mapped[Optional[float]] = mapped_column()
    avg_pause_ms:    Mapped[Optional[int]] = mapped_column(Integer)
    pause_count:     Mapped[Optional[int]] = mapped_column(Integer)
    pause_stage_dist: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    speed_trend:     Mapped[Optional[float]] = mapped_column()
    last_analyzed_at: Mapped[Optional[int]] = mapped_column(BigInteger)


# ─────────────────────────────────────────────────────────────
# AIReport
# ─────────────────────────────────────────────────────────────
class AIReport(Base):
    __tablename__ = "ai_reports"

    id:             Mapped[int] = mapped_column(PKType, primary_key=True)
    session_id:     Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    user_id:        Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    model:          Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_prompt:     Mapped[str] = mapped_column(Text, nullable=False)
    raw_response:   Mapped[str] = mapped_column(Text, nullable=False)
    parsed_json:    Mapped[Optional[str]] = mapped_column(Text)
    bottleneck:     Mapped[Optional[str]] = mapped_column(String(64))
    confidence:     Mapped[Optional[float]] = mapped_column()
    status:         Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # ok/failed
    created_at:     Mapped[int] = mapped_column(BigInteger, nullable=False, default=now_ms)


# ─────────────────────────────────────────────────────────────
# TrainingTask
# ─────────────────────────────────────────────────────────────
class TrainingTask(Base):
    __tablename__ = "training_tasks"

    id:             Mapped[int] = mapped_column(PKType, primary_key=True)
    user_id:        Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id:     Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    ai_report_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("ai_reports.id", ondelete="SET NULL"))
    daily_goal_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("daily_goals.id", ondelete="SET NULL"))
    rule_id:        Mapped[Optional[str]] = mapped_column(String(32))
    category:       Mapped[str] = mapped_column(String(32), nullable=False)
    title:          Mapped[str] = mapped_column(String(128), nullable=False)
    description:    Mapped[Optional[str]] = mapped_column(Text)
    config_json:    Mapped[Optional[str]] = mapped_column(Text)
    target_metric:  Mapped[Optional[str]] = mapped_column(String(64))
    duration_min:   Mapped[Optional[int]] = mapped_column(Integer)
    status:         Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    scheduled_for:  Mapped[Optional[int]] = mapped_column(BigInteger)
    completed_at:   Mapped[Optional[int]] = mapped_column(BigInteger)
    result_json:    Mapped[Optional[str]] = mapped_column(Text)
    created_at:     Mapped[int] = mapped_column(BigInteger, nullable=False, default=now_ms)


# ─────────────────────────────────────────────────────────────
# DailyGoal
# ─────────────────────────────────────────────────────────────
class DailyGoal(Base):
    __tablename__ = "daily_goals"

    id:              Mapped[int] = mapped_column(PKType, primary_key=True)
    user_id:         Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    goal_date:       Mapped[int] = mapped_column(BigInteger, nullable=False)  # 当日 0 点 UTC ms
    target_kind:     Mapped[str] = mapped_column(String(16), nullable=False, default="count")
    target_value:    Mapped[int] = mapped_column(Integer, nullable=False)
    completed_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_achieved:     Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recommended:     Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note:            Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("user_id", "goal_date", name="uq_daily_user_date"),)


# ─────────────────────────────────────────────────────────────
# CubeDevice (智能魔方配对, 未来扩展)
# ─────────────────────────────────────────────────────────────
class CubeDevice(Base):
    __tablename__ = "cube_devices"

    id:           Mapped[int] = mapped_column(PKType, primary_key=True)
    user_id:      Mapped[int]   = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # 品牌: gan / moyu / qiyi / gocube / giiker / manual (无硬件)
    brand:        Mapped[Optional[str]]   = mapped_column(String(32))
    # 具体型号 (e.g. "GAN 356 i3", "MoYu RS3M 2020", 手动填则为空)
    model:        Mapped[Optional[str]]   = mapped_column(String(64))
    # BLE MAC 地址 (大写冒号分隔, e.g. "AA:BB:CC:DD:EE:FF"); 手动填则可空
    mac_address:  Mapped[Optional[str]]   = mapped_column(String(32), index=True)
    # 用户自定义昵称
    nickname:     Mapped[Optional[str]]   = mapped_column(String(64))
    # 协议版本: gan_v1 / gan_v2 / gan_v3 / gan_v4 / moyu / qiyi / manual
    protocol:     Mapped[str]   = mapped_column(String(16), nullable=False, default="manual")
    # 适配器类型: simulator (本期) / webbluetooth (v2)
    adapter:      Mapped[str]   = mapped_column(String(16), nullable=False, default="simulator")
    # 电池电量 0-100, None=未知
    battery_pct:  Mapped[Optional[int]]   = mapped_column(Integer)
    # 当前硬件状态: idle / scrambling / inspecting / solving / solved
    state:        Mapped[str]   = mapped_column(String(16), nullable=False, default="idle")
    # 最后一次硬件事件时间 (毫秒)
    last_event_at: Mapped[Optional[int]]   = mapped_column(BigInteger)
    paired_at:    Mapped[Optional[int]]   = mapped_column(BigInteger)
    last_sync_at: Mapped[Optional[int]]   = mapped_column(BigInteger)


# ─────────────────────────────────────────────────────────────
# FormulaSet  (一份 case 集合, 如 PLL / OLL / F2L)
# ─────────────────────────────────────────────────────────────
class FormulaSet(Base):
    __tablename__ = "formula_sets"

    id:           Mapped[int]   = mapped_column(PKType, primary_key=True)
    code:         Mapped[str]   = mapped_column(String(32), nullable=False, unique=True)
    puzzle:       Mapped[str]   = mapped_column(String(16), nullable=False, default="3x3")
    display_name: Mapped[str]   = mapped_column(String(64), nullable=False)
    case_count:   Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    source:       Mapped[str]   = mapped_column(String(32), nullable=False, default="cubingapp/algdb")
    fetched_at:   Mapped[int]   = mapped_column(BigInteger, nullable=False, default=now_ms)

    cases: Mapped[list["FormulaCase"]] = relationship(
        back_populates="fset", cascade="all, delete-orphan", order_by="FormulaCase.position_in_set"
    )


# ─────────────────────────────────────────────────────────────
# FormulaCase  (一个 case, 如 "Aa perm" / "OLL 21")
# ─────────────────────────────────────────────────────────────
class FormulaCase(Base):
    __tablename__ = "formula_cases"

    id:              Mapped[int]   = mapped_column(PKType, primary_key=True)
    set_id:          Mapped[int]   = mapped_column(
        ForeignKey("formula_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name:            Mapped[str]   = mapped_column(String(64), nullable=False)
    code:            Mapped[str]   = mapped_column(String(32), nullable=False)  # 归一化: Aa / OLL-21
    recognition:     Mapped[Optional[str]] = mapped_column(String(256))
    mirror_of:       Mapped[Optional[str]] = mapped_column(String(32))
    position_in_set: Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    is_symmetric:    Mapped[bool]  = mapped_column(Boolean, nullable=False, default=False)
    source:          Mapped[str]   = mapped_column(String(32), nullable=False, default="cubingapp/algdb")

    fset: Mapped["FormulaSet"] = relationship(back_populates="cases")
    algs: Mapped[list["FormulaAlg"]] = relationship(
        back_populates="fcase", cascade="all, delete-orphan", order_by="FormulaAlg.seq"
    )

    __table_args__ = (UniqueConstraint("set_id", "code", name="uq_case_set_code"),)


# ─────────────────────────────────────────────────────────────
# FormulaAlg  (case 下的一个算法变体, seq=0 为首选)
# ─────────────────────────────────────────────────────────────
class FormulaAlg(Base):
    __tablename__ = "formula_algs"

    id:           Mapped[int]   = mapped_column(PKType, primary_key=True)
    case_id:      Mapped[int]   = mapped_column(
        ForeignKey("formula_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq:          Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    alg_text:     Mapped[str]   = mapped_column(Text, nullable=False)
    fingertricks: Mapped[Optional[str]] = mapped_column(String(64))    # 'RUSH' / 'LUSH' / 'standard' / 'm2-only' / '?'
    move_count:   Mapped[Optional[int]] = mapped_column(Integer)
    is_canonical: Mapped[bool]  = mapped_column(Boolean, nullable=False, default=True)
    notes:        Mapped[Optional[str]] = mapped_column(Text)

    fcase: Mapped["FormulaCase"] = relationship(back_populates="algs")

    __table_args__ = (UniqueConstraint("case_id", "seq", name="uq_alg_case_seq"),)


__all__ = [
    "User", "TrainingSession", "Cube", "MoveEvent", "SolveStages",
    "PauseEvent", "SessionStats", "AIReport", "TrainingTask",
    "DailyGoal", "CubeDevice",
    "FormulaSet", "FormulaCase", "FormulaAlg",
    "now_ms",
]
