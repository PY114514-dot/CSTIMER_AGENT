# CSTIMER 智能魔方训练助手 — 总体设计

> **基线**: 完全 Python 重写（cstimer 仅作行为参考，不直接 fork/修改原 JS 代码）
> **后端**: Python 3.12 + FastAPI + SQLAlchemy 2.0
> **数据库**: 默认 SQLite（开发/单机），可平滑切换 PostgreSQL
> **前端**: React + Vite + shadcn/ui + Recharts
> **AI**: 通过 OpenAI 兼容协议调用 LLM（兼容 GPT / Claude / DeepSeek / 本地 Ollama）
> **本轮范围**: 文档 + 关键原型（HTML+JS 可运行的看板 mock）
> **下一轮**: 完整可运行 MVP（FastAPI + SQLite + AI 真实接入 + 看板）

---

## 目录

- [01 架构总览](01-architecture.md)
- [02 数据库 Schema](02-database-schema.md)
- [03 核心类/函数伪代码](03-core-pseudocode.md)
- [04 AI 分析 Prompt 模板](04-ai-prompt.md)
- [05 智能训练生成逻辑](05-training-generator.md)
- [06 前端看板建议](06-frontend-dashboard.md)
- [07 关键原型 (HTML mock)](07-prototype-mock.md)
