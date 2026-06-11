# 05 智能训练生成逻辑

> **核心思路**: **AI 诊断 → 规则库 → 训练任务**。
> 训练项是**确定性的**（用规则生成），AI 只负责诊断，不直接生成文本。
> 这样:
> - 训练项有明确 metric 跟踪、可量化
> - LLM 故障时仍能生成训练计划
> - 训练项可以被"收藏/复用"，不依赖某次 AI 输出

---

## 5.1 规则库定义

```pseudo
# training_rules.py (示意)
@dataclass
class TrainingRule:
    id: str
    match: Callable[[SessionStats, AIReportParsed], bool]
    generate: Callable[[SessionStats, AIReportParsed], list[TrainingTask]]
    cooldown_days: int
    priority: int  # 数字越小优先级越高


RULES: list[TrainingRule] = [

    # ── 1) F2L 停顿/耗时 集中 ─────────────────────────────────────
    TrainingRule(
        id="R-F2L-001",
        match=lambda s, r: s.avg_f2l_ms and s.pct_f2l >= 0.45
                           or s.pause_stage_dist.get("f2l", 0) >= 0.5,
        generate=lambda s, r: [
            TrainingTask(
                category="f2l",
                title="慢拧 F2L 预判 5 把",
                description="节拍器 0.6s/动, 强制每组动 1 的末段观察下一组 slot",
                config_json={"sets": 5, "metronome_ms": 600},
                target_metric="f2l_observation_ms",
                duration_min=15
            ),
            TrainingTask(
                category="lookahead",
                title="盲拧 F2L 预判 10 对",
                description="闭眼识别 10 对, 目标每对 ≤ 2.5s",
                config_json={"pairs": 10, "target_per_pair_ms": 2500},
                target_metric="f2l_pairs_per_min",
                duration_min=10
            )
        ],
        cooldown_days=1,
        priority=10
    ),

    # ── 2) PLL 识别停顿过长 ─────────────────────────────────────────
    TrainingRule(
        id="R-PLL-001",
        match=lambda s, r: (s.avg_pll_ms and s.avg_pll_ms >= 2500)
                           or s.pause_stage_dist.get("pll", 0) >= 0.3,
        generate=lambda s, r: [
            TrainingTask(
                category="pll",
                title="PLL recognition drill",
                description="展示 21 个 PLL case, 目标 0.5s 内起手; 错 3 次循环重练",
                config_json={"cases": "all", "max_recognition_ms": 500},
                target_metric="pll_recognition_ms",
                duration_min=12
            ),
            TrainingTask(
                category="pll",
                title="2-side PLL 强制 8 步以内",
                description="A/E/H/Ua 等简单 PLL 强制无废动, 记 10 次",
                config_json={"cases": ["Aa","E","H","Ua","Ub","Z"], "max_moves": 8},
                target_metric="pll_move_count",
                duration_min=8
            )
        ],
        cooldown_days=1,
        priority=20
    ),

    # ── 3) Cross 占比 >15% ────────────────────────────────────────
    TrainingRule(
        id="R-CROSS-001",
        match=lambda s, r: s.pct_cross >= 0.15,
        generate=lambda s, r: [
            TrainingTask(
                category="cross",
                title="8 步 Cross 练习",
                description="用 cstimer 训练模式, 限定 ≤8 步 Cross, 连续 10 把",
                config_json={"mode": "cross_8", "rounds": 10},
                target_metric="cross_moves",
                duration_min=10
            ),
            TrainingTask(
                category="cross",
                title="Cross 扩展 F2L 首对",
                description="做完 Cross 后, 不停下, 直接转入第一组 F2L (无观察停顿)",
                config_json={"rounds": 5},
                target_metric="cross_to_f2l_transition_ms",
                duration_min=12
            )
        ],
        cooldown_days=2,
        priority=30
    ),

    # ── 4) 转动过多 (>65 步) ──────────────────────────────────────
    TrainingRule(
        id="R-MOVES-001",
        match=lambda s, r: (s.avg_moves or 0) >= 65,
        generate=lambda s, r: [
            TrainingTask(
                category="fingers",
                title="最少步复盘",
                description="挑 3 把 move_count 最高的, 对比 algs.net 标准解, 列出废动",
                config_json={"count": 3, "source": "session_top_moves"},
                target_metric="effective_moves",
                duration_min=20
            )
        ],
        cooldown_days=3,
        priority=40
    ),

    # ── 5) 后半段掉速 (endurance) ──────────────────────────────────
    TrainingRule(
        id="R-END-001",
        match=lambda s, r: (s.speed_trend or 1) >= 1.12,
        generate=lambda s, r: [
            TrainingTask(
                category="metronome",
                title="连续 25 把不间断",
                description="节拍器 4.0s/把, 完成 25 把为目标, 培养耐力",
                config_json={"count": 25, "metronome_ms": 4000},
                target_metric="speed_trend",
                duration_min=20
            )
        ],
        cooldown_days=2,
        priority=50
    ),

    # ── 6) OLL 停顿/耗时 集中 ─────────────────────────────────────
    TrainingRule(
        id="R-OLL-001",
        match=lambda s, r: s.pause_stage_dist.get("oll", 0) >= 0.25
                           or (s.avg_oll_ms and s.pct_oll >= 0.20),
        generate=lambda s, r: [
            TrainingTask(
                category="oll",
                title="全 OLL 识别刷",
                description="展示 OLL case, 0.7s 内说出名字",
                config_json={"mode": "oll_recog", "max_ms": 700},
                target_metric="oll_recognition_ms",
                duration_min=12
            ),
            TrainingTask(
                category="oll",
                title="2-look OLL 强化",
                description="如果 OLL 平均动数 > 6, 切 2-look OLL 1 周",
                config_json={"mode": "2look_oll"},
                target_metric="oll_moves",
                duration_min=10
            )
        ],
        cooldown_days=2,
        priority=25
    ),
]
```

