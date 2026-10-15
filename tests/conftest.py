import pytest
from sqlalchemy.orm import Session

from cargo_bot.models import (
    Base,
    Driver,
    ShipmentStatus,
    build_engine,
    build_session_factory,
    init_db,
)


@pytest.fixture()
def session() -> Session:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    init_db(engine)
    SessionLocal = build_session_factory(engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def customer(session: Session):
    from cargo_bot.services import get_or_create_customer

    return get_or_create_customer(session, telegram_id=1001, name="Alex", phone="+380501112233")


@pytest.fixture()
def driver(session: Session):
    from cargo_bot.services import register_driver

    return register_driver(session, telegram_id=2002, name="Driver Sam", phone="+380667778899")


def make_shipment(session: Session, customer, **overrides):
    from cargo_bot.services import create_shipment

    payload = {
        "pickup": "Kyiv, Khreschatyk 1",
        "dropoff": "Lviv, Svobody Ave 2",
        "cargo_type": "boxes",
        "weight_kg": 12.5,
        "price": 45.0,
    }
    payload.update(overrides)
    return create_shipment(session, customer, **payload)