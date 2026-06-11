"""
全局 pytest fixtures: 强制在 import app 前设置测试用 DATABASE_URL,
避免 SQLAlchemy 引擎绑定到真实 DB.
"""
import os
import tempfile


def pytest_configure(config):
    # 在任何 app.* 导入前设置环境变量
    tmp = tempfile.mkdtemp(prefix="cstimer_test_")
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{tmp}/test.db")
    os.environ.setdefault("LLM_API_KEY", "sk-test-placeholder")
