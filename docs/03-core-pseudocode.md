# 03 核心类/函数伪代码

> **目的**: 给出可直接转译成 Python 的伪代码骨架
> **风格**: 类 + 方法，类型提示用 TypeScript-like 风格（实际实现用 Python 3.12）
> **依赖**: 仅 `dataclasses`, 实际实现可换 Pydantic

---

## 3.1 顶层 API（FastAPI 路由层）

```pseudo
# routers/moves.py
@router.post("/api/moves")
def post_move(req: MoveEventRequest) -> Ack:
    """
    一次转动一报: 由前端或智能魔方桥接发出。
    在 solve 进行中, 写入 move_events。
    """
    solve = solve_repo.get_open(user_id=req.user_id)
    assert solve is not None, "no open solve"
    seq = move_repo.next_seq(solve.id)
    move_repo.insert(MoveEvent(
        solve_id=solve.id,
        seq=seq,
        move_text=req.move,
        timestamp_ms=req.relative_ms,
        absolute_ms=req.absolute_ms,
        is_smart_turn=req.is_smart_turn
    ))
    return Ack(ok=True, seq=seq)

# routers/solves.py
@router.post("/api/solves/{solve_id}/finish")
def finish_solve(solve_id: int) -> FinishResponse:
    """结束本次复原: 触发阶段识别 + 停顿识别 + Session 汇总检查"""
    solve = solve_repo.get(solve_id)
    moves = move_repo.list(solve_id)

    # 1. 阶段识别
    stages = CFOPStageDetector().detect(moves)
    solve_stages_repo.upsert(solve_id, stages)

    # 2. 停顿识别
    pauses = PauseAnalyzer(threshold_ms=500).analyze(moves, stages)
    pause_repo.replace_all(solve_id, pauses)

    # 3. 写入 move_events.stage_label (回填)
    move_repo.backfill_stage(solve_id, stages)

    # 4. 更新 solve 汇总字段
    solve_repo.update_derived(solve_id, stages, pauses)

    # 5. 检查 Session 闭环
    session = session_repo.current_open(user_id=solve.user_id)
    session_repo.increment(session.id)
    if session.cube_count >= session.target_size:
        session_repo.close(session.id)
        schedule_background(aggregate_session_job, session.id)
        schedule_background(run_ai_coach_job, session.id)

    return FinishResponse(solve_id=solve_id, session_id=session.id)

# routers/sessions.py
@router.get("/api/sessions/{session_id}")
def get_session(session_id: int) -> SessionDetail:
    """看板使用: 返回 Session 完整信息含 AI 报告与训练项"""
    return SessionDetail(
        session=session_repo.get(session_id),
        stats=session_stats_repo.get(session_id),
        solves=solve_repo.list_by_session(session_id),
        ai_report=ai_report_repo.latest_for_session(session_id),
        training_tasks=training_task_repo.list_by_session(session_id)
    )
```

---

## 3.2 领域核心类

### 3.2.1 `CFOPStageDetector` — 阶段识别

> **难点**: 阶段不是输入信号，是事后从 move 序列反推的"语义"。
> **策略**: 三层回退策略

