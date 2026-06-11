"""
AGENT: 接受用户自然语言, 通过 tool-use 协议调用后端能力, 返回对话式回答

设计: 单轮 tool-use 循环 (不用 OpenAI Assistants/Agents SDK)
  1. user -> system_prompt (含 tool schemas) + user_msg -> LLM
  2. LLM 返回 JSON: {"action": "tool_call", "tool": "xxx", "args": {...}} | {"action": "answer", "text": "..."}
  3. 后端执行 tool -> 把 tool 结果作为新 user msg -> LLM 再生成 -> 直到 action=answer

支持的 tool:
  - query_user_stats  (DashboardAPI 等价的快照)
  - lookup_formulas   (按 set/q 查 case)
  - generate_training (跑 TrainingRuleEngine, 写库, 返回 task 列表)
  - mark_task_done    (标完成)
"""
from __future__ import annotations
import json
import logging
import time
from typing import Any, Callable, Awaitable

from sqlalchemy.orm import Session

from app.persistence.db import SessionLocal
from app.llm.client import LLMClient, LLMError
from app.domain.session_aggregator import SessionAggregator
from app.domain.training_engine import TrainingRuleEngine
from app.persistence import repositories as repo
from app.persistence.models import TrainingTask

logger = logging.getLogger("cstimer-coach.agent")

PROMPT_VERSION = "v0.1"

# ── System prompt (中文) ────────────────────────────────
SYSTEM_PROMPT = """你是 CSTIMER 智能魔方训练助手的对话式 AGENT, 负责帮用户理解自己的训练数据, 推荐训练项, 解释瓶颈.

你可以调用 4 个工具. **必须严格用以下 JSON 格式**返回你的下一步:

如果需要调用工具:
{{
  "action": "tool_call",
  "tool": "工具名",
  "args": {{ ... 工具参数 ... }},
  "think": "为什么调用 (1 句)"
}}

如果已掌握足够信息可以回答:
{{
  "action": "answer",
  "text": "给你的最终回答 (中文, 简洁, 含具体数字和行动建议)"
}}

工具列表:
1. query_user_stats(user_id: int)
   返回: 今日 dashboard 摘要, 含 daily_goal, current_session, latest_ai_report, training_tasks

2. lookup_formulas(set: str, q: str = "")
   set: "PLL" / "OLL" / "F2L" / "CMLL" / "OLLCP" / "COLL" / "ZBLL" / "WV"
   q: 模糊关键字, 可空
   返回: 命中的 case 列表, 含 id / code / name / recognition / algs[0].alg_text

3. generate_training(session_id: int)
   跑训练生成, 写库
   返回: 生成的 training_tasks 列表 (含 id, title, config.pll_case_ids 等)

4. mark_task_done(task_id: int, result: object = null)
   把任务标 done
   返回: 更新后的 task 状态

约束:
- 最多连续调用 3 个 tool, 然后必须给 answer
- 回答里提到的 case id / 任务 id / 时间 都要给具体数字
- 如果工具报错 (e.g. 公式库空), 老实告诉用户
- 不要凭空捏造数据
"""

USER_PROMPT_TEMPLATE = """用户问题: {user_msg}

可用上下文:
- user_id: {user_id}
- 当前 session_id: {session_id}

请按 JSON 格式返回下一步.
"""


# ── Tool implementations (sync, 拿 SessionLocal 现场开事务) ──
def _tool_query_user_stats(args: dict) -> dict:
    uid = int(args["user_id"])
    with SessionLocal() as s:
        from app.api.routers.dashboard import get_today
        # 直接复用 dashboard 路由
        return get_today(user_id=uid, db=s).model_dump(mode="json")


def _tool_lookup_formulas(args: dict) -> dict:
    set_code = args.get("set") or ""
    q = args.get("q") or ""
    with SessionLocal() as s:
        fset = repo.get_formula_set_with_cases(s, set_code) if set_code else None
        if not fset:
            return {"error": f"set '{set_code}' not found; available: "
                             f"{[fs.code for fs in repo.list_formula_sets(s)]}"}
        cases = fset.cases
        if q:
            ql = q.lower()
            cases = [c for c in cases if ql in c.name.lower() or ql in c.code.lower()]
        return {
            "set_code": set_code,
            "case_count": len(cases),
            "cases": [
                {
                    "id": c.id, "code": c.code, "name": c.name,
                    "recognition": c.recognition,
                    "first_alg": c.algs[0].alg_text if c.algs else None,
                    "move_count": c.algs[0].move_count if c.algs else None,
                } for c in cases[:30]
            ],
        }


