"""Runtime configuration.

SQLite by default so the bot runs with zero setup; set DATABASE_URL to a
PostgreSQL DSN for production. Everything else comes from the environment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite+pysqlite:///cargo.db")
    )
    admin_ids: frozenset[int] = field(
        default_factory=lambda: frozenset(
            int(chunk)
            for chunk in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",")
            if chunk.isdigit()
        )
    )
    currency: str = field(default_factory=lambda: os.getenv("CURRENCY", "$"))
    # Maximum cargo weight accepted per shipment, in kilograms.
    max_weight_kg: int = field(default_factory=lambda: _env_int("MAX_WEIGHT_KG", 10_000))

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


settings = Settings()