```pseudo
class CFOPStageDetector:
    """
    三层回退:
      L1 启发式: 通过 scramble 反演 + 面归位判定, 快速给出粗略切分
      L2 转动法标记: 用户在计时过程中可手动按数字键标记阶段 (cstimer 风格)
      L3 LLM 校正: 对 L1 不可信时, 把 moves 序列发给 LLM 重新分段 (用于分析)
    """
    PAIRS_TO_F2L: int = 4
    PLL_CASES: set = { 'Aa','Ab','E','F','Ga','Gb','Gc','Gd','H','Ja','Jb','Na','Nb','Ra','Rb','T','Ua','Ub','V','Y','Z' }

    def detect(self, moves: list[MoveEvent]) -> SolveStages:
        # 1. 尝试 L1 启发式
        result = self._heuristic(moves)
        if result.confidence >= 0.85:
            return result.to_solve_stages()

        # 2. 查 L2 手动标记
        tagged = [m for m in moves if m.user_stage_tag is not None]
        if tagged:
            return self._from_user_tags(tagged)

        # 3. 退回 L3 LLM
        llm_result = LLMStageRefiner().refine(moves)
        return llm_result

    def _heuristic(self, moves: list[MoveEvent]) -> StageHypothesis:
        # 思路:
        #   a) 用 scramble 推算"已还原面" -> 反向遍历 moves, 找到 D 面 + 4 底棱归位那一刻 = cross_end
        #   b) 从 cross_end 后, 累计还原的 F2L 对数; 每多一对 = F2L 切分点
        #   c) OLL: 顶面同色那一刻
        #   d) PLL: 整体复原 = pll_end
        # 此处给出调用入口, 实际实现会调 cube_state.py 中的 CubeModel
        cube = CubeModel.from_solved()
        cross_done_at = None
        f2l_pairs = 0
        last_pair_complete = None
        oll_done_at = None
        pll_done_at = None

        for m in moves:
            cube.apply(m.move_text)
            if cross_done_at is None and self._is_cross_solved(cube):
                cross_done_at = m.timestamp_ms
            if cross_done_at and oll_done_at is None:
                pairs = self._count_solved_f2l_pairs(cube)
                if pairs > f2l_pairs:
                    f2l_pairs = pairs
                    if pairs == 1: f2l_start_at = m.timestamp_ms
                    if pairs == 4: f2l_end_at = m.timestamp_ms
            if cross_done_at and f2l_pairs == 4 and oll_done_at is None:
                if self._is_oll_done(cube):
                    oll_done_at = m.timestamp_ms
            if oll_done_at and pll_done_at is None:
                if self._is_solved(cube):
                    pll_done_at = m.timestamp_ms

        confidence = self._confidence_score(
            cross_done_at, f2l_pairs, oll_done_at, pll_done_at, len(moves)
        )
        return StageHypothesis(
            cross_start=0,
            cross_end=cross_done_at,
            f2l_start=f2l_start_at,
            f2l_end=f2l_end_at,
            oll_start=f2l_end_at,
            oll_end=oll_done_at,
            pll_start=oll_done_at,
            pll_end=pll_done_at,
            f2l_pairs=f2l_pairs,
            confidence=confidence
        )
```

> **关键点**: `CubeModel` 需要一个轻量魔方状态机，本轮文档先描述接口，下一轮实现用 Kociemba 风格的面状态结构（54 个 sticker）。

### 3.2.2 `PauseAnalyzer` — 停顿分析

```pseudo
@dataclass
class Pause:
    seq: int
    start_ms: int
    end_ms: int
    duration_ms: int
    before_move_seq: int
    after_move_seq: int
    stage_label: str
    type: str  # observe / think / lockup

class PauseAnalyzer:
    DEFAULT_THRESHOLD_MS = 500

    def __init__(self, threshold_ms: int = DEFAULT_THRESHOLD_MS):
        self.threshold_ms = threshold_ms

    def analyze(self, moves: list[MoveEvent], stages: SolveStages) -> list[Pause]:
        pauses: list[Pause] = []
        if len(moves) < 2:
            return pauses

        for i in range(1, len(moves)):
            gap = moves[i].timestamp_ms - moves[i-1].timestamp_ms
            if gap < self.threshold_ms:
                continue

            pause = Pause(
                seq=len(pauses),
                start_ms=moves[i-1].timestamp_ms,
                end_ms=moves[i].timestamp_ms,
                duration_ms=gap,
                before_move_seq=moves[i-1].seq,
                after_move_seq=moves[i].seq,
                stage_label=self._resolve_stage(moves[i-1], stages),
                type=self._classify(gap, moves[i-1], moves[i], stages)
            )
            pauses.append(pause)
        return pauses

    def _classify(self, gap: int, prev: MoveEvent, nxt: MoveEvent, stages: SolveStages) -> str:
        # 启发式分类
        prev_stage = self._resolve_stage(prev, stages)
        next_stage = self._resolve_stage(nxt, stages)
        if prev_stage != next_stage:
            return "observe"
        if gap >= 2000:
            return "lockup"
        return "think"

    def _resolve_stage(self, move: MoveEvent, stages: SolveStages) -> str:
        t = move.timestamp_ms
        if t <= stages.cross_end_ms: return "cross"
        if t <= stages.f2l_end_ms:   return "f2l"
        if t <= stages.oll_end_ms:   return "oll"
        return "pll"
```

