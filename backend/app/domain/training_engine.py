"""
训练项规则引擎 (Python 重写 docs/05-training-generator.md)

与公式库集成:
  - config_json 不再写字符串 case 列表, 而是写真实 case_id 列表
  - 新增 R-PLL-002 (PLL 识别刷, 21 case 全量) / R-OLL-002 (OLL 识别刷)
  - AI 报告里的 bottleneck (pll_recognition/oll_recognition) 也会反向驱动选 case
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Callable, Optional

from app.domain.session_aggregator import SessionSummary
from app.persistence import repositories as repo
from app.persistence.db import SessionLocal
from app.settings import settings


@dataclass
class TrainingTaskDict:
    rule_id: str
    category: str
    title: str
    description: str
    config_json: dict
    target_metric: str
    duration_min: int

    def to_db_kwargs(self, *, user_id: int, session_id: int, ai_report_id: int | None) -> dict:
        import json
        return {
            "user_id": user_id,
            "session_id": session_id,
            "ai_report_id": ai_report_id,
            "rule_id": self.rule_id,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "config_json": json.dumps(self.config_json, ensure_ascii=False),
            "target_metric": self.target_metric,
            "duration_min": self.duration_min,
            "status": "pending",
            "scheduled_for": self._today_zero_ms(),
        }

    def _today_zero_ms(self) -> int:
        now = time.gmtime()
        return int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, 0)) * 1000)


@dataclass
class TrainingRule:
    id: str
    priority: int
    cooldown_days: int
    match: Callable[[SessionSummary], bool]
    generate: Callable[[SessionSummary, "RuleContext"], list[TrainingTaskDict]]


@dataclass
class RuleContext:
    """generate 阶段能拿到的额外信息 (含 AI 报告 / 公式库)"""
    user_id: int
    session_id: int
    ai_report: dict | None
    # 缓存: set_code -> list[FormulaCase]
    _case_cache: dict[str, list] | None = None

    def case_ids(self, set_code: str, codes: list[str]) -> list[int]:
        return repo.formula_case_ids_by_codes(self._s(), set_code, codes)

    def all_case_ids(self, set_code: str) -> list[int]:
        if self._case_cache is None:
            self._case_cache = {}
        if set_code not in self._case_cache:
            self._case_cache[set_code] = repo.list_formula_cases_by_set(self._s(), set_code)
        return [c.id for c in self._case_cache[set_code]]

    def bottleneck_set(self) -> str | None:
        """从 AI 报告里挑出主要瓶颈对应的 set_code, 用于动态选 case"""
        if not self.ai_report:
            return None
        b = (self.ai_report.get("bottlenecks") or [])
        if not b:
            return None
        b0 = b[0]
        return {
            "cross":         "F2L",   # cross 阶段紧接 F2L
            "f2l":           "F2L",
            "f2l_lookahead": "F2L",
            "cross_efficiency": "F2L",
            "oll":           "OLL",
            "oll_recognition":  "OLL",
            "pll":           "PLL",
            "pll_recognition": "PLL",
            "move_efficiency": None,
            "endurance":     None,
        }.get(b0)

    def _s(self):
        # 每次取新 session, 避免跨规则长事务; RuleContext 是 dataclass, 借用 SessionLocal
        return SessionLocal()


# ── 规则 ─────────────────────────────────────────────────
def _rule_f2l() -> TrainingRule:
    return TrainingRule(
        id="R-F2L-001", priority=10, cooldown_days=1,
        match=lambda s: ((s.avg_f2l_ms or 0) and (s.avg_f2l_ms / max(1, s.avg_total_ms or 1)) >= 0.45)
                        or s.pause_stage_dist.get("f2l", 0) >= 0.5,
        generate=lambda s, ctx: [
            TrainingTaskDict(
                rule_id="R-F2L-001", category="f2l",
                title="慢拧 F2L 预判 5 把",
                description="节拍器 0.6s/动, 强制每组动 1 的末段观察下一组 slot",
                config_json={
                    "sets": 5,
                    "metronome_ms": 600,
                    "f2l_case_ids": ctx.all_case_ids("F2L"),  # 全量 41 case 供训练页轮
                },
                target_metric="f2l_observation_ms",
                duration_min=15,
            ),
            TrainingTaskDict(
                rule_id="R-F2L-001", category="lookahead",
                title="盲拧 F2L 预判 10 对",
                description="闭眼识别 10 对, 目标每对 ≤ 2.5s",
                config_json={"pairs": 10, "target_per_pair_ms": 2500,
                             "f2l_case_ids": ctx.all_case_ids("F2L")},
                target_metric="f2l_pairs_per_min",
                duration_min=10,
            ),
        ],
    )


def _rule_pll() -> TrainingRule:
    def _pll_match(s: SessionSummary) -> bool:
        if (s.avg_pll_ms or 0) >= 2500:
            return True
        if s.pause_stage_dist.get("pll", 0) >= 0.3:
            return True
        return False

    def _pll_generate(s: SessionSummary, ctx: RuleContext) -> list[TrainingTaskDict]:
        # 简单 case: Aa, E, H, Ua, Ub, Z (新手友好, 8 步以内)
        easy_codes = ["Aa", "E", "H", "Ua", "Ub", "Z"]
        easy_ids = ctx.case_ids("PLL", easy_codes)
        return [
            TrainingTaskDict(
                rule_id="R-PLL-001", category="pll",
                title="PLL recognition drill (推荐 6 入门)",
                description="展示 6 个常见 PLL case, 目标 0.5s 内起手; 错 3 次循环重练",
                config_json={
                    "pll_case_ids": easy_ids,
                    "max_recognition_ms": 500,
                    "max_retries": 3,
                },
                target_metric="pll_recognition_ms",
                duration_min=12,
            ),
            TrainingTaskDict(
                rule_id="R-PLL-001", category="pll",
                title="2-side PLL 强制 8 步以内",
                description="A/E/H/Ua/Ub/Z 等简单 PLL 强制无废动, 记 10 次",
                config_json={
                    "pll_case_ids": easy_ids,
                    "max_moves": 8,
                    "rounds": 10,
                },
                target_metric="pll_move_count",
                duration_min=8,
            ),
        ]

    return TrainingRule(id="R-PLL-001", priority=20, cooldown_days=1,
                        match=_pll_match, generate=_pll_generate)


def _rule_pll_recognition_all() -> TrainingRule:
    """R-PLL-002: 完整 21 case 识别刷 (高强度, 3 天 cooldown)"""
    def _match(s: SessionSummary) -> bool:
        return s.pause_stage_dist.get("pll", 0) >= 0.4 or (s.avg_pll_ms or 0) >= 4000

    def _gen(s: SessionSummary, ctx: RuleContext) -> list[TrainingTaskDict]:
        all_ids = ctx.all_case_ids("PLL")
        return [TrainingTaskDict(
            rule_id="R-PLL-002", category="pll",
            title="PLL 21 case 全量识别刷",
            description="全 21 PLL case 随机出, 0.5s 内说出名字; 错 5 次重练整组",
            config_json={
                "pll_case_ids": all_ids,
                "max_recognition_ms": 500,
                "max_retries": 5,
                "rounds": 21,
            },
            target_metric="pll_recognition_all_ms",
            duration_min=20,
        )]

    return TrainingRule(id="R-PLL-002", priority=15, cooldown_days=3,
                        match=_match, generate=_gen)


def _rule_cross() -> TrainingRule:
    return TrainingRule(
        id="R-CROSS-001", priority=30, cooldown_days=2,
        match=lambda s: ((s.avg_cross_ms or 0) and (s.avg_cross_ms / max(1, s.avg_total_ms or 1)) >= 0.15),
        generate=lambda s, ctx: [
            TrainingTaskDict(
                rule_id="R-CROSS-001", category="cross",
                title="8 步 Cross 练习",
                description="用训练模式, 限定 ≤8 步 Cross, 连续 10 把",
                config_json={"mode": "cross_8", "rounds": 10},
                target_metric="cross_moves",
                duration_min=10,
            ),
            TrainingTaskDict(
                rule_id="R-CROSS-001", category="cross",
                title="Cross 扩展 F2L 首对",
                description="做完 Cross 后, 不停下, 直接转入第一组 F2L (无观察停顿)",
                config_json={"rounds": 5},
                target_metric="cross_to_f2l_transition_ms",
                duration_min=12,
            ),
        ],
    )


def _rule_moves() -> TrainingRule:
    return TrainingRule(
        id="R-MOVES-001", priority=40, cooldown_days=3,
        match=lambda s: (s.avg_moves or 0) >= 65,
        generate=lambda s, ctx: [
            TrainingTaskDict(
                rule_id="R-MOVES-001", category="fingers",
                title="最少步复盘",
                description="挑 3 把 move_count 最高的, 对比标准解, 列出废动",
                config_json={"count": 3, "source": "session_top_moves"},
                target_metric="effective_moves",
                duration_min=20,
            ),
        ],
    )


def _rule_endurance() -> TrainingRule:
    return TrainingRule(
        id="R-END-001", priority=50, cooldown_days=2,
        match=lambda s: (s.speed_trend or 1) >= 1.12,
        generate=lambda s, ctx: [
            TrainingTaskDict(
                rule_id="R-END-001", category="metronome",
                title="连续 25 把不间断",
                description="节拍器 4.0s/把, 完成 25 把为目标, 培养耐力",
                config_json={"count": 25, "metronome_ms": 4000},
                target_metric="speed_trend",
                duration_min=20,
            ),
        ],
    )


def _rule_oll() -> TrainingRule:
    def _oll_match(s: SessionSummary) -> bool:
        if s.pause_stage_dist.get("oll", 0) >= 0.25:
            return True
        if (s.avg_oll_ms or 0) and (s.avg_oll_ms / max(1, s.avg_total_ms or 1)) >= 0.20:
            return True
        return False

    def _oll_gen(s: SessionSummary, ctx: RuleContext) -> list[TrainingTaskDict]:
        # 取 OLL 集合前 1/3 (新手版), seq=0 排前
        all_oll = repo.list_formula_cases_by_set(ctx._s(), "OLL")
        if not all_oll:
            return []
        # 取 dot/line/subset (这里用前 N 个简化, 后续可按 OLL_SUBSET 改进)
        subset_n = max(1, len(all_oll) // 3)
        subset_ids = [c.id for c in all_oll[:subset_n]]
        return [TrainingTaskDict(
            rule_id="R-OLL-001", category="oll",
            title=f"OLL 识别刷 (子集 {subset_n} 个)",
            description=f"展示 OLL case 子集, 0.7s 内说出名字, 共 {subset_n} 个",
            config_json={
                "oll_case_ids": subset_ids,
                "max_recognition_ms": 700,
                "rounds": subset_n,
            },
            target_metric="oll_recognition_ms",
            duration_min=12,
        )]

    return TrainingRule(id="R-OLL-001", priority=25, cooldown_days=2,
                        match=_oll_match, generate=_oll_gen)


def _rule_bottleneck_driven() -> TrainingRule:
    """R-BOTTLENECK-001: 直接按 AI 报告的 bottleneck 推一个聚焦训练项"""
    def _match(s: SessionSummary) -> bool:
        return False  # 只在 generate 时由 ctx 决定, match 永远 True 也不行 (会跟上面冲突); 用别的方式

    def _gen(s: SessionSummary, ctx: RuleContext) -> list[TrainingTaskDict]:
        set_code = ctx.bottleneck_set()
        if not set_code or not ctx.ai_report:
            return []
        ids = ctx.all_case_ids(set_code)
        # 即使 DB 暂无公式 (冷启动) 也生成, 让前端知道"该去刷 PLL", 训练页会用空列表占位
        # 挑前 8 个 (新手), 或全部 (高手)
        b = (ctx.ai_report.get("bottlenecks") or [""])[0]
        level = (ctx.ai_report.get("confidence") or 0.5)
        n = min(8, len(ids)) if level < 0.7 else len(ids)
        return [TrainingTaskDict(
            rule_id="R-BOTTLENECK-001", category=set_code.lower(),
            title=f"针对 {b} 瓶颈: {set_code} 集中训练",
            description=f"AI 报告识别 {b} 为主要瓶颈, 推荐该 {set_code} 子集优先刷",
            config_json={
                f"{set_code.lower()}_case_ids": ids[:n],
                "max_recognition_ms": 500,
                "rounds": n,
                "source": "ai_bottleneck",
            },
            target_metric=f"{b}_ms",
            duration_min=15,
        )]

    return TrainingRule(id="R-BOTTLENECK-001", priority=5, cooldown_days=1,
                        match=_match, generate=_gen)


DEFAULT_RULES: list[TrainingRule] = sorted(
    [
        _rule_f2l(),
        _rule_pll_recognition_all(),
        _rule_pll(),
        _rule_oll(),
        _rule_cross(),
        _rule_moves(),
        _rule_endurance(),
    ],
    key=lambda r: r.priority,
)


class TrainingRuleEngine:
    """主入口"""

    def __init__(self, rules: list[TrainingRule] | None = None):
        self.rules = rules or DEFAULT_RULES

    def generate(self,
                 session_id: int,
                 summary: SessionSummary,
                 ai_report: dict | None = None,
                 user_id: int | None = None,
                 max_tasks: int = 4,
                 ) -> list[dict]:
        tasks: list[TrainingTaskDict] = []
        ctx = RuleContext(user_id=user_id or 0, session_id=session_id, ai_report=ai_report)

        with SessionLocal() as s:
            uid = user_id or self._get_user_id(s, session_id)
            ctx.user_id = uid

            # 0) AI 瓶颈驱动规则 -> 永远先跑 (且替换一个低优先级槽位)
            if ai_report:
                bottle_rule = _rule_bottleneck_driven()
                if not self._in_cooldown(s, uid, bottle_rule.id, bottle_rule.cooldown_days):
                    bottle_tasks = bottle_rule.generate(summary, ctx)
                    if bottle_tasks:
                        tasks.extend(bottle_tasks)

            # 1) 跑普通规则, 留至少 1 个槽给可能的 default
            remaining = max(1, max_tasks - len(tasks))
            for rule in self.rules:
                if len(tasks) >= max_tasks:
                    break
                if not rule.match(summary):
                    continue
                if self._in_cooldown(s, uid, rule.id, rule.cooldown_days):
                    continue
                new_tasks = rule.generate(summary, ctx)
                tasks.extend(new_tasks[: max(0, max_tasks - len(tasks))])

            if not tasks:
                tasks.append(self._default_task())

            ai_report_id = ai_report.get("id") if ai_report else None
            db_tasks = [t.to_db_kwargs(user_id=uid, session_id=session_id, ai_report_id=ai_report_id)
                        for t in tasks]
            ids = repo.add_training_tasks(s, db_tasks)
            s.commit()
        return [{"id": tid, **{k: v for k, v in t.items() if k != "user_id"}}
                for tid, t in zip(ids, db_tasks)]

    def _in_cooldown(self, s, user_id: int, rule_id: str, cooldown_days: int) -> bool:
        since = int(time.time() * 1000) - cooldown_days * 86_400_000
        return repo.task_exists_recent(s, user_id, rule_id, since)

    def _default_task(self) -> TrainingTaskDict:
        return TrainingTaskDict(
            rule_id="R-DEFAULT", category="fingers",
            title="基础手感维护 10 把",
            description="无目标, 放松解 10 把, 关注手指流畅度",
            config_json={"count": 10},
            target_metric="general_smoothness",
            duration_min=8,
        )

    def _get_user_id(self, s, session_id: int) -> int:
        from app.persistence.models import TrainingSession
        sess = s.get(TrainingSession, session_id)
        return sess.user_id if sess else 0
