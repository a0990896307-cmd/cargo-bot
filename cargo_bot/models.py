"""SQLAlchemy models for customers, drivers and shipments."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ShipmentStatus(str, enum.Enum):
    """Lifecycle of a shipment.

    Transitions are enforced in services.py; the enum order below also
    defines the progress bar shown to the customer.
    """

    NEW = "new"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED)


#: Allowed forward moves. Cancelling is allowed from any non-terminal state.
ALLOWED_TRANSITIONS: dict[ShipmentStatus, frozenset[ShipmentStatus]] = {
    ShipmentStatus.NEW: frozenset(
        {ShipmentStatus.ASSIGNED, ShipmentStatus.CANCELLED}
    ),
    ShipmentStatus.ASSIGNED: frozenset(
        {ShipmentStatus.PICKED_UP, ShipmentStatus.CANCELLED}
    ),
    ShipmentStatus.PICKED_UP: frozenset(
        {ShipmentStatus.IN_TRANSIT, ShipmentStatus.CANCELLED}
    ),
    ShipmentStatus.IN_TRANSIT: frozenset(
        {ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED}
    ),
    ShipmentStatus.DELIVERED: frozenset(),
    ShipmentStatus.CANCELLED: frozenset(),
}


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    shipments: Mapped[list["Shipment"]] = relationship(back_populates="customer")


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    shipments: Mapped[list["Shipment"]] = relationship(back_populates="driver")


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Short human-facing ticket code, e.g. "CRG-4821".
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), nullable=True)

    pickup: Mapped[str] = mapped_column(String(255))
    dropoff: Mapped[str] = mapped_column(String(255))
    cargo_type: Mapped[str] = mapped_column(String(80))
    weight_kg: Mapped[float] = mapped_column(Float)

    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(ShipmentStatus, native_enum=False),
        default=ShipmentStatus.NEW,
        index=True,
    )
    price: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="shipments")
    driver: Mapped[Driver | None] = relationship(back_populates="shipments")

    __table_args__ = (
        CheckConstraint("weight_kg > 0", name="ck_shipments_weight_positive"),
    )


class StatusEvent(Base):
    """Append-only audit trail; one row per status change."""

    __tablename__ = "status_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), index=True)
    from_status: Mapped[ShipmentStatus | None] = mapped_column(
        Enum(ShipmentStatus, native_enum=False), nullable=True
    )
    to_status: Mapped[ShipmentStatus] = mapped_column(Enum(ShipmentStatus, native_enum=False))
    actor_id: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, server_default=func.now())


def build_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


def build_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)