"""
AI 教练 - 构造 Prompt, 调用 DeepSeek, 解析结果
"""
from __future__ import annotations
import json
import logging
import time
from typing import Optional

from app.domain.session_aggregator import SessionSummary
from app.llm.client import LLMClient, LLMError
from app.persistence import repositories as repo
from app.persistence.db import SessionLocal

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1.0"

SYSTEM_PROMPT = """你是一位经验丰富的魔方速拧高级教练, 同时也是数据分析师.
你的工作是基于一个选手最近一个 Session(默认 12 次复原) 的统计指标,
准确指出其当前的瓶颈, 并给出具体可执行的训练建议.

约束:
1. 必须严格基于提供的数据, 不要凭空捏造数字.
2. 最多指出 2 个最主要的瓶颈, 不要泛泛而谈.
3. 给出的训练建议必须可以立即被一名普通用户执行 (具体动作/次数/节拍).
4. 响应必须是合法 JSON, 不要包含 JSON 以外的任何文字.
"""

USER_PROMPT_TEMPLATE = """你是一位魔方高级教练. 以下是某选手最近一个 Session 的数据摘要.

## 基础信息
- 用户水平自评: {user_level}
- 训练项目: 3x3x3 标准 CFOP
- 本 Session 次数: {solve_count} (含 DNF {dnf_count})

## 总成绩
- 平均总时长: {avg_total_ms}ms (即 {avg_total_sec}s)
- 单次最佳: {best_ms}ms / 单次最差: {worst_ms}ms
- 标准差: {std_dev_ms}ms
- 去尾平均(avg3 / avg5): {avg3_ms}ms / {avg5_ms}ms
- 完整 12 次 avg12: {avg12_ms}

## 阶段耗时(平均)
- Cross: {avg_cross_ms}ms
- F2L:   {avg_f2l_ms}ms
- OLL:   {avg_oll_ms}ms
- PLL:   {avg_pll_ms}ms
- 各阶段占总时长百分比: cross {pct_cross}% / f2l {pct_f2l}% / oll {pct_oll}% / pll {pct_pll}%

## 转动效率
- 平均 move count: {avg_moves}
- 最长一次停顿: {longest_pause_ms}ms, 发生阶段: {longest_pause_stage}

## 停顿分析
- 平均停顿总时长/把: {avg_pause_ms}ms
- 停顿次数/把: {pause_count}
- 停顿时长分布(占总停顿): {pause_stage_distribution}
- 停顿类型分布: observe {pct_observe}% / think {pct_think}% / lockup {pct_lockup}%

## 速率趋势
- 前半段(前 {first_n} 次)平均: {first_half_ms}ms
- 后半段(后 {second_n} 次)平均: {second_half_ms}ms
- 比值(后半/前半): {speed_trend} (>1 = 后半掉速, <1 = 后半越快)

请输出 JSON, 严格按以下 schema:
{{
  "bottlenecks":          [string, string],
  "root_causes":          [string],
  "speed_pattern":        "front_heavy" | "back_heavy" | "even",
  "confidence":           number,
  "recommendations": [
    {{
      "id":               string,
      "category":         string,
      "metric_to_improve": string,
      "text":             string,
      "duration_min":     number,
      "frequency":        "daily" | "every_other_day" | "weekly"
    }}
  ],
  "summary":              string
}}

只输出 JSON, 不要解释, 不要 markdown 代码块标记.
"""


