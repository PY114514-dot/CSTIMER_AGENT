"""
AGENT 单元测试
- TOOL_NAMES 包含 4 个
- lookup_formulas (mock 数据库) 命中
- mark_task_done 修改状态
- generate_training 写入 tasks
- Agent 类用 mock LLM 模拟单轮 + 多轮 tool-use
"""
import os
import json
import pytest
from sqlalchemy import create_engine

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LLM_API_KEY", "sk-test-placeholder")

import app.persistence.db as db_mod
from app.persistence.db import Base
from app.persistence import models  # noqa
from app.persistence import repositories as repo
from app.persistence.formula_importer import import_one_set
from app.llm.agent import Agent, TOOL_NAMES, TOOL_REGISTRY
from app.llm.client import LLMClient


# ── Tool registry 完整性 ─────────────────────────────
def test_tool_registry_has_four_tools():
    assert set(TOOL_NAMES) == {"query_user_stats", "lookup_formulas", "generate_training", "mark_task_done"}
    for name in TOOL_NAMES:
        assert callable(TOOL_REGISTRY[name])


# ── 工具调用 (真 DB) ─────────────────────────────────
@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    db_path = tmp_path / f"agent_test_{os.getpid()}_{id(object())}.db"
    eng = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    db_mod.engine = eng
    db_mod.SessionLocal.configure(bind=eng)
    yield
    eng.dispose()


def test_lookup_formulas_returns_cases():
    """先 seed 一份 mini PLL, 再查"""
    import tempfile
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "PLL.json"), "w", encoding="utf-8") as f:
        json.dump({"puzzle": "3x3", "cases": [
            {"name": "Aa perm", "algs": ["R U R' U'"]},
            {"name": "T perm",  "algs": ["R U R' U' R' F R2 U' R' F'"]},
        ]}, f, ensure_ascii=False)
    with db_mod.SessionLocal() as s:
        import_one_set(s, filename="PLL.json", set_code="PLL", display_name="PLL", cache_dir=tmp)
        s.commit()

    r = TOOL_REGISTRY["lookup_formulas"]({"set": "PLL", "q": "Aa"})
    assert r["set_code"] == "PLL"
    assert r["case_count"] == 1
    assert r["cases"][0]["code"] == "Aa"
    assert r["cases"][0]["first_alg"].startswith("R U")

    # q 留空 -> 全部
    r2 = TOOL_REGISTRY["lookup_formulas"]({"set": "PLL"})
    assert r2["case_count"] == 2

    # 错 set
    r3 = TOOL_REGISTRY["lookup_formulas"]({"set": "NOPE"})
    assert "error" in r3


def test_mark_task_done_updates_status():
    with db_mod.SessionLocal() as s:
        u = repo.get_or_create_user(s, "agent_tester"); s.commit()
        uid = u.id
        ids = repo.add_training_tasks(s, [{
            "user_id": uid, "category": "f2l", "title": "t1",
            "target_metric": "f2l_obs", "duration_min": 10, "status": "pending",
        }])
        s.commit()
        tid = ids[0]

    r = TOOL_REGISTRY["mark_task_done"]({"task_id": tid, "result": {"felt": "good"}})
    assert r["status"] == "done"

    with db_mod.SessionLocal() as s:
        t = s.get(models.TrainingTask, tid)
        assert t.status == "done"
        assert "good" in t.result_json


def test_generate_training_writes_tasks():
    from app.domain.session_aggregator import SessionSummary
    with db_mod.SessionLocal() as s:
        u = repo.get_or_create_user(s, "agent_tester2"); s.commit()
        uid = u.id
        sess = repo.create_session(s, user_id=uid, target_size=12); s.commit()
        sid = sess.id

    summary = SessionSummary(
        session_id=sid, solve_count=12, dnf_count=0,
        avg_total_ms=15000, best_ms=12000, worst_ms=18000, std_dev_ms=1500,
        avg3_ms=13500, avg5_ms=14000, avg12_ms=14500,
        avg_cross_ms=2000, avg_f2l_ms=8000, avg_oll_ms=2500, avg_pll_ms=2500,
        avg_moves=58.0, avg_pause_ms=4000, pause_count=40,
        pause_stage_dist={"f2l": 0.7, "oll": 0.2, "pll": 0.1},
        pause_type_dist={"observe": 0.3, "think": 0.5, "lockup": 0.2},
        speed_trend=1.05, first_half_ms=14000, second_half_ms=15000,
        longest_pause_ms=2500, longest_pause_stage="f2l",
    )
    # 真实调用: 走 generate
    from app.domain.training_engine import TrainingRuleEngine
    with db_mod.SessionLocal() as s:
        tasks = TrainingRuleEngine().generate(sid, summary, user_id=uid)
    assert len(tasks) >= 1