### 3.2.3 `MoveEfficiency` — 转动效率

```pseudo
class MoveEfficiency:
    """
    计算:
      - move_count: 原始计数
      - effective_moves: 抵消后 (e.g. R R' = 0, R R R = R')
      - waste_moves: 原始 - effective
      - cross_moves: cross 阶段 move_count
      - f2l_move_per_pair: f2l_moves / f2l_pairs
    """
    def analyze(self, moves: list[MoveEvent], stages: SolveStages) -> MoveStats:
        raw = [m.move_text for m in moves]
        effective = self._cancel_moves(raw)
        waste = len(raw) - len(effective)

        cross_moves = sum(1 for m in moves if m.timestamp_ms <= stages.cross_end_ms)
        f2l_moves = sum(1 for m in moves
                        if stages.cross_end_ms < m.timestamp_ms <= stages.f2l_end_ms)
        oll_moves  = sum(1 for m in moves
                        if stages.f2l_end_ms < m.timestamp_ms <= stages.oll_end_ms)
        pll_moves  = sum(1 for m in moves
                        if stages.oll_end_ms < m.timestamp_ms <= stages.pll_end_ms)

        return MoveStats(
            raw=len(raw),
            effective=len(effective),
            waste=waste,
            cross_moves=cross_moves,
            f2l_moves=f2l_moves,
            oll_moves=oll_moves,
            pll_moves=pll_moves,
            f2l_per_pair=(f2l_moves / max(1, stages.f2l_pairs))
        )

    def _cancel_moves(self, raw: list[str]) -> list[str]:
        """
        简易抵消: 相邻相反动抵消, 4 同向折合为 1 反向。
        不考虑面块关系(那是 OLL/PLL 范畴), 这里的目的是检测"重复/犹豫"产生的废动。
        """
        out: list[str] = []
        for m in raw:
            face, mod = self._parse(m)
            if out:
                p_face, p_mod, count = out[-1]
                if p_face == face:
                    # 同面: 合并模数
                    new_mod = (p_mod + mod) % 4
                    if new_mod == 0:
                        out.pop()
                    else:
                        out[-1] = (p_face, new_mod, 1)
                    continue
            out.append((face, mod, 1))
        return [self._format(f, m) for f, m, _ in out]
```

### 3.2.4 `SessionAggregator` — Session 汇总

```pseudo
class SessionAggregator:
    def aggregate(self, session_id: int) -> SessionStats:
        solves = solve_repo.list_by_session(session_id, include_dnf=False)
        if not solves:
            return SessionStats()

        totals = [s.total_time_ms for s in solves]
        cross  = [s.cross_dur_ms for s in solves if s.cross_dur_ms]
        f2l    = [s.f2l_dur_ms for s in solves if s.f2l_dur_ms]
        oll    = [s.oll_dur_ms for s in solves if s.oll_dur_ms]
        pll    = [s.pll_dur_ms for s in solves if s.pll_dur_ms]

        # 速率趋势: 前半 vs 后半
        half = len(totals) // 2
        first_half = sum(totals[:half]) / max(1, half)
        second_half = sum(totals[half:]) / max(1, len(totals) - half)
        speed_trend = second_half / max(1, first_half)  # >1 = 后半掉速

        # 停顿阶段分布
        pause_dist = self._pause_stage_distribution(solves)

        return SessionStats(
            session_id=session_id,
            avg_total_ms=mean(totals),
            best_ms=min(totals),
            worst_ms=max(totals),
            std_dev_ms=stdev(totals),
            avg3_ms=self._trimmed_mean(totals, 1),
            avg5_ms=self._trimmed_mean(totals, 2),
            avg12_ms=mean(totals) if len(totals) >= 12 else None,
            avg_cross_ms=mean(cross) if cross else None,
            avg_f2l_ms=mean(f2l) if f2l else None,
            avg_oll_ms=mean(oll) if oll else None,
            avg_pll_ms=mean(pll) if pll else None,
            avg_moves=mean(s.move_count for s in solves),
            avg_pause_ms=self._avg_pause(solves),
            pause_count=self._total_pauses(solves),
            pause_stage_dist=pause_dist,
            speed_trend=speed_trend
        )

    def _trimmed_mean(self, xs: list[int], trim: int) -> int:
        if len(xs) <= trim * 2: return int(mean(xs))
        xs_sorted = sorted(xs)
        return int(mean(xs_sorted[trim:-trim]))

    def _pause_stage_distribution(self, solves: list[Solve]) -> dict[str, float]:
        counter: Counter = Counter()
        for s in solves:
            for p in pause_repo.list_by_solve(s.id):
                counter[p.stage_label] += p.duration_ms
        total = sum(counter.values()) or 1
        return {k: round(v / total, 3) for k, v in counter.items()}
```

