"""
FastAPI Pydantic v2 Schemas (request/response 契约)
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ── Health ─────────────────────────────────────────────
class HealthResp(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    db: str


# ── User ───────────────────────────────────────────────
class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    display_name: Optional[str] = None
    timezone: str = "Asia/Shanghai"
    avg_level: Optional[str] = None


class UserResp(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: Optional[str]
    timezone: str
    avg_level: Optional[str]
    created_at: int


# ── Solve (单次复原) ────────────────────────────────────
class SolveStartReq(BaseModel):
    user_id: int
    session_id: Optional[int] = None          # 不传则用当前 open session
    scramble: Optional[str] = None            # 不传则随机生成
    puzzle_type: str = "333"


class MoveReq(BaseModel):
    move: str                                  # "R", "U'", "F2" ...
    timestamp_ms: Optional[int] = None         # 相对 started_at; 不传则用 now
    is_smart_turn: bool = False


class SolveResp(BaseModel):
    cube_id: int
    session_id: Optional[int]
    scramble: str
    started_at: int


class MoveAck(BaseModel):
    seq: int
    move: str
    timestamp_ms: int


class SolveFinishResp(BaseModel):
    cube_id: int
    session_id: Optional[int]
    total_time_ms: int
    move_count: int
    stage_confidence: float
    pause_count: int


# ── Session ────────────────────────────────────────────
class SessionCreateReq(BaseModel):
    user_id: int
    target_size: int = 12
    name: Optional[str] = None


class SessionResp(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: Optional[str]
    target_size: int
    is_auto: bool
    started_at: int
    ended_at: Optional[int]
    cube_count: int
    status: str


# ── Stages / Pauses ─────────────────────────────────────
class SolveStagesResp(BaseModel):
    cross_dur_ms: Optional[int]
    f2l_dur_ms:   Optional[int]
    oll_dur_ms:   Optional[int]
    pll_dur_ms:   Optional[int]
    f2l_pairs:    Optional[int]
    detected_method: Optional[str]
    confidence:   Optional[float]


class PauseResp(BaseModel):
    seq: int
    start_ms: int
    end_ms: int
    duration_ms: int
    before_move_seq: int
    after_move_seq: int
    stage_label: Optional[str]
    type: str


class MoveResp(BaseModel):
    seq: int
    move_text: str
    timestamp_ms: int
    stage_label: Optional[str]


# ── Session Stats ───────────────────────────────────────
class SessionStatsResp(BaseModel):
    session_id: int
    solve_count: int
    dnf_count: int
    avg_total_ms: Optional[int]
    best_ms: Optional[int]
    worst_ms: Optional[int]
    std_dev_ms: Optional[int]
    avg3_ms: Optional[int]
    avg5_ms: Optional[int]
    avg12_ms: Optional[int]
    avg_cross_ms: Optional[int]
    avg_f2l_ms:   Optional[int]
    avg_oll_ms:   Optional[int]
    avg_pll_ms:   Optional[int]
    avg_moves:    Optional[float]
    avg_pause_ms: Optional[int]
    pause_count:  Optional[int]
    pause_stage_dist: dict[str, float]
    pause_type_dist:  dict[str, float]
    speed_trend:  Optional[float]
    first_half_ms:  Optional[int]
    second_half_ms: Optional[int]
    longest_pause_ms: Optional[int]
    longest_pause_stage: Optional[str]


# ── Cube (in session detail) ────────────────────────────
class CubeResp(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    session_id: Optional[int]
    puzzle_type: str
    scramble: str
    started_at: int
    ended_at: int
    total_time_ms: int
    penalty_ms: int
    move_count: int
    is_dnf: bool
    notes: Optional[str]
    source: str
    created_at: int


class SessionDetailResp(BaseModel):
    session: SessionResp
    stats: Optional[SessionStatsResp]
    cubes: list[CubeResp]
    ai_report: Optional["AIReportResp"] = None
    training_tasks: list["TrainingTaskResp"] = []


# ── AI Report ───────────────────────────────────────────
class AIReportResp(BaseModel):
    id: int
    session_id: int
    user_id: int
    model: str
    prompt_version: str
    bottleneck: Optional[str]
    confidence: Optional[float]
    parsed: dict
    created_at: int


# ── Training ────────────────────────────────────────────
class TrainingTaskResp(BaseModel):
    id: int
    rule_id: Optional[str]
    category: str
    title: str
    description: Optional[str]
    target_metric: Optional[str]
    duration_min: Optional[int]
    status: str
    scheduled_for: Optional[int]
    completed_at: Optional[int]
    config: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)


class TrainingTaskDoneReq(BaseModel):
    result: dict = Field(default_factory=dict)     # {"self_rating": 4, "felt": "good"}


# ── Dashboard ───────────────────────────────────────────
class DailyGoalResp(BaseModel):
    id: int
    goal_date: int
    target_kind: str
    target_value: int
    completed_value: int
    is_achieved: bool
    recommended: bool
    achievement_ratio: float


class TodayDashboardResp(BaseModel):
    date: str
    daily_goal: Optional[DailyGoalResp]
    current_session: Optional[SessionResp]
    latest_ai_report: Optional[AIReportResp]
    training_tasks: list[TrainingTaskResp]
    stage_breakdown: list[dict]
    pause_heatmap: list[dict]
    trend_30: list[dict]


# ── Import ──────────────────────────────────────────────
class ImportResp(BaseModel):
    sessions_imported: int
    cubes_imported: int
    session_ids: list[int]


# Resolve forward refs
SessionDetailResp.model_rebuild()


# ── Formula Library ─────────────────────────────────────────
class FormulaAlgResp(BaseModel):
    id: int
    seq: int
    alg_text: str
    fingertricks: Optional[str] = None
    move_count: Optional[int] = None
    is_canonical: bool = True
    notes: Optional[str] = None


class FormulaCaseResp(BaseModel):
    id: int
    name: str
    code: str
    recognition: Optional[str] = None
    mirror_of: Optional[str] = None
    position_in_set: int
    is_symmetric: bool = False
    algs: list[FormulaAlgResp] = Field(default_factory=list)


class FormulaSetSummary(BaseModel):
    id: int
    code: str
    puzzle: str
    display_name: str
    case_count: int
    source: str
    fetched_at: int


class FormulaSetDetail(FormulaSetSummary):
    cases: list[FormulaCaseResp] = Field(default_factory=list)
