"""Queries, stats, revenue and formatting."""
from sqlalchemy.orm import Session

from cargo_bot.models import ShipmentStatus
from cargo_bot.services import (
    available_shipments,
    cancel,
    customer_shipments,
    driver_shipments,
    progress_text,
    revenue,
    stats,
)


def test_available_shipments_excludes_assigned(session: Session, customer, driver):
    from tests.conftest import make_shipment

    first = make_shipment(session, customer)
    make_shipment(session, customer)
    available = available_shipments(session)
    assert len(available) == 2

    from cargo_bot.services import assign_driver

    assign_driver(session, first.code, driver)
    remaining = {s.code for s in available_shipments(session)}
    assert first.code not in remaining


def test_available_excludes_cancelled(session: Session, customer):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    cancel(session, shipment.code)
    assert available_shipments(session) == []


def test_driver_shipments_only_own(session: Session, customer, driver):
    from cargo_bot.services import assign_driver, register_driver
    from tests.conftest import make_shipment

    other = register_driver(session, 3003, "Other", "+380509998877")
    mine = make_shipment(session, customer)
    theirs = make_shipment(session, customer)

    assign_driver(session, mine.code, driver)
    assign_driver(session, theirs.code, other)

    assert {s.code for s in driver_shipments(session, driver)} == {mine.code}


def test_customer_shipments_lists_all(session: Session, customer):
    from tests.conftest import make_shipment

    a = make_shipment(session, customer)
    b = make_shipment(session, customer)
    assert {s.code for s in customer_shipments(session, customer)} == {a.code, b.code}


def test_stats_counts_by_status(session: Session, customer, driver):
    from cargo_bot.services import assign_driver
    from tests.conftest import make_shipment

    delivered = make_shipment(session, customer)
    cancelled = make_shipment(session, customer)
    make_shipment(session, customer)

    from cargo_bot.services import advance

    assign_driver(session, delivered.code, driver)
    advance(session, delivered.code, ShipmentStatus.PICKED_UP)
    advance(session, delivered.code, ShipmentStatus.IN_TRANSIT)
    advance(session, delivered.code, ShipmentStatus.DELIVERED)
    cancel(session, cancelled.code)

    result = stats(session)
    assert result["total"] == 3
    assert result["delivered"] == 1
    assert result["cancelled"] == 1
    assert result["new"] == 1
    assert result["active"] == 1


def test_stats_empty(session: Session):
    result = stats(session)
    assert result["total"] == 0
    assert result["delivered"] == 0


def test_revenue_counts_delivered_only(session: Session, customer, driver):
    from cargo_bot.services import advance, assign_driver
    from tests.conftest import make_shipment

    delivered = make_shipment(session, customer, price=100.0)
    pending = make_shipment(session, customer, price=999.0)

    assign_driver(session, delivered.code, driver)
    advance(session, delivered.code, ShipmentStatus.PICKED_UP)
    advance(session, delivered.code, ShipmentStatus.IN_TRANSIT)
    advance(session, delivered.code, ShipmentStatus.DELIVERED)

    assert revenue(session) == 100.0
    assert pending.price == 999.0


def test_revenue_zero_when_nothing_delivered(session: Session, customer):
    from tests.conftest import make_shipment

    make_shipment(session, customer, price=50.0)
    assert revenue(session) == 0.0


def test_progress_text_marks_completed_steps(session: Session, customer, driver):
    from cargo_bot.services import assign_driver
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    text = progress_text(shipment)
    assert "OK Created" in text
    assert "-- Delivered" in text

    assign_driver(session, shipment.code, driver)
    assert "OK Driver assigned" in progress_text(shipment)


def test_progress_text_cancelled(session: Session, customer):
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    cancel(session, shipment.code)
    assert progress_text(shipment) == "Cancelled"


def test_progress_text_delivered_all_ok(session: Session, customer, driver):
    from cargo_bot.services import advance, assign_driver
    from tests.conftest import make_shipment

    shipment = make_shipment(session, customer)
    assign_driver(session, shipment.code, driver)
    advance(session, shipment.code, ShipmentStatus.PICKED_UP)
    advance(session, shipment.code, ShipmentStatus.IN_TRANSIT)
    advance(session, shipment.code, ShipmentStatus.DELIVERED)

    text = progress_text(shipment)
    assert "--" not in text