# ── Agent 主循环 (mock LLM) ──────────────────────────
class MockLLM:
    """按调用顺序返回预设 decisions"""
    def __init__(self, decisions: list[dict]):
        self.decisions = list(decisions)
        self.calls = 0

    def complete(self, messages, **kwargs) -> str:
        if not self.decisions:
            raise RuntimeError("mock LLM out of decisions")
        d = self.decisions.pop(0)
        self.calls += 1
        return json.dumps(d)


def test_agent_immediate_answer():
    mock = MockLLM([{"action": "answer", "text": "你最近是 PLL 慢"}])
    a = Agent(llm=mock)  # type: ignore
    r = a.chat(user_id=1, session_id=None, user_msg="hi")
    assert r["answer"] == "你最近是 PLL 慢"
    assert r["steps"] == 0
    assert mock.calls == 1


def test_agent_one_tool_then_answer():
    # 第一次: tool_call (mock 实现是 echo back), 第二次: answer
    decisions = [
        {"action": "tool_call", "tool": "lookup_formulas", "args": {"set": "PLL"}, "think": "查 PLL"},
        {"action": "answer", "text": "PLL 有 21 个 case"},
    ]
    mock = MockLLM(decisions)
    a = Agent(llm=mock)  # type: ignore
    r = a.chat(user_id=1, session_id=None, user_msg="PLL 有多少 case?")
    assert r["answer"] == "PLL 有 21 个 case"
    assert r["steps"] == 1
    assert mock.calls == 2
    # 验证 transcript 记录了 tool_call + tool_result
    assert r["transcript"][0]["decision"]["tool"] == "lookup_formulas"
    assert "tool_result" in r["transcript"][0]


def test_agent_unknown_tool_falls_through_to_answer():
    decisions = [
        {"action": "tool_call", "tool": "no_such_tool", "args": {}},
        {"action": "answer", "text": "对不起, 暂不支持这个操作"},
    ]
    mock = MockLLM(decisions)
    r = Agent(llm=mock).chat(1, None, "x")  # type: ignore
    assert "不支持" in r["answer"]
    # tool_result 应包含 error
    assert "error" in r["transcript"][0]["tool_result"]


def test_agent_max_steps_caps_loop():
    decisions = [{"action": "tool_call", "tool": "lookup_formulas", "args": {}}] * 5
    mock = MockLLM(decisions)
    r = Agent(llm=mock, max_steps=2).chat(1, None, "x")  # type: ignore
    assert r["steps"] == 3  # 0=tool, 1=tool, 2=tool -> 走到 max_steps+1
    assert "最大步数" in r["answer"]


# ── stream_chat 流式 ──────────────────────────────
def test_stream_chat_yields_step_and_final():
    """验证 generator 按顺序 yield: step -> final"""
    mock = MockLLM([{"action": "answer", "text": "PLL 慢"}])
    a = Agent(llm=mock)  # type: ignore
    events = list(a.stream_chat(1, None, "x"))
    names = [e["event"] for e in events]
    assert "step" in names
    assert "answer" in names
    assert names[-1] == "final"
    final = events[-1]
    assert final["answer"] == "PLL 慢"
    assert final["steps"] == 0


def test_stream_chat_yields_tool_lifecycle():
    """tool_call 时应有 tool_start + tool_result + step"""
    decisions = [
        {"action": "tool_call", "tool": "lookup_formulas", "args": {"set": "PLL"}, "think": "查"},
        {"action": "answer", "text": "done"},
    ]
    mock = MockLLM(decisions)
    a = Agent(llm=mock)  # type: ignore
    events = list(a.stream_chat(1, None, "x"))
    names = [e["event"] for e in events]
    # step, tool_start, tool_result, step, answer, final
    assert names[0] == "step"
    assert "tool_start" in names
    assert "tool_result" in names
    # 测试 fixture 没灌公式库 -> 工具返回 error
    tr = next(e for e in events if e["event"] == "tool_result")
    assert "result" in tr
    # tool_result 应是 dict (error 或正常)
    assert isinstance(tr["result"], dict)


def test_stream_chat_error_when_unknown_tool():
    decisions = [
        {"action": "tool_call", "tool": "no_such_tool", "args": {}},
        {"action": "answer", "text": "不支持"},
    ]
    mock = MockLLM(decisions)
    events = list(Agent(llm=mock).stream_chat(1, None, "x"))  # type: ignore
    tr = next(e for e in events if e["event"] == "tool_result")
    assert "error" in tr["result"]


def test_stream_chat_max_steps_emits_error():
    decisions = [{"action": "tool_call", "tool": "lookup_formulas", "args": {}}] * 5
    mock = MockLLM(decisions)
    events = list(Agent(llm=mock, max_steps=2).stream_chat(1, None, "x"))  # type: ignore
    final = events[-1]
    assert final["event"] == "final"
    assert "最大步数" in final["answer"]