def _build_prompt(summary: SessionSummary, user_level: str = "未指定") -> str:
    s = summary
    def pct(part: int | None, total: int | None) -> str:
        if not part or not total:
            return "0"
        return f"{round(part / total * 100)}"

    total = s.avg_total_ms or 1
    pause = s.pause_type_dist
    return USER_PROMPT_TEMPLATE.format(
        user_level=user_level,
        solve_count=s.solve_count,
        dnf_count=s.dnf_count,
        avg_total_ms=s.avg_total_ms or "N/A",
        avg_total_sec=f"{(s.avg_total_ms or 0) / 1000:.2f}",
        best_ms=s.best_ms or "N/A",
        worst_ms=s.worst_ms or "N/A",
        std_dev_ms=s.std_dev_ms or "N/A",
        avg3_ms=s.avg3_ms or "N/A",
        avg5_ms=s.avg5_ms or "N/A",
        avg12_ms=s.avg12_ms or "样本不足",
        avg_cross_ms=s.avg_cross_ms or "N/A",
        avg_f2l_ms=s.avg_f2l_ms or "N/A",
        avg_oll_ms=s.avg_oll_ms or "N/A",
        avg_pll_ms=s.avg_pll_ms or "N/A",
        pct_cross=pct(s.avg_cross_ms, total),
        pct_f2l=pct(s.avg_f2l_ms, total),
        pct_oll=pct(s.avg_oll_ms, total),
        pct_pll=pct(s.avg_pll_ms, total),
        avg_moves=round(s.avg_moves, 1) if s.avg_moves else "N/A",
        longest_pause_ms=s.longest_pause_ms or "N/A",
        longest_pause_stage=s.longest_pause_stage or "N/A",
        avg_pause_ms=s.avg_pause_ms or 0,
        pause_count=s.pause_count or 0,
        pause_stage_distribution=json.dumps(s.pause_stage_dist, ensure_ascii=False),
        pct_observe=round(pause.get("observe", 0) * 100),
        pct_think=round(pause.get("think", 0) * 100),
        pct_lockup=round(pause.get("lockup", 0) * 100),
        first_n=(s.solve_count // 2),
        second_n=(s.solve_count - s.solve_count // 2),
        first_half_ms=s.first_half_ms or "N/A",
        second_half_ms=s.second_half_ms or "N/A",
        speed_trend=s.speed_trend or 1.0,
    )


ALLOWED_BOTTLENECKS = {
    "cross", "f2l", "oll", "pll_recognition",
    "f2l_lookahead", "cross_efficiency", "move_efficiency", "endurance",
}


def _validate(parsed: dict) -> dict:
    parsed["bottlenecks"] = [b for b in parsed.get("bottlenecks", [])
                             if b in ALLOWED_BOTTLENECKS][:2]
    if not parsed["bottlenecks"]:
        parsed["bottlenecks"] = ["f2l"]
    parsed.setdefault("root_causes", [])
    parsed.setdefault("speed_pattern", "even")
    parsed.setdefault("recommendations", [])
    parsed.setdefault("summary", "")
    if not parsed["recommendations"]:
        raise ValueError("LLM returned no recommendations")
    return parsed


class AICoach:
    """调用 LLM 产出 AI 报告"""

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or LLMClient()

    def analyze(self,
                session_id: int,
                summary: SessionSummary,
                user_level: str = "未指定"
                ) -> dict:
        prompt = _build_prompt(summary, user_level)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]
        raw = self.llm.complete(messages, response_format_json=True)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM returned non-JSON: {e}; raw={raw[:200]}") from e
        parsed = _validate(parsed)

        # 持久化
        with SessionLocal() as s:
            report = repo.create_ai_report(
                s,
                session_id=session_id,
                user_id=self._get_user_id(s, session_id),
                model=self.llm.model,
                prompt_version=PROMPT_VERSION,
                raw_prompt=prompt,
                raw_response=raw,
                parsed_json=json.dumps(parsed, ensure_ascii=False),
                bottleneck=",".join(parsed["bottlenecks"]),
                confidence=float(parsed.get("confidence", 0.5)),
                status="ok",
            )
            s.commit()
        parsed["id"] = report.id
        return parsed

    def _get_user_id(self, s, session_id: int) -> int:
        from app.persistence.models import TrainingSession
        sess = s.get(TrainingSession, session_id)
        return sess.user_id if sess else 0