### 3.2.5 `AICoach` — AI 分析调用

```pseudo
class AICoach:
    def __init__(self, llm: LLMClient, prompt_template: PromptTemplate):
        self.llm = llm
        self.template = prompt_template

    def analyze(self, session_id: int) -> AIReport:
        stats = session_stats_repo.get(session_id)
        prompt = self.template.render(stats)
        raw = self.llm.complete(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        parsed = self._parse_and_validate(raw)
        return ai_report_repo.create(
            session_id=session_id,
            user_id=stats.user_id,
            model=settings.LLM_MODEL,
            prompt_version=self.template.version,
            raw_prompt=prompt,
            raw_response=raw,
            parsed_json=parsed,
            bottleneck=",".join(parsed.get("bottlenecks", [])),
            confidence=parsed.get("confidence", 0.5)
        )

    def _parse_and_validate(self, raw: str) -> dict:
        obj = json.loads(raw)
        # 防御性默认值
        obj.setdefault("bottlenecks", [])
        obj.setdefault("root_causes", [])
        obj.setdefault("speed_pattern", "even")
        obj.setdefault("recommendations", [])
        return obj
```

### 3.2.6 `TrainingRuleEngine` — 训练项生成（规则库）

见 [05-training-generator.md](05-training-generator.md)

### 3.2.7 `DailyGoalManager` — 每日目标

```pseudo
class DailyGoalManager:
    def recommend_for_today(self, user_id: int) -> DailyGoal:
        """根据过去 7 日达成率, 推荐今日目标"""
        recent = daily_goal_repo.list_recent(user_id, days=7)
        avg_achievement = mean(g.achieved_ratio for g in recent) if recent else 0.7
        avg_target = mean(g.target_value for g in recent) if recent else 12

        # 简单规则: 达成率高 -> 提 10% ; 低 -> 降 10%
        if avg_achievement >= 1.0:
            suggested = int(avg_target * 1.1)
        elif avg_achievement < 0.6:
            suggested = int(avg_target * 0.9)
        else:
            suggested = int(avg_target)

        return DailyGoal(
            user_id=user_id,
            goal_date=today_zero_ms(user.timezone),
            target_kind="count",
            target_value=suggested,
            recommended=True
        )

    def update_progress(self, user_id: int) -> DailyGoal:
        """每次 finish_solve 后调用"""
        goal = daily_goal_repo.today(user_id)
        goal.completed_value = solve_repo.count_today(user_id, goal.goal_date)
        goal.is_achieved = goal.completed_value >= goal.target_value
        daily_goal_repo.upsert(goal)
        return goal
```

---

## 3.3 状态机

```pseudo
class SolveState:
    IDLE      -> 用户长按空格 (1.0s) -> INSPECTING
    INSPECTING -> 放开空格 + 触发打乱 -> READY
    READY     -> 再次按键 -> SOLVING
    SOLVING   -> 完成复原 (所有面同色) -> FINISHED
    SOLVING   -> 超时 (>5min) -> LOCKED
    FINISHED  -> 用户确认 / 判罚 -> LOGGED
```

对应 `cubes.status` 字段（可选）:

```sql
ALTER TABLE cubes ADD COLUMN status TEXT NOT NULL DEFAULT 'logged';
-- 'inspecting' / 'solving' / 'finished' / 'dnf' / '+2' / 'logged'
```
