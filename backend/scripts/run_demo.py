"""
端到端 demo 脚本:
1. 初始化 DB
2. 创建用户 + 12 个 solve (使用真实 scramble + 模拟解法 + 模拟停顿)
3. 关闭 Session, 触发聚合 → AI 分析 → 训练项生成 → 每日目标
4. 打印结果
"""
from __future__ import annotations
import time
import random
import json
import sys
import os

# 让脚本能 import app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.settings import settings
from app.persistence.db import init_db, SessionLocal
from app.persistence.models import User
from app.persistence import repositories as repo
from app.domain.solve_recorder import SolveRecorder
from app.domain.cube_model import generate_random_scramble, apply_moves_facelet, parse_moves, SOLVED_FACELET
from app.domain.session_aggregator import SessionAggregator
from app.domain.training_engine import TrainingRuleEngine
from app.domain.daily_goal import DailyGoalManager


def _now_ms() -> int:
    return int(time.time() * 1000)


# 模拟一次典型 solve: 从 SOLVED 应用 scramble, 然后模拟一段解法
# 为了让 stage detector 真实地能识别阶段, 我们用一段 CFOP 解法 (cross/f2l/oll/pll)
SAMPLE_SOLUTION = [
    # Cross
    "F", "R", "U", "R'", "U'", "F'",
    # F2L pair 1
    "R", "U", "R'", "U", "R", "U2", "R'",
    # F2L pair 2
    "L'", "U'", "L", "U'", "L'", "U2", "L",
    # F2L pair 3
    "R", "U", "R'", "U'", "R", "U'", "R'",
    # F2L pair 4
    "L'", "U'", "L", "U", "L'", "U", "L",
    # OLL
    "R", "U2", "R'", "U'", "R", "U2", "L'", "U", "R'", "L",
    # PLL
    "R", "U", "R'", "U'", "R'", "F", "R2", "U'", "R'", "U'", "R", "U", "R'", "F'",
]


def simulate_solve(recorder: SolveRecorder, user_id: int, target_ms: int, rng: random.Random) -> dict:
    """模拟一次 solve, 写入 DB. 全程一个 session."""
    from app.persistence import repositories as r
    from app.persistence.models import Cube
    # 真实 scramble
    scramble = generate_random_scramble(seed=rng.randint(0, 1 << 31))

    # 用相对时间戳 (从 0 开始), 后续按比例放大
    n_moves = len(SAMPLE_SOLUTION)
    started_at = _now_ms()

    # 简单按目标总时长均匀分配
    move_timestamps: list[int] = []
    for i in range(n_moves):
        t = int(target_ms * (i + 1) / n_moves)
        # 在 F2L 段加停顿: 累积停顿量
        move_timestamps.append(t)

    with SessionLocal() as s:
        # 创建 cube
        sess = r.get_open_session(s, user_id)
        if not sess:
            sess = r.create_session(s, user_id=user_id, target_size=12,
                                     name=f"auto-{_now_ms()}")
        cube = r.create_cube(s,
                              user_id=user_id,
                              session_id=sess.id,
                              puzzle_type="333",
                              scramble=scramble,
                              started_at=started_at,
                              ended_at=started_at,  # 临时
                              total_time_ms=0,
                              move_count=0)
        s.flush()
        cube_id = cube.id

        # 在基础时间上叠加 F2L 段停顿
        for i, mv in enumerate(SAMPLE_SOLUTION):
            in_f2l_range = 0.2 * n_moves < i < 0.8 * n_moves
            pause_ms = 0
            if in_f2l_range and rng.random() < 0.5:
                pause_ms = int(rng.uniform(400, 1600))
            elif rng.random() < 0.1:
                pause_ms = int(rng.uniform(300, 800))
            cum_ts = move_timestamps[i] + pause_ms
            absolute = started_at + cum_ts
            r.add_move(s, solve_id=cube_id, seq=i, move_text=mv,
                        is_smart_turn=False, timestamp_ms=cum_ts,
                        absolute_ms=absolute, stage_label=None)

        cube = s.get(Cube, cube_id)
        cum_ts = move_timestamps[-1] + sum(int(rng.uniform(0, 800)) for _ in range(5))  # 最后再加点
        cube.ended_at = started_at + cum_ts
        cube.total_time_ms = cum_ts
        cube.move_count = n_moves
        s.commit()

    # 走标准后处理
    return recorder.finish_solve(cube_id)


