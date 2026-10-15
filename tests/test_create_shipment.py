"""Shipment creation and validation rules."""
import pytest
from sqlalchemy.orm import Session

from cargo_bot.services import ValidationError, create_shipment, get_or_create_customer


def test_create_shipment_defaults_to_new(session: Session, customer):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    assert shipment.status.value == "new"
    assert shipment.code.startswith("CRG-")
    assert len(shipment.code) == 8


def test_codes_are_unique(session: Session, customer):
    from tests.conftest import make_shipment

    codes = {make_shipment(session, customer).code for _ in range(25)}
    assert len(codes) == 25


def test_rejects_blank_pickup(session: Session, customer):
    from tests.conftest import make_shipment

    with pytest.raises(ValidationError):
        make_shipment(session, customer, pickup="   ")


def test_rejects_same_pickup_and_dropoff(session: Session, customer):
    from tests.conftest import make_shipment

    with pytest.raises(ValidationError):
        make_shipment(session, customer, dropoff="kyiv, khreschatyk 1")


def test_rejects_non_positive_weight(session: Session, customer):
    from tests.conftest import make_shipment

    with pytest.raises(ValidationError):
        make_shipment(session, customer, weight_kg=0)


def test_rejects_negative_weight(session: Session, customer):
    from tests.conftest import make_shipment

    with pytest.raises(ValidationError):
        make_shipment(session, customer, weight_kg=-3)


def test_rejects_weight_over_limit(session: Session, customer):
    from tests.conftest import make_shipment

    with pytest.raises(ValidationError, match="limit"):
        make_shipment(session, customer, weight_kg=50_000)


def test_rejects_blank_cargo_type(session: Session, customer):
    from tests.conftest import make_shipment

    with pytest.raises(ValidationError):
        make_shipment(session, customer, cargo_type="  ")


def test_rejects_negative_price(session: Session, customer):
    from tests.conftest import make_shipment

    with pytest.raises(ValidationError):
        make_shipment(session, customer, price=-1.0)


def test_accepts_weight_exactly_at_limit(session: Session, customer):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer, weight_kg=10_000)
    assert shipment.weight_kg == 10_000


def test_customer_is_idempotent(session: Session):
    first = get_or_create_customer(session, 555, "Alex")
    second = get_or_create_customer(session, 555, "Alex")
    assert first.id == second.id


def test_customer_name_updates_on_reuse(session: Session):
    first = get_or_create_customer(session, 556, "Alex")
    second = get_or_create_customer(session, 556, "Alex New")
    assert second.name == "Alex New"
    assert first.id == second.id


def test_short_phone_rejected(session: Session):
    with pytest.raises(ValidationError):
        get_or_create_customer(session, 557, "Alex", phone="123")


def test_phone_is_normalised(session: Session):
    cust = get_or_create_customer(session, 558, "Alex", phone="+38 (050) 111-22-33")
    assert cust.phone == "+380501112233"


def test_persisted_to_database(session: Session, customer):
    from sqlalchemy import select

    from cargo_bot.models import Shipment
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    session.commit()
    found = session.scalars(select(Shipment).where(Shipment.code == shipment.code)).one()
    assert found.id == shipment.id