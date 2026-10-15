"""Status machine, assignment and audit trail."""
import pytest
from sqlalchemy.orm import Session

from cargo_bot.models import ALLOWED_TRANSITIONS, ShipmentStatus
from cargo_bot.services import (
    InvalidTransition,
    ShipmentNotFound,
    ValidationError,
    advance,
    assign_driver,
    cancel,
    shipment_history,
)


def test_happy_path_to_delivery(session: Session, customer, driver):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)

    assign_driver(session, shipment.code, driver)
    assert shipment.status is ShipmentStatus.ASSIGNED
    assert shipment.driver_id == driver.id

    advance(session, shipment.code, ShipmentStatus.PICKED_UP)
    assert shipment.status is ShipmentStatus.PICKED_UP

    advance(session, shipment.code, ShipmentStatus.IN_TRANSIT)
    advance(session, shipment.code, ShipmentStatus.DELIVERED)

    assert shipment.status is ShipmentStatus.DELIVERED
    assert shipment.delivered_at is not None


def test_cannot_skip_assign(session: Session, customer):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    with pytest.raises(InvalidTransition):
        advance(session, shipment.code, ShipmentStatus.IN_TRANSIT)


def test_cannot_skip_pickup(session: Session, customer, driver):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    assign_driver(session, shipment.code, driver)
    with pytest.raises(InvalidTransition):
        advance(session, shipment.code, ShipmentStatus.DELIVERED)


def test_terminal_states_are_final(session: Session, customer, driver):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    assign_driver(session, shipment.code, driver)
    advance(session, shipment.code, ShipmentStatus.PICKED_UP)
    advance(session, shipment.code, ShipmentStatus.IN_TRANSIT)
    advance(session, shipment.code, ShipmentStatus.DELIVERED)

    with pytest.raises(InvalidTransition):
        advance(session, shipment.code, ShipmentStatus.CANCELLED)


def test_cancel_from_new(session: Session, customer):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    cancel(session, shipment.code)
    assert shipment.status is ShipmentStatus.CANCELLED
    assert shipment.status.is_terminal


def test_cancel_from_in_transit(session: Session, customer, driver):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    assign_driver(session, shipment.code, driver)
    advance(session, shipment.code, ShipmentStatus.PICKED_UP)
    advance(session, shipment.code, ShipmentStatus.IN_TRANSIT)
    cancel(session, shipment.code)
    assert shipment.status is ShipmentStatus.CANCELLED


def test_cannot_assign_twice(session: Session, customer, driver):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    assign_driver(session, shipment.code, driver)
    with pytest.raises(InvalidTransition):
        assign_driver(session, shipment.code, driver)


def test_cannot_assign_inactive_driver(session: Session, customer, driver):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    driver.is_active = False
    session.flush()
    with pytest.raises(ValidationError):
        assign_driver(session, shipment.code, driver)


def test_cannot_assign_after_cancel(session: Session, customer, driver):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    cancel(session, shipment.code)
    with pytest.raises(InvalidTransition):
        assign_driver(session, shipment.code, driver)


def test_unknown_code_raises(session: Session):
    with pytest.raises(ShipmentNotFound):
        advance(session, "CRG-0000", ShipmentStatus.PICKED_UP)


def test_lookup_is_case_insensitive(session: Session, customer, driver):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    assign_driver(session, shipment.code.lower(), driver)
    assert shipment.status is ShipmentStatus.ASSIGNED


def test_history_records_every_step(session: Session, customer, driver):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    assign_driver(session, shipment.code, driver)
    advance(session, shipment.code, ShipmentStatus.PICKED_UP)
    advance(session, shipment.code, ShipmentStatus.IN_TRANSIT)
    advance(session, shipment.code, ShipmentStatus.DELIVERED)

    history = shipment_history(session, shipment)
    assert [e.to_status for e in history] == [
        ShipmentStatus.NEW,
        ShipmentStatus.ASSIGNED,
        ShipmentStatus.PICKED_UP,
        ShipmentStatus.IN_TRANSIT,
        ShipmentStatus.DELIVERED,
    ]
    assert history[0].from_status is None
    assert history[1].from_status is ShipmentStatus.NEW


def test_history_first_event_records_actor(session: Session, customer):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    history = shipment_history(session, shipment)
    assert history[0].actor_id == customer.telegram_id


@pytest.mark.parametrize(
    ("status", "target", "allowed"),
    [
        (ShipmentStatus.NEW, ShipmentStatus.ASSIGNED, True),
        (ShipmentStatus.NEW, ShipmentStatus.PICKED_UP, False),
        (ShipmentStatus.ASSIGNED, ShipmentStatus.PICKED_UP, True),
        (ShipmentStatus.ASSIGNED, ShipmentStatus.NEW, False),
        (ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED, False),
    ],
)
def test_transition_table(status, target, allowed):
    assert (target in ALLOWED_TRANSITIONS[status]) is allowed


def test_terminal_flag():
    assert ShipmentStatus.DELIVERED.is_terminal
    assert ShipmentStatus.CANCELLED.is_terminal
    assert not ShipmentStatus.IN_TRANSIT.is_terminal