def _tool_generate_training(args: dict) -> dict:
    sid = int(args["session_id"])
    with SessionLocal() as s:
        from app.persistence.models import TrainingSession
        sess = s.get(TrainingSession, sid)
        if not sess:
            return {"error": f"session {sid} not found"}
        uid = sess.user_id
    summary = SessionAggregator().aggregate(sid)
    engine = TrainingRuleEngine()
    tasks = engine.generate(sid, summary, user_id=uid)
    return {"session_id": sid, "task_count": len(tasks), "tasks": tasks}


def _tool_mark_task_done(args: dict) -> dict:
    tid = int(args["task_id"])
    result = args.get("result") or {"felt": "agent_completed"}
    with SessionLocal() as s:
        t = s.get(TrainingTask, tid)
        if not t:
            return {"error": f"task {tid} not found"}
        t.status = "done"
        t.completed_at = int(time.time() * 1000)
        t.result_json = json.dumps(result, ensure_ascii=False)
        s.commit()
        return {"task_id": tid, "status": "done", "result": result}


TOOL_REGISTRY: dict[str, Callable[[dict], dict]] = {
    "query_user_stats":  _tool_query_user_stats,
    "lookup_formulas":   _tool_lookup_formulas,
    "generate_training": _tool_generate_training,
    "mark_task_done":    _tool_mark_task_done,
}

# 供测试/外部使用
TOOL_NAMES: list[str] = list(TOOL_REGISTRY.keys())


# ── AGENT 主循环 ─────────────────────────────────────
class Agent:
    def __init__(self, llm: LLMClient | None = None, max_steps: int = 3):
        self.llm = llm or LLMClient()
        self.max_steps = max_steps

    def chat(self, user_id: int, session_id: int | None, user_msg: str) -> dict:
        """非流式: 同步返回最终 dict"""
        result: dict = {"answer": "", "transcript": [], "steps": 0}
        for ev in self.stream_chat(user_id, session_id, user_msg):
            kind = ev.get("event")
            if kind == "final":
                # final 自带完整 answer/steps/transcript
                return ev
            if kind == "step":
                result["transcript"] = ev.get("transcript", result["transcript"])
                result["steps"] = ev.get("step", result["steps"])
            if kind == "answer":
                result["answer"] = ev.get("text", "")
        return result

    def stream_chat(self, user_id: int, session_id: int | None, user_msg: str):
        """流式 generator, yield SSE-style dict 事件:
          - {"event": "step",     "step": 0, "decision": {...}}
          - {"event": "tool_start", "tool": "...", "args": {...}}
          - {"event": "tool_result", "tool": "...", "result": {...}}
          - {"event": "answer",   "text": "..."}
          - {"event": "error",    "message": "..."}
          - {"event": "final",    "answer": ..., "transcript": [...], "steps": N}
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                user_msg=user_msg, user_id=user_id, session_id=session_id or 0,
            )},
        ]
        transcript: list[dict] = []
        answer = ""
        tool_steps = 0  # 完成的 tool 调用次数
        for step in range(self.max_steps + 1):
            try:
                raw = self.llm.complete(messages, response_format_json=True)
            except LLMError as e:
                yield {"event": "error", "message": f"LLM 错误: {e}"}
                break
            try:
                decision = json.loads(raw)
            except json.JSONDecodeError:
                yield {"event": "error", "message": f"LLM 返回非 JSON: {raw[:200]}"}
                break

            transcript.append({"step": step, "decision": decision})
            yield {"event": "step", "step": step, "decision": decision}

            action = decision.get("action")
            if action == "answer":
                answer = decision.get("text", "")
                yield {"event": "answer", "text": answer}
                break

            if action != "tool_call":
                yield {"event": "error", "message": f"未知 action: {action}"}
                break

            tool = decision.get("tool")
            args = decision.get("args") or {}
            yield {"event": "tool_start", "tool": tool, "args": args}
            impl = TOOL_REGISTRY.get(tool or "")
            if not impl:
                tool_result = {"error": f"unknown tool '{tool}'"}
            else:
                try:
                    tool_result = impl(args)
                except Exception as e:
                    tool_result = {"error": f"{type(e).__name__}: {e}"}

            transcript[-1]["tool_result"] = tool_result
            yield {"event": "tool_result", "tool": tool, "result": tool_result}
            tool_steps += 1

            messages.append({"role": "user", "content": f"工具 {tool} 返回:\n{json.dumps(tool_result, ensure_ascii=False, default=str)[:4000]}\n请继续."})

        if not answer:
            answer = "达到最大步数, 强制结束"
        yield {
            "event": "final",
            "answer": answer,
            "transcript": transcript,
            "steps": tool_steps,
        }
