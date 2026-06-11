"""
测试 Session 聚合器 (用临时 SQLite 内存库)
"""
import os
import os
import time
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.persistence.db as db_mod


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """每个测试用全新临时 SQLite, 走 fresh engine"""
    db_path = tmp_path / f"test_agg_{os.getpid()}_{id(object())}.db"
    from app.persistence.db import Base
    from app.persistence import models  # noqa
    eng = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    TestSession = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)

    # 关键: 修改已导入的 SessionLocal 指向新 engine
    db_mod.SessionLocal.configure(bind=eng)
    db_mod.engine = eng
    _CURRENT_USER_ID[0] = 1
    yield TestSession
    # 还原到原 engine (避免污染下一个测试)
    db_mod.SessionLocal.configure(bind=db_mod._original_engine)


_CURRENT_USER_ID: list[int] = [1]  # 用 list 包装实现 nonlocal


def _create_user():
    from app.persistence import repositories as repo
    with db_mod.SessionLocal() as s:
        u = repo.get_or_create_user(s, "tester", display_name="T")
        s.commit()
        _CURRENT_USER_ID[0] = u.id
        return u.id


def _create_cube(total_ms, move_count, started_at, is_dnf=False, session_id=None):
    from app.persistence import repositories as repo
    with db_mod.SessionLocal() as s:
        c = repo.create_cube(
            s,
            user_id=_CURRENT_USER_ID[0], session_id=session_id,
            puzzle_type="333",
            scramble="R U R' U'",
            started_at=started_at,
            ended_at=started_at + total_ms,
            total_time_ms=total_ms,
            penalty_ms=-1 if is_dnf else 0,
            move_count=move_count,
            is_dnf=is_dnf,
            source="test",
        )
        s.commit()
        return c.id


def _create_session(user_id):
    from app.persistence import repositories as repo
    with db_mod.SessionLocal() as s:
        sess = repo.create_session(s, user_id=user_id, target_size=12)
        s.commit()
        return sess.id


class TestSessionAggregator:
    def test_empty_session(self):
        uid = _create_user()
        sid = _create_session(uid)
        from app.domain.session_aggregator import SessionAggregator
        summary = SessionAggregator().aggregate(sid)
        assert summary.solve_count == 0
        assert summary.avg_total_ms is None

    def test_12_solves(self):
        uid = _create_user()
        sid = _create_session(uid)
        base = int(time.time() * 1000) - 12 * 60_000
        totals = [10000, 11000, 10500, 9800, 10200, 10700, 9900, 10100, 10300, 10000, 9900, 10200]
        for i, t in enumerate(totals):
            _create_cube(t, 60, base + i * 60_000, session_id=sid)
        from app.domain.session_aggregator import SessionAggregator
        summary = SessionAggregator().aggregate(sid)
        assert summary.solve_count == 12
        assert summary.best_ms == 9800
        assert summary.worst_ms == 11000
        assert summary.avg3_ms is not None
        assert summary.avg5_ms is not None
        assert summary.avg12_ms is not None

    def test_dnf_excluded_from_mean(self):
        uid = _create_user()
        sid = _create_session(uid)
        base = int(time.time() * 1000) - 4 * 60_000
        _create_cube(10000, 60, base, session_id=sid)
        _create_cube(12000, 60, base + 60_000, session_id=sid)
        _create_cube(0, 60, base + 120_000, is_dnf=True, session_id=sid)
        _create_cube(11000, 60, base + 180_000, session_id=sid)
        from app.domain.session_aggregator import SessionAggregator
        summary = SessionAggregator().aggregate(sid)
        assert summary.solve_count == 4
        assert summary.dnf_count == 1
        # (10000+12000+11000)/3 = 11000
        assert summary.avg_total_ms == 11000


