"""Service layer: all shipment business rules live here.

Handlers stay thin; everything testable is in this module and needs no
Telegram connection.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    ALLOWED_TRANSITIONS,
    Customer,
    Driver,
    Shipment,
    ShipmentStatus,
    StatusEvent,
)


class ServiceError(Exception):
    """Base error for rule violations."""


class ShipmentNotFound(ServiceError):
    pass


class InvalidTransition(ServiceError):
    def __init__(self, current: ShipmentStatus, target: ShipmentStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"cannot move {current.value} -> {target.value}")


class ValidationError(ServiceError):
    pass


_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _make_code(rng: secrets.SystemRandom | None = None) -> str:
    source = rng or secrets.SystemRandom()
    body = "".join(source.choice(_CODE_ALPHABET) for _ in range(4))
    return f"CRG-{body}"


def _normalise_phone(raw: str) -> str:
    cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if len(cleaned) < 7:
        raise ValidationError("phone number looks too short")
    return cleaned


def get_or_create_customer(
    session: Session,
    telegram_id: int,
    name: str,
    phone: str | None = None,
) -> Customer:
    customer = session.scalar(
        select(Customer).where(Customer.telegram_id == telegram_id)
    )
    if customer is None:
        customer = Customer(telegram_id=telegram_id, name=name.strip() or "Customer")
        session.add(customer)
        session.flush()
    else:
        if name and name.strip() and customer.name != name.strip():
            customer.name = name.strip()
    if phone:
        customer.phone = _normalise_phone(phone)
    session.flush()
    return customer


def register_driver(
    session: Session,
    telegram_id: int,
    name: str,
    phone: str,
) -> Driver:
    if not name.strip():
        raise ValidationError("driver name is required")
    driver = session.scalar(select(Driver).where(Driver.telegram_id == telegram_id))
    if driver is None:
        driver = Driver(
            telegram_id=telegram_id, name=name.strip(), phone=_normalise_phone(phone)
        )
        session.add(driver)
    else:
        driver.name = name.strip()
        driver.phone = _normalise_phone(phone)
        driver.is_active = True
    session.flush()
    return driver


def create_shipment(
    session: Session,
    customer: Customer,
    *,
    pickup: str,
    dropoff: str,
    cargo_type: str,
    weight_kg: float,
    price: float = 0.0,
    max_weight_kg: int = 10_000,
) -> Shipment:
    pickup = pickup.strip()
    dropoff = dropoff.strip()
    cargo_type = cargo_type.strip()

    if not pickup or not dropoff:
        raise ValidationError("pickup and dropoff are required")
    if pickup.casefold() == dropoff.casefold():
        raise ValidationError("pickup and dropoff must differ")
    if not cargo_type:
        raise ValidationError("cargo type is required")
    if weight_kg <= 0:
        raise ValidationError("weight must be positive")
    if weight_kg > max_weight_kg:
        raise ValidationError(f"weight exceeds {max_weight_kg} kg limit")
    if price < 0:
        raise ValidationError("price cannot be negative")

    # Retry on the (unlikely) code collision rather than failing the request.
    code = _make_code()
    for _ in range(5):
        exists = session.scalar(select(Shipment.id).where(Shipment.code == code))
        if exists is None:
            break
        code = _make_code()
    else:  # pragma: no cover - astronomically unlikely
        raise ServiceError("could not allocate a shipment code")

    shipment = Shipment(
        code=code,
        customer_id=customer.id,
        pickup=pickup,
        dropoff=dropoff,
        cargo_type=cargo_type,
        weight_kg=float(weight_kg),
        price=float(price),
        status=ShipmentStatus.NEW,
    )
    session.add(shipment)
    session.flush()
    session.add(
        StatusEvent(
            shipment_id=shipment.id,
            from_status=None,
            to_status=ShipmentStatus.NEW,
            actor_id=customer.telegram_id,
            note="shipment created",
        )
    )
    session.flush()
    return shipment


def assign_driver(session: Session, shipment_code: str, driver: Driver) -> Shipment:
    shipment = _load_by_code(session, shipment_code)
    if shipment.status is not ShipmentStatus.NEW:
        raise InvalidTransition(shipment.status, ShipmentStatus.ASSIGNED)
    if not driver.is_active:
        raise ValidationError("driver is not active")
    shipment.driver_id = driver.id
    return transition(session, shipment, ShipmentStatus.ASSIGNED, actor_id=driver.telegram_id)


def advance(
    session: Session,
    shipment_code: str,
    target: ShipmentStatus,
    actor_id: int = 0,
    note: str = "",
) -> Shipment:
    shipment = _load_by_code(session, shipment_code)
    return transition(session, shipment, target, actor_id=actor_id, note=note)


def transition(
    session: Session,
    shipment: Shipment,
    target: ShipmentStatus,
    *,
    actor_id: int = 0,
    note: str = "",
) -> Shipment:
    current = shipment.status
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(current, target)

    shipment.status = target
    shipment.updated_at = datetime.now(timezone.utc)
    if target is ShipmentStatus.DELIVERED:
        shipment.delivered_at = shipment.updated_at

    session.add(
        StatusEvent(
            shipment_id=shipment.id,
            from_status=current,
            to_status=target,
            actor_id=actor_id,
            note=note,
        )
    )
    session.flush()
    return shipment


def cancel(session: Session, shipment_code: str, actor_id: int = 0) -> Shipment:
    shipment = _load_by_code(session, shipment_code)
    return transition(session, shipment, ShipmentStatus.CANCELLED, actor_id=actor_id, note="cancelled")


def available_shipments(session: Session) -> list[Shipment]:
    """Open shipments that still need a driver."""
    return list(
        session.scalars(
            select(Shipment)
            .where(Shipment.status == ShipmentStatus.NEW)
            .order_by(Shipment.created_at.desc())
        )
    )


def driver_shipments(session: Session, driver: Driver) -> list[Shipment]:
    return list(
        session.scalars(
            select(Shipment)
            .where(Shipment.driver_id == driver.id)
            .order_by(Shipment.created_at.desc())
        )
    )


def customer_shipments(session: Session, customer: Customer) -> list[Shipment]:
    return list(
        session.scalars(
            select(Shipment)
            .where(Shipment.customer_id == customer.id)
            .order_by(Shipment.created_at.desc())
        )
    )


def shipment_history(session: Session, shipment: Shipment) -> list[StatusEvent]:
    return list(
        session.scalars(
            select(StatusEvent)
            .where(StatusEvent.shipment_id == shipment.id)
            .order_by(StatusEvent.created_at, StatusEvent.id)
        )
    )


def stats(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Shipment.status, func.count(Shipment.id)).group_by(Shipment.status)
    ).all()
    by_status = {status: count for status, count in rows}
    return {
        "total": sum(by_status.values()),
        "active": sum(
            count
            for status, count in by_status.items()
            if status is not ShipmentStatus.DELIVERED
            and status is not ShipmentStatus.CANCELLED
        ),
        "delivered": by_status.get(ShipmentStatus.DELIVERED, 0),
        "cancelled": by_status.get(ShipmentStatus.CANCELLED, 0),
        "new": by_status.get(ShipmentStatus.NEW, 0),
    }


def revenue(session: Session) -> float:
    """Sum of prices for delivered shipments only."""
    return float(
        session.scalar(
            select(func.coalesce(func.sum(Shipment.price), 0.0)).where(
                Shipment.status == ShipmentStatus.DELIVERED
            )
        )
        or 0.0
    )


def progress_text(shipment: Shipment) -> str:
    steps = [
        (ShipmentStatus.NEW, "Created"),
        (ShipmentStatus.ASSIGNED, "Driver assigned"),
        (ShipmentStatus.PICKED_UP, "Picked up"),
        (ShipmentStatus.IN_TRANSIT, "In transit"),
        (ShipmentStatus.DELIVERED, "Delivered"),
    ]
    if shipment.status is ShipmentStatus.CANCELLED:
        return "Cancelled"
    done = next(
        (i for i, (s, _) in enumerate(steps) if s is shipment.status), 0
    )
    return " > ".join(
        f"{'OK' if i <= done else '--'} {label}" for i, (_, label) in enumerate(steps)
    )


def get_shipment(session: Session, code: str) -> Shipment:
    """Look up a shipment by its ticket code. Raises ShipmentNotFound."""
    return _load_by_code(session, code)


def _load_by_code(session: Session, code: str) -> Shipment:
    shipment = session.scalar(
        select(Shipment).where(Shipment.code == code.strip().upper())
    )
    if shipment is None:
        raise ShipmentNotFound(code)
    return shipment