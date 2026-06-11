# 01 架构总览

## 1.1 分层

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite + shadcn/ui + Recharts)            │
│  - 计时录入页（兼容 cstimer 操作手感）                       │
│  - 训练看板（每日目标 / Session 卡片 / AI 报告 / 训练项）     │
│  - 复盘页（逐动回放 + 停顿热图）                             │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST / WebSocket
┌──────────────────────────┴──────────────────────────────────┐
│  Backend (FastAPI)                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ MoveIngest   │  │ SessionAgg   │  │ AICoach          │   │
│  │ 转动流接入    │  │ Session 聚合 │  │ LLM 分析 + 训练生成 │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
│         └─────────────────┴──────────────────┘             │
│                          │                                 │
│  ┌───────────────────────▼──────────────────────────────┐   │
│  │ Domain (纯 Python 业务逻辑)                           │   │
│  │  - CFOPStageDetector  阶段识别                         │   │
│  │  - PauseAnalyzer      停顿分析                         │   │
│  │  - MoveEfficiency     转动效率                         │   │
│  │  - TrainingRuleEngine 训练项生成（规则库）              │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                 │
│  ┌───────────────────────▼──────────────────────────────┐   │
│  │ Persistence (SQLAlchemy 2.0)                          │   │
│  │  SQLite (dev) | PostgreSQL (prod)                      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           │
                ┌──────────┴──────────┐
                │  External LLM API   │
                │  (OpenAI 兼容)       │
                └─────────────────────┘
```

## 1.2 核心数据流

```
[计时器产生 Move 事件] 
   └─> POST /api/moves          (写入 move_events 表)
   └─> WebSocket push           (实时刷新看板)
   
[完成一次复原]
   └─> POST /api/solves         (汇总写入 solves 表)
   └─> 后台异步: 阶段切分 / 停顿识别 / 效率计算
   └─> 写入 solve_stages / pause_events
   
[累积满 12 次 (一个 Session)]
   └─> 触发 Session 聚合 job
   └─> 写入 sessions / session_stats
   └─> 调用 AICoach.analyze(session_id) -> 写 ai_reports
   └─> 调 TrainingRuleEngine -> 写 training_tasks
   └─> 更新每日目标进度
```

## 1.3 关键模块职责

| 模块 | 职责 | 关键类 |
|---|---|---|
| 接入层 | 接收 Move 事件、Solve 完成事件 | `MoveIngestAPI`, `SolveSubmitAPI` |
| 领域 - 阶段 | 根据 Move 序列识别 Cross/F2L/OLL/PLL 边界 | `CFOPStageDetector` |
| 领域 - 停顿 | 在 Move 时间戳流上识别停顿区间 | `PauseAnalyzer` |
| 领域 - 效率 | 检测多余转动（重复、抵消） | `MoveEfficiency` |
| 领域 - 训练 | AI 结论 → 训练项映射 | `TrainingRuleEngine` |
| 领域 - 目标 | 每日目标管理 + 智能推荐 | `DailyGoalManager` |
| 持久化 | 表模型、迁移、查询 | `models/*`, `repositories/*` |
| AI | 构造 Prompt、调用 LLM、解析响应 | `AICoach` |
| 看板 API | 给前端用的聚合查询 | `DashboardAPI` |

## 1.4 关键依赖（下一轮实现）

```
fastapi
uvicorn[standard]
sqlalchemy>=2.0
pydantic>=2
pydantic-settings
aiosqlite / asyncpg
httpx                 # 调 LLM
tenacity              # 重试
python-dotenv
alembic               # 迁移
pytest, pytest-asyncio
```

## 1.5 兼容 cstimer 的策略

- 数据导入：解析 cstimer 导出的 JSON（其 `sessionData` / `property` 结构），写入新 schema
- 计时操作：复刻 cstimer 的按键/观察/启动/停止/判罚 5 段式交互
- 不修改 cstimer 源码，但保留 `cstimer-ref/` 目录作为参考
