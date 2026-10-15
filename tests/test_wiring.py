"""Wiring checks: every user-facing action must be reachable by a filter.

Importing the module proves nothing, so these tests evaluate the real
aiogram filters against fake updates and assert the route matches.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, User
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cargo_bot.config import Settings, settings as global_settings
from cargo_bot.handlers import router
from cargo_bot.models import build_engine, build_session_factory, init_db

#: Syntactically valid dummy token; command filters only read the prefix.
TEST_BOT = Bot(token="42:TEST")


def make_message(text: str, user_id: int = 1001) -> Message:
    return Message(
        message_id=1,
        date=datetime(2026, 1, 1),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Alex"),
        text=text,
    )


async def _matches_async(observer, message: Message) -> bool:
    # Command filters read the current bot to resolve the command prefix.
    async with TEST_BOT.context():
        for handler in observer.handlers:
            if not handler.filters:
                # FSM-state handlers cannot be judged without a state machine.
                continue
            verdicts = []
            for filt in handler.filters:
                callback = getattr(filt, "callback", None)
                if callback is None:
                    verdicts.append(False)
                    continue
                try:
                    # Command filters take (event, bot); others take (event).
                    import inspect as _inspect

                    params = _inspect.signature(callback).parameters
                    if "bot" in params:
                        result = callback(message, TEST_BOT)
                    else:
                        result = callback(message)
                    if asyncio.iscoroutine(result):
                        result = await result
                except Exception:  # noqa: BLE001 - a filter needing context cannot match
                    result = False
                verdicts.append(bool(result))
            if verdicts and all(verdicts):
                return True
    return False


def matches(observer, message: Message) -> bool:
    return asyncio.run(_matches_async(observer, message))


@pytest.fixture()
def session() -> Session:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    db = build_session_factory(engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_router_has_handlers():
    assert router.message.handlers, "no message handlers registered"
    assert router.callback_query.handlers, "no callback handlers registered"


@pytest.mark.parametrize(
    "text",
    [
        "/start",
        "/cancel",
        "New shipment",
        "My shipments",
        "Track",
        "Become a driver",
        "Available jobs",
        "My jobs",
        "CRG-ABCD",
    ],
)
def test_action_is_reachable(text):
    assert matches(router.message, make_message(text)) is True


def test_plain_question_is_not_captured():
    """A normal sentence must not be swallowed by a keyboard-button filter."""
    assert matches(router.message, make_message("what is the weather today?")) is False


def test_garbage_is_not_captured():
    assert matches(router.message, make_message("not-a-code")) is False


def test_callback_routes_exist():
    filters = [
        type(filt).__name__
        for handler in router.callback_query.handlers
        for filt in handler.filters
    ]
    assert filters, "callback filters are missing"


def test_driver_registration_parses(session):
    from cargo_bot.services import register_driver

    name, _, phone = "Sam | +380501112233".partition("|")
    driver = register_driver(session, 2001, name.strip(), phone.strip())
    assert driver.name == "Sam"
    assert driver.phone == "+380501112233"


def test_admin_check_rejects_stranger():
    assert global_settings.is_admin(999999) is False


def test_admin_check_accepts_configured_ids(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "555, 556")
    s = Settings()
    assert s.is_admin(555) is True
    assert s.is_admin(556) is True
    assert s.is_admin(557) is False