---

## 5.2 训练生成引擎

```pseudo
class TrainingRuleEngine:
    def __init__(self, rules: list[TrainingRule] = RULES):
        self.rules = sorted(rules, key=lambda r: r.priority)

    def generate(self,
                 session_id: int,
                 stats: SessionStats,
                 ai_report: AIReportParsed | None
                ) -> list[TrainingTask]:
        ctx = (stats, ai_report or {})
        tasks: list[TrainingTask] = []

        for rule in self.rules:
            if not rule.match(*ctx):
                continue
            if self._in_cooldown(rule, session_id):
                continue
            tasks.extend(rule.generate(*ctx))
            if len(tasks) >= 4:   # 一次最多 4 个, 避免过载
                break

        # 如果 AI 没结论或规则都没命中, 给出通用保底
        if not tasks:
            tasks.append(self._default_task(stats))

        # 关联 session & ai_report
        for t in tasks:
            t.session_id = session_id
            t.ai_report_id = ai_report.get("id") if ai_report else None
            t.scheduled_for = today_zero_ms(user.timezone)

        return tasks

    def _in_cooldown(self, rule: TrainingRule, session_id: int) -> bool:
        since_ms = now_ms() - rule.cooldown_days * 86_400_000
        return training_task_repo.exists_recent(
            user_id=current_user_id(),
            rule_id=rule.id,
            since_ms=since_ms
        )

    def _default_task(self, stats: SessionStats) -> TrainingTask:
        return TrainingTask(
            category="fingers",
            title="基础手感维护 10 把",
            description="无目标, 放松解 10 把, 关注手指流畅度",
            config_json={"count": 10},
            duration_min=8
        )
```

---

## 5.3 与每日目标的整合

```pseudo
class DailyGoalIntegrator:
    def merge_into_today(self, user_id: int, generated: list[TrainingTask]) -> list[DailyGoalItem]:
        """
        把新生成的训练项加入今日目标清单, 并基于耗时重新估算 count target。
        规则:
          - 训练项总耗时 > 30 min -> 维持 count 不变 (已经够量)
          - 训练项总耗时 < 10 min -> 把 count target 调高 20%
        """
        today = daily_goal_repo.today(user_id)
        total_train_min = sum(t.duration_min for t in generated)
        new_training_ids = training_task_repo.insert_many(generated)

        if total_train_min < 10 and today.target_kind == "count":
            today.target_value = int(today.target_value * 1.2)
            daily_goal_repo.update(today)

        return [
            DailyGoalItem(kind="count", value=today.target_value, completed=today.completed_value),
            *(DailyGoalItem(kind="training", task_id=id) for id in new_training_ids)
        ]
```

---

## 5.4 训练项完成追踪

```pseudo
class TrainingTaskTracker:
    def mark_done(self, task_id: int, result: dict):
        task = training_task_repo.get(task_id)
        task.status = "done"
        task.completed_at = now_ms()
        task.result_json = json.dumps(result)  # {"self_rating": 4, "felt": "good"}
        training_task_repo.update(task)
        return task
```

每日目标页面展示:

```
今日目标 (2026-06-08)
─────────────────────
计时主目标: 12 把  ▓▓▓▓▓▓▓▓░░░░  7/12
训练项:
  ✓ [已完成] 慢拧 F2L 预判 5 把       15min
  ◌ [待办]   PLL recognition drill    12min
  ✓ [已完成] Cross ≤8 步练习         10min
```

---

## 5.5 智能推荐次日目标

```pseudo
class NextDayRecommender:
    def recommend(self, user_id: int) -> DailyGoal:
        today = daily_goal_repo.today(user_id)
        today_achievement = today.completed_value / max(1, today.target_value)
        recent = daily_goal_repo.list_recent(user_id, days=7)
        fatigue = self._fatigue_score(recent)

        # 多因子决策表
        if today_achievement >= 1.0 and fatigue < 0.6:
            suggested = int(today.target_value * 1.10)   # 提 10%
        elif today_achievement < 0.5:
            suggested = int(today.target_value * 0.90)   # 降 10%
        else:
            suggested = today.target_value

        return DailyGoal(
            user_id=user_id,
            goal_date=tomorrow_zero_ms(user.timezone),
            target_kind="count",
            target_value=suggested,
            recommended=True
        )

    def _fatigue_score(self, recent: list[DailyGoal]) -> float:
        """0~1, 越高越疲劳"""
        if not recent: return 0.0
        last_3 = recent[-3:]
        return min(1.0, mean(g.achieved_ratio for g in last_3))
```
