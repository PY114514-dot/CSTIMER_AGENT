"""
SQLAlchemy 2.0 引擎与 Session 工厂
支持 sqlite (默认) / postgresql
"""
from __future__ import annotations
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from app.settings import settings


class Base(DeclarativeBase):
    pass


def _build_engine():
    url = settings.database_url
    kwargs = {"echo": False, "future": True}
    if url.startswith("sqlite"):
        # SQLite 需要 check_same_thread=False 才能在多线程下用
        kwargs["connect_args"] = {"check_same_thread": False}

        @event.listens_for(create_engine(url, **kwargs), "connect")
        def _enable_fk(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return create_engine(url, **kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
# 测试 fixture 会用 SessionLocal.configure(bind=eng) 切换, 保留原始 engine 引用便于还原
_original_engine = engine


def init_db() -> None:
    """创建所有表 (生产应改用 alembic 迁移)"""
    # 必须在 import models 之后调用, 否则 metadata 还没注册
    from app.persistence import models  # noqa: F401
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Session:
    """事务性 session 上下文"""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
