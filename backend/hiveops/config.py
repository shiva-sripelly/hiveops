"""Settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

EMBED_DIM = 384


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    database_url: str = "sqlite+aiosqlite:///./hiveops.db"
    redis_url: str | None = None
    llm_provider: str = "auto"  # auto | anthropic | openai | sim
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-5-5"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    sim_delay: float = 0.25  # seconds per simulated LLM call, so live logs look live
    workers: int = 3
    seed_demo: bool = True
    seed_demo_runs: bool = True
    slack_webhook_url: str | None = None
    static_dir: str | None = None
    max_upload_mb: int = 15
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def from_env(cls) -> Settings:
        d = cls()
        return cls(
            database_url=os.environ.get("DATABASE_URL", d.database_url),
            redis_url=os.environ.get("REDIS_URL") or None,
            llm_provider=os.environ.get("LLM_PROVIDER", d.llm_provider).lower(),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", d.anthropic_model),
            openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
            openai_base_url=os.environ.get("OPENAI_BASE_URL", d.openai_base_url),
            openai_model=os.environ.get("OPENAI_MODEL", d.openai_model),
            sim_delay=float(os.environ.get("SIM_DELAY", d.sim_delay)),
            workers=int(os.environ.get("WORKERS", d.workers)),
            seed_demo=_bool("SEED_DEMO", d.seed_demo),
            seed_demo_runs=_bool("SEED_DEMO_RUNS", d.seed_demo_runs),
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL") or None,
            static_dir=os.environ.get("STATIC_DIR") or None,
        )

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")
