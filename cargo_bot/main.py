"""Bot entrypoint. Session lifecycle is handled by middleware."""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.types import TelegramObject

from .config import settings
from .handlers import build_dispatcher
from .models import build_engine, build_session_factory, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("cargo_bot")


class DbSessionMiddleware(BaseMiddleware):
    """One SQLAlchemy session per Telegram update, committed on success."""

    def __init__(self, session_factory) -> None:
        self._factory = session_factory

    async def __call__(self, handler, event: TelegramObject, data: dict):
        session = self._factory()
        data["session"] = session
        try:
            result = await handler(event, data)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def main() -> int:
    if not settings.bot_token:
        log.error("BOT_TOKEN is not set")
        return 1

    engine = build_engine(settings.database_url)
    init_db(engine)
    session_factory = build_session_factory(engine)

    from aiogram import Bot

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = build_dispatcher(DbSessionMiddleware(session_factory))

    async def _run() -> None:
        log.info("starting polling")
        await dp.start_polling(bot)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())