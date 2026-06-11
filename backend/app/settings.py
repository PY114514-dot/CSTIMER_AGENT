"""
全局配置 (基于 pydantic-settings, 读 .env)
"""
from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: str = "deepseek"
    llm_api_key: str = "sk-placeholder"
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout_s: int = 30

    # Database
    database_url: str = "sqlite:///./cstimer_coach.db"

    # 训练
    session_default_size: int = 12
    pause_threshold_ms: int = 500
    training_cooldown_days: int = 1

    @property
    def db_path(self) -> str:
        """从 sqlite:///./xxx.db 提取出实际文件路径"""
        url = self.database_url
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///"):]
        return ""


settings = Settings()