class TestTrainingEngine:
    def test_f2l_rule_triggers(self):
        from app.domain.session_aggregator import SessionSummary
        from app.domain.training_engine import TrainingRuleEngine
        summary = SessionSummary(
            session_id=1, solve_count=12, dnf_count=0,
            avg_total_ms=15000, best_ms=12000, worst_ms=18000, std_dev_ms=1500,
            avg3_ms=13500, avg5_ms=14000, avg12_ms=14500,
            avg_cross_ms=2000, avg_f2l_ms=8000, avg_oll_ms=2500, avg_pll_ms=2500,
            avg_moves=58.0, avg_pause_ms=4000, pause_count=40,
            pause_stage_dist={"f2l": 0.7, "oll": 0.2, "pll": 0.1},
            pause_type_dist={"observe": 0.3, "think": 0.5, "lockup": 0.2},
            speed_trend=1.05,
            first_half_ms=14000, second_half_ms=15000,
            longest_pause_ms=2500, longest_pause_stage="f2l",
        )
        engine = TrainingRuleEngine()
        tasks = engine.generate(99, summary, user_id=_CURRENT_USER_ID[0])
        rule_ids = {t["rule_id"] for t in tasks}
        assert "R-F2L-001" in rule_ids

    def test_default_when_no_match(self):
        from app.domain.session_aggregator import SessionSummary
        from app.domain.training_engine import TrainingRuleEngine
        summary = SessionSummary(
            session_id=1, solve_count=12, dnf_count=0,
            avg_total_ms=15000, best_ms=12000, worst_ms=18000, std_dev_ms=1500,
            avg3_ms=13500, avg5_ms=14000, avg12_ms=14500,
            avg_cross_ms=2000, avg_f2l_ms=5000, avg_oll_ms=2000, avg_pll_ms=1500,  # PLL 1500 < 2500
            avg_moves=58.0, avg_pause_ms=1000, pause_count=10,
            pause_stage_dist={"cross": 0.3, "f2l": 0.3, "oll": 0.2, "pll": 0.2},
            pause_type_dist={"observe": 1.0},
            speed_trend=1.0,
            first_half_ms=14000, second_half_ms=15000,
            longest_pause_ms=900, longest_pause_stage="cross",
        )
        engine = TrainingRuleEngine()
        tasks = engine.generate(99, summary, user_id=_CURRENT_USER_ID[0])
        # 全部规则都不匹配: F2L 占比 33% < 45%, cross 占比 13% < 15%, speed_trend 1.0 < 1.12
        assert len(tasks) == 1
        assert tasks[0]["rule_id"] == "R-DEFAULT"

    def test_f2l_rule_embeds_real_case_ids(self):
        """F2L 规则触发时, config_json 应包含 f2l_case_ids 真实 ID 列表 (无公式库时为空)"""
        from app.domain.session_aggregator import SessionSummary
        from app.domain.training_engine import TrainingRuleEngine
        summary = SessionSummary(
            session_id=1, solve_count=12, dnf_count=0,
            avg_total_ms=15000, best_ms=12000, worst_ms=18000, std_dev_ms=1500,
            avg3_ms=13500, avg5_ms=14000, avg12_ms=14500,
            avg_cross_ms=2000, avg_f2l_ms=8000, avg_oll_ms=2500, avg_pll_ms=2500,
            avg_moves=58.0, avg_pause_ms=4000, pause_count=40,
            pause_stage_dist={"f2l": 0.7, "oll": 0.2, "pll": 0.1},
            pause_type_dist={"observe": 0.3, "think": 0.5, "lockup": 0.2},
            speed_trend=1.05,
            first_half_ms=14000, second_half_ms=15000,
            longest_pause_ms=2500, longest_pause_stage="f2l",
        )
        engine = TrainingRuleEngine()
        tasks = engine.generate(99, summary, user_id=_CURRENT_USER_ID[0])
        f2l_tasks = [t for t in tasks if t["rule_id"] == "R-F2L-001"]
        assert f2l_tasks, "F2L 规则应触发"
        for t in f2l_tasks:
            cfg = json.loads(t["config_json"]) if isinstance(t["config_json"], str) else t["config_json"]
            # 测试 fixture 不灌公式库 -> case_ids 列表应为空 (但 key 存在)
            assert "f2l_case_ids" in cfg
            assert isinstance(cfg["f2l_case_ids"], list)

    def test_ai_bottleneck_drives_target_set(self):
        """AI 报告 bottleneck=pll_recognition 时, 应额外生成 R-BOTTLENECK-001"""
        from app.domain.session_aggregator import SessionSummary
        from app.domain.training_engine import TrainingRuleEngine
        # 制造一个不会触发其它规则的 summary, 但 AI 报告说 pll
        summary = SessionSummary(
            session_id=1, solve_count=12, dnf_count=0,
            avg_total_ms=12000, best_ms=10000, worst_ms=14000, std_dev_ms=1000,
            avg3_ms=11500, avg5_ms=11800, avg12_ms=12000,
            avg_cross_ms=1500, avg_f2l_ms=5000, avg_oll_ms=2000, avg_pll_ms=2500,
            avg_moves=55.0, avg_pause_ms=300, pause_count=8,
            pause_stage_dist={"cross": 0.3, "f2l": 0.3, "oll": 0.2, "pll": 0.2},
            pause_type_dist={"observe": 1.0},
            speed_trend=1.0,
            first_half_ms=11800, second_half_ms=12200,
            longest_pause_ms=600, longest_pause_stage="f2l",
        )
        ai_report = {"id": 42, "bottlenecks": ["pll_recognition"], "confidence": 0.5}
        engine = TrainingRuleEngine()
        tasks = engine.generate(99, summary, ai_report=ai_report, user_id=_CURRENT_USER_ID[0])
        rule_ids = {t["rule_id"] for t in tasks}
        assert "R-BOTTLENECK-001" in rule_ids
        # 找该 task, 验证 config_json 有 pll_case_ids
        bt = next(t for t in tasks if t["rule_id"] == "R-BOTTLENECK-001")
        cfg = json.loads(bt["config_json"]) if isinstance(bt["config_json"], str) else bt["config_json"]
        assert "pll_case_ids" in cfg