def main():
    print("=" * 70)
    print("CSTIMER 智能魔方训练助手 - 端到端 demo")
    print("=" * 70)

    # 1. 初始化 DB
    print("\n[1] 初始化数据库 ...")
    init_db()
    print(f"  DB: {settings.db_path}")

    # 2. 创建用户
    print("\n[2] 创建用户 ...")
    with SessionLocal() as s:
        user = repo.get_or_create_user(s, "demo_user", display_name="Demo")
        s.commit()
        user_id = user.id
    print(f"  user_id = {user_id}")

    # 3. 模拟 12 把 solve
    print("\n[3] 模拟 12 把 solve (target 10~15s) ...")
    recorder = SolveRecorder()
    rng = random.Random(42)
    for i in range(12):
        target_ms = rng.randint(10000, 15000)
        result = simulate_solve(recorder, user_id, target_ms, rng)
        print(f"  solve #{i+1:2d}  total={result['total_time_ms']/1000:5.2f}s  "
              f"moves={result['move_count']:2d}  "
              f"pauses={result['pause_count']:2d}  "
              f"conf={result['stage_confidence']:.2f}")

    # 4. 关闭 session (满 12 把)
    print("\n[4] 关闭当前 Session ...")
    with SessionLocal() as s:
        sess = repo.get_open_session(s, user_id)
        if sess:
            repo.close_session(s, sess.id)
            session_id = sess.id
            s.commit()
    print(f"  closed session_id = {session_id}")

    # 5. 聚合
    print("\n[5] Session 聚合 ...")
    summary = SessionAggregator().aggregate(session_id)
    print(f"  solve_count  = {summary.solve_count}")
    print(f"  avg3_ms      = {summary.avg3_ms}")
    print(f"  avg5_ms      = {summary.avg5_ms}")
    print(f"  avg_total_ms = {summary.avg_total_ms}")
    print(f"  avg_cross_ms = {summary.avg_cross_ms}")
    print(f"  avg_f2l_ms   = {summary.avg_f2l_ms}")
    print(f"  avg_oll_ms   = {summary.avg_oll_ms}")
    print(f"  avg_pll_ms   = {summary.avg_pll_ms}")
    print(f"  avg_pause_ms = {summary.avg_pause_ms}")
    print(f"  pause_stage_dist = {summary.pause_stage_dist}")
    print(f"  speed_trend  = {summary.speed_trend}")

    # 6. 训练项 (规则引擎 - 不用 LLM 也能跑)
    print("\n[6] 训练项生成 (规则引擎) ...")
    engine = TrainingRuleEngine()
    tasks = engine.generate(session_id, summary, user_id=user_id)
    for t in tasks:
        print(f"  [{t['id']:3d}] {t['category']:10s} | {t['title']} ({t['duration_min']}min)")

    # 7. AI 分析 (DeepSeek - 跳过如果没有 key)
    print("\n[7] AI 分析 (DeepSeek) ...")
    if settings.llm_api_key.startswith("sk-your") or settings.llm_api_key == "sk-test-placeholder":
        print("  [SKIP] 未配置 DEEPSEEK_API_KEY, 跳过 LLM 调用")
        print("        在 backend/.env 中填入 key 后重跑")
    else:
        from app.llm.ai_coach import AICoach
        try:
            coach = AICoach()
            report = coach.analyze(session_id, summary, user_level="进阶级")
            print(f"  bottlenecks : {report.get('bottlenecks')}")
            print(f"  speed_pattern: {report.get('speed_pattern')}")
            print(f"  summary     : {report.get('summary')}")
            for r in report.get("recommendations", []):
                print(f"    [{r['id']}] {r['text']} ({r['duration_min']}min, {r['frequency']})")
        except Exception as e:
            print(f"  [ERR] {e}")

    # 8. 每日目标
    print("\n[8] 每日目标 ...")
    mgr = DailyGoalManager()
    rec = mgr.recommend_for_today(user_id)
    print(f"  recommended target = {rec['target_value']}")
    mgr.update_progress(user_id)
    today = mgr.today_goal(user_id)
    print(f"  today  completed = {today['completed_value']} / target {today['target_value']}")

    print("\n" + "=" * 70)
    print("[OK] Demo finished")
    print("=" * 70)


if __name__ == "__main__":
    main()
