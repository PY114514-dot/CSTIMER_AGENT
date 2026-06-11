# 06 前端看板建议 (React + Vite + shadcn/ui)

> 选型已经在前面确认。下面是**信息架构 + 关键组件 + 接口契约**，下一轮按此实现。

---

## 6.1 路由 / 页面

```
/                    今日看板 (默认首页)
/timer               计时器 (cstimer 风格)
/sessions            Session 列表
/sessions/:id        Session 详情 (AI 报告 + 训练项)
/training            今日训练项清单
/history             历史趋势
/solves/:id          单次复原复盘 (动序回放 + 停顿热图)
/settings            设置 (智能魔方 / LLM key / 时区 / 目标偏好)
```

---

## 6.2 今日看板 (核心页)

**布局** (12 栅格):

```
┌──────────────────────────────────────────────────────────────┐
│  [DatePicker] 2026-06-08  ← →            [刷新] [新 Session] │
├─────────────────┬─────────────────────┬──────────────────────┤
│  每日目标        │  当前 Session 卡片    │  AI 教练 (最新一份)   │
│  12 把 / 7 完成  │  avg3 11.42          │  瓶颈: F2L, PLL 识别   │
│  ▓▓▓▓▓▓▓░░░ 58% │  趋势 ↓ -0.6s        │  训练项: 3 条          │
│  [开始计时]      │  [查看详情]           │  [去训练]             │
├─────────────────┴─────────────────────┴──────────────────────┤
│  阶段耗时分布 (Stacked Bar 12 把)                              │
│  ▰▰▰▰ Cross   ▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰ F2L   ▰▰ OLL   ▰▰ PLL        │
├──────────────────────────────────────────────────────────────┤
│  停顿热图 (Heatmap: 把次 × 时间窗)                              │
│      0s   2s   4s   6s   8s  10s  12s  14s                     │
│  #1 ░░   ░    ░    ▓▓   ░    ░    ░    ░                      │
│  #2 ░    ░    ▓    ░    ░    ░    ░    ░                      │
│  ...                                                          │
├──────────────────────────────────────────────────────────────┤
│  历史 avg3 折线 (近 30 个 Session)                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 6.3 关键组件清单 (shadcn/ui)

| 组件 | 用途 | 关键 props |
|---|---|---|
| `<DailyGoalRing />` | 环形进度，今日目标 | `target`, `completed` |
| `<SessionCard />` | Session 摘要 | `session`, `stats`, `trend` |
| `<AICoachCard />` | AI 报告 | `report`, `recommendations` |
| `<StageBreakdown />` | 阶段耗时堆叠图 | `solves[]` |
| `<PauseHeatmap />` | 停顿热图 | `solves[]` |
| `<TrendChart />` | 折线/区域图 | `series[]` |
| `<TrainingTaskList />` | 训练项 | `tasks[]`, `onComplete` |
| `<TimerPad />` | 计时器主体 | `onSolveFinish` |
| `<ScrambleView />` | 打乱展示 | `scramble` |
| `<MoveReplay />` | 动序回放 | `solveId` |

图表统一用 **Recharts**（与 React 生态贴合）。

---

## 6.4 接口契约 (TypeScript-ish)

```ts
// GET /api/dashboard/today
interface TodayDashboard {
  date: string;          // 'YYYY-MM-DD'
  daily_goal: {
    target_kind: 'count' | 'time' | 'duration';
    target_value: number;
    completed_value: number;
    is_achieved: boolean;
    recommended: boolean;
  };
  current_session: {
    id: number;
    cube_count: number;
    target_size: number;
    stats: SessionStats;
  } | null;
  latest_ai_report: {
    id: number;
    session_id: number;
    bottlenecks: string[];
    summary: string;
    recommendations: Recommendation[];
    created_at: number;
  } | null;
  training_tasks: TrainingTask[];
  stage_breakdown: Array<{
    solve_id: number;
    seq: number;
    cross_ms: number;
    f2l_ms: number;
    oll_ms: number;
    pll_ms: number;
  }>;
  pause_heatmap: Array<{
    solve_id: number;
    seq: number;
    bins_ms: number[];   // 每 200ms 一格
  }>;
  trend_30: Array<{
    session_id: number;
    closed_at: number;
    avg3_ms: number;
    avg5_ms: number;
  }>;
}

interface SessionStats {
  avg_total_ms: number;
  best_ms: number;
  worst_ms: number;
  std_dev_ms: number;
  avg3_ms: number;
  avg5_ms: number;
  avg12_ms: number | null;
  avg_cross_ms: number | null;
  avg_f2l_ms:   number | null;
  avg_oll_ms:   number | null;
  avg_pll_ms:   number | null;
  avg_moves: number;
  avg_pause_ms: number;
  pause_count: number;
  pause_stage_dist: Record<string, number>;
  speed_trend: number;
}

interface TrainingTask {
  id: number;
  category: string;
  title: string;
  description: string;
  target_metric: string;
  duration_min: number;
  status: 'pending' | 'doing' | 'done' | 'skipped';
}

interface Recommendation {
  id: string;
  category: string;
  metric_to_improve: string;
  text: string;
  duration_min: number;
  frequency: 'daily' | 'every_other_day' | 'weekly';
}
```

---

## 6.5 状态管理

- **Server state**: TanStack Query (`@tanstack/react-query`)
- **Client state**: Zustand（仅用于：当前用户、计时器运行时状态、当前 Session ID）
- **实时刷新**: WebSocket `/ws` 推送新 solve、新训练项

---

## 6.6 主题 / 设计

- shadcn/ui `slate` 基底，`zinc` 中性色
- 主色: `#6366f1` (indigo-500)
- 关键指标用 `tabular-nums`
- 字号: 计时大数字 `text-7xl font-mono tabular-nums tracking-tight`
- 暗色优先（速拧党夜间训练多）

---

## 6.7 关键交互细节

1. **计时大数字** 进入时 `RequestAnimationFrame` 更新，避免 setState 风暴
2. **按键协议**: 长按空格 1.0s 进入 inspect，松手后任意键开始（与 cstimer 完全一致）
3. **AI 报告加载**: 用骨架卡片 +30s 超时（LLM 慢），超时显示 "AI 还在分析，先继续训练"
4. **训练项完成**: 单击勾选，自动调用 `POST /api/training/:id/done` 并刷新今日目标

---

## 6.8 不在本轮范围

- 真实 LLM 接入（下一轮）
- 智能魔方 BLE 桥接（下一轮，预留 `cube_devices` 表）
- 移动端 App（仅 Web 响应式）
- 多人/排行榜
