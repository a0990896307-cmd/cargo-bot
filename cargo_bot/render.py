"""Shared rendering helpers: one place formats a shipment for any audience."""
from __future__ import annotations

from .config import Settings, settings as default_settings
from .models import Shipment, ShipmentStatus
from .services import progress_text

_STATUS_TEXT = {
    ShipmentStatus.NEW: "waiting for a driver",
    ShipmentStatus.ASSIGNED: "driver assigned",
    ShipmentStatus.PICKED_UP: "picked up",
    ShipmentStatus.IN_TRANSIT: "on the way",
    ShipmentStatus.DELIVERED: "delivered",
    ShipmentStatus.CANCELLED: "cancelled",
}


def shipment_card(shipment: Shipment, settings: Settings = default_settings) -> str:
    cur = settings.currency
    return (
        f"<b>{shipment.code}</b>\n"
        f"Status: {_STATUS_TEXT[shipment.status]}\n"
        f"From: {shipment.pickup}\n"
        f"To: {shipment.dropoff}\n"
        f"Cargo: {shipment.cargo_type}, {shipment.weight_kg:g} kg\n"
        f"Price: {cur}{shipment.price:g}"
    )


def progress_card(shipment: Shipment, settings: Settings = default_settings) -> str:
    return (
        f"<b>{shipment.code}</b>\n\n"
        f"{progress_text(shipment)}\n\n"
        f"From: {shipment.pickup}\n"
        f"To: {shipment.dropoff}"
    )


def shipment_summary(shipment: Shipment, settings: Settings = default_settings) -> str:
    cur = settings.currency
    return (
        f"{shipment.code} — {shipment.pickup} -> {shipment.dropoff}\n"
        f"   {shipment.cargo_type}, {shipment.weight_kg:g} kg, {cur}{shipment.price:g} "
        f"({shipment.status.value})"
    )


def stats_card(data: dict[str, int], revenue_value: float, settings: Settings = default_settings) -> str:
    return (
        "<b>Statistics</b>\n"
        f"Total: {data['total']}\n"
        f"Active: {data['active']}\n"
        f"Awaiting driver: {data['new']}\n"
        f"Delivered: {data['delivered']}\n"
        f"Cancelled: {data['cancelled']}\n"
        f"Revenue: {settings.currency}{revenue_value:g}"
    )