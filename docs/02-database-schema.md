# 02 数据库 Schema

> **ORM**: SQLAlchemy 2.0（Declarative + Mapped）
> **方言**: SQLite (dev) / PostgreSQL (prod)，差异点已在注释中标注
> **时间统一**: 数据库内全部存 UTC 时间戳（毫秒整数 `BIGINT`），展示时按用户时区

---

## 2.1 ER 总览

```
users ──┬── solves ──┬── move_events
        │            ├── solve_stages
        │            ├── pause_events
        │            └── ai_reports
        ├── sessions ──── session_stats
        ├── training_tasks
        ├── daily_goals
        └── cube_devices    (智能魔方配对)
```

---

## 2.2 表定义

### 2.2.1 `users` — 用户

```sql
CREATE TABLE users (
    id              BIGSERIAL PRIMARY KEY,           -- PG: BIGSERIAL; SQLite: INTEGER
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT,
    timezone        TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    avg_level       TEXT,                            -- 初学/进阶级/高手/顶尖
    created_at      BIGINT NOT NULL,                 -- 毫秒时间戳
    settings_json   TEXT NOT NULL DEFAULT '{}'       -- 用户偏好 (JSON 字符串)
);
```

### 2.2.2 `cubes` — 复原汇总（每一次完整复原 = 一行）

> 这是最核心的"事实表"。

```sql
CREATE TABLE cubes (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id      BIGINT REFERENCES sessions(id) ON DELETE SET NULL,
    puzzle_type     TEXT NOT NULL DEFAULT '333',     -- '333' / '444' / ...
    scramble        TEXT NOT NULL,                   -- 打乱公式原文
    started_at      BIGINT NOT NULL,                 -- 第一次按键/启动 毫秒
    ended_at        BIGINT NOT NULL,                 -- 停止 毫秒
    total_time_ms   INTEGER NOT NULL,                -- 计入成绩的总时长
    penalty_ms      INTEGER NOT NULL DEFAULT 0,      -- +2: 2000, DNF: -1
    move_count      INTEGER NOT NULL,                -- 转动次数（含 F2L/OLL/PLL 全部）
    is_dnf          BOOLEAN NOT NULL DEFAULT FALSE,
    notes           TEXT,
    source          TEXT NOT NULL DEFAULT 'manual',  -- manual / smart_cube / cstimer_import
    created_at      BIGINT NOT NULL,
    INDEX idx_cubes_user_started (user_id, started_at DESC),
    INDEX idx_cubes_session (session_id)
);
```

### 2.2.3 `move_events` — 转动事件（每转一行）

```sql
CREATE TABLE move_events (
    id              BIGSERIAL PRIMARY KEY,
    solve_id        BIGINT NOT NULL REFERENCES cubes(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,                -- 在本次复原中的次序, 0,1,2,...
    move_text       TEXT NOT NULL,                   -- "R", "U'", "x", "M2"
    is_smart_turn   BOOLEAN NOT NULL DEFAULT FALSE,  -- 来自智能魔方/手动录入
    timestamp_ms    BIGINT NOT NULL,                 -- 相对 started_at 的毫秒
    absolute_ms     BIGINT NOT NULL,                 -- 绝对毫秒
    stage_label     TEXT,                            -- 写入时由后处理填: cross/f2l/oll/pll/post
    UNIQUE (solve_id, seq),
    INDEX idx_moves_solve (solve_id)
);
```

> 注: `stage_label` 通常在 solve 完成后由 `CFOPStageDetector` 回填，所以写入时可以为 NULL。

### 2.2.4 `solve_stages` — 阶段耗时（每个 solve 一行存 4 个阶段）

```sql
CREATE TABLE solve_stages (
    id              BIGSERIAL PRIMARY KEY,
    solve_id        BIGINT NOT NULL UNIQUE REFERENCES cubes(id) ON DELETE CASCADE,
    cross_start_ms  BIGINT,
    cross_end_ms    BIGINT,
    f2l_start_ms    BIGINT,
    f2l_end_ms      BIGINT,
    oll_start_ms    BIGINT,
    oll_end_ms      BIGINT,
    pll_start_ms    BIGINT,
    pll_end_ms      BIGINT,
    cross_dur_ms    INTEGER,    -- 派生字段: cross_end - cross_start
    f2l_dur_ms      INTEGER,
    oll_dur_ms      INTEGER,
    pll_dur_ms      INTEGER,
    f2l_pairs       INTEGER,   -- F2L 完成的组数 (0~4)
    detected_method TEXT        -- 'cfop' / 'roux' / 'cf-ce' / 'unknown'
);
```

### 2.2.5 `pause_events` — 停顿事件

```sql
CREATE TABLE pause_events (
    id              BIGSERIAL PRIMARY KEY,
    solve_id        BIGINT NOT NULL REFERENCES cubes(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,                -- 第几次停顿
    start_ms        BIGINT NOT NULL,                 -- 相对 started_at
    end_ms          BIGINT NOT NULL,
    duration_ms     INTEGER NOT NULL,                -- end - start
    before_move_seq INTEGER NOT NULL,                -- 紧邻的上一动 seq
    after_move_seq  INTEGER NOT NULL,                -- 紧邻的下一动 seq
    stage_label     TEXT,                            -- 停顿发生在哪个阶段
    type            TEXT NOT NULL DEFAULT 'observe', -- observe / think / lockup
    INDEX idx_pause_solve (solve_id),
    INDEX idx_pause_stage (stage_label)
);
```

> `type` 启发式分类（仅作参考，最终可由 AI 校正）：
> - 紧随解法阶段切换 = `observe`
> - 同一 case 内部 >=1.5s = `think`
> - 跨多个阶段且 >2s = `lockup`

### 2.2.6 `sessions` — 训练 Session（默认 12 次一包）

```sql
CREATE TABLE sessions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT,                            -- 用户自定义/自动: "2026-06-08 21:00 12把"
    target_size     INTEGER NOT NULL DEFAULT 12,     -- 每包目标次数
    is_auto         BOOLEAN NOT NULL DEFAULT TRUE,   -- 自动满 12 关闭 / 手动
    started_at      BIGINT NOT NULL,
    ended_at        BIGINT,
    cube_count      INTEGER NOT NULL DEFAULT 0,      -- 实际完成次数
    status          TEXT NOT NULL DEFAULT 'open',   -- open / closed / archived
    INDEX idx_sessions_user_time (user_id, started_at DESC)
);
```

### 2.2.7 `session_stats` — Session 汇总统计

```sql
CREATE TABLE session_stats (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          BIGINT NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
    avg_total_ms        INTEGER,
    best_ms             INTEGER,
    worst_ms            INTEGER,
    std_dev_ms          INTEGER,
    avg3_ms             INTEGER,                  -- 去尾均值
    avg5_ms             INTEGER,
    avg12_ms            INTEGER,
    avg_cross_ms        INTEGER,
    avg_f2l_ms          INTEGER,
    avg_oll_ms          INTEGER,
    avg_pll_ms          INTEGER,
    avg_moves           REAL,
    avg_pause_ms        INTEGER,
    pause_count         INTEGER,
    pause_stage_dist    TEXT,                      -- JSON: {"f2l":0.7,"oll":0.2}
    speed_trend         REAL,                      -- 后半段 / 前半段 速率比
    last_analyzed_at    BIGINT
);
```

### 2.2.8 `ai_reports` — AI 分析报告

```sql
CREATE TABLE ai_reports (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    model           TEXT NOT NULL,                 -- 'gpt-4o-mini' / 'claude-haiku' / 'local-llama'
    prompt_version  TEXT NOT NULL,                 -- 'v1.2'
    raw_prompt      TEXT NOT NULL,                 -- 入参完整快照 (可重放)
    raw_response    TEXT NOT NULL,                 -- 原始输出
    parsed_json     TEXT,                          -- 结构化结论 (JSON)
    bottleneck      TEXT,                          -- 短板阶段: 'f2l,pll'
    confidence      REAL,
    created_at      BIGINT NOT NULL,
    INDEX idx_ai_user_time (user_id, created_at DESC)
);
```

> `parsed_json` 标准结构:
> ```json
> {
>   "bottlenecks": ["f2l", "pll_recognition"],
>   "root_causes": ["observation > 1.5s on PLL", "no lookahead in F2L"],
>   "speed_pattern": "front_heavy",   // front_heavy / back_heavy / even
>   "recommendations": [
>     {"id": "R1", "text": "慢拧 5 把 F2L 强制预判下一组", "metric": "f2l_observation"},
>     {"id": "R2", "text": "PLL recognition drill", "metric": "pll_recognition"}
>   ]
> }
> ```

### 2.2.9 `training_tasks` — 训练项（每日计划 + 临时插入）

```sql
CREATE TABLE training_tasks (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id      BIGINT REFERENCES sessions(id) ON DELETE SET NULL,   -- 来源
    ai_report_id    BIGINT REFERENCES ai_reports(id) ON DELETE SET NULL,
    daily_goal_id   BIGINT REFERENCES daily_goals(id) ON DELETE SET NULL,
    category        TEXT NOT NULL,                 -- 'cross' / 'f2l' / 'oll' / 'pll' / 'lookahead' / 'fingers' / 'metronome'
    title           TEXT NOT NULL,                 -- "慢拧 F2L 预判 5 把"
    description     TEXT,
    config_json     TEXT,                          -- 训练配置: 次数/节拍/限制
    target_metric   TEXT,                          -- 期望改善的指标
    duration_min    INTEGER,                       -- 预计耗时
    status          TEXT NOT NULL DEFAULT 'pending', -- pending / doing / done / skipped
    scheduled_for   BIGINT,                        -- 计划日期 (毫秒/日 0 点)
    completed_at    BIGINT,
    result_json     TEXT,                          -- 训练后自评
    created_at      BIGINT NOT NULL,
    INDEX idx_tasks_user_date (user_id, scheduled_for)
);
```

### 2.2.10 `daily_goals` — 每日目标

```sql
CREATE TABLE daily_goals (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    goal_date       BIGINT NOT NULL,               -- 当日 0 点的毫秒戳
    target_kind     TEXT NOT NULL,                 -- 'count' / 'time' / 'duration'
    target_value    INTEGER NOT NULL,              -- 12 / 36 / 3600 (秒)
    completed_value INTEGER NOT NULL DEFAULT 0,
    is_achieved     BOOLEAN NOT NULL DEFAULT FALSE,
    recommended     BOOLEAN NOT NULL DEFAULT FALSE,-- 是否系统智能推荐
    note            TEXT,
    UNIQUE (user_id, goal_date)
);
```

### 2.2.11 `cube_devices` — 智能魔方配对（为未来扩展预留）

```sql
CREATE TABLE cube_devices (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    brand           TEXT,                          -- 'GAN' / 'MoYu' / 'GoCube'
    model           TEXT,
    mac_address     TEXT,
    nickname        TEXT,
    paired_at       BIGINT,
    last_sync_at    BIGINT
);
```

---

## 2.3 关键索引与性能说明

- `cubes(user_id, started_at DESC)`：看板首页按时间倒序分页
- `move_events(solve_id, seq)` UNIQUE：保证转动次序唯一
- `pause_events(stage_label)`：跨 Session 聚合"停顿集中在哪个阶段"
- `training_tasks(user_id, scheduled_for)`：每日计划列表

> 当 `move_events` > 5e6 行时建议按 `cubes` 起始月份做**分区表**（PG 特性）；SQLite 单机使用时归档旧数据到 `move_events_archive`。

---

## 2.4 SQLite vs PostgreSQL 差异

| 维度 | SQLite | PostgreSQL |
|---|---|---|
| 主键 | `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL` / `BIGINT GENERATED ALWAYS AS IDENTITY` |
| 时间 | INTEGER ms（统一） | INTEGER ms（统一） |
| JSON | `TEXT` 存 JSON 字符串 | 优先 `JSONB` |
| 全文检索 | FTS5 扩展 | `tsvector` |
| 并发 | 单写锁 | MVCC |

SQLAlchemy 2.0 通过方言无关的类型 (`BigInteger`, `Text`, `Boolean`) 自动适配，本设计在两边都能跑。
