"""Keyboard builders."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from .models import ShipmentStatus

#: Actions a driver may perform from the given state.
DRIVER_ACTIONS: dict[ShipmentStatus, tuple[ShipmentStatus, ...]] = {
    ShipmentStatus.ASSIGNED: (ShipmentStatus.PICKED_UP,),
    ShipmentStatus.PICKED_UP: (ShipmentStatus.IN_TRANSIT,),
    ShipmentStatus.IN_TRANSIT: (ShipmentStatus.DELIVERED,),
}

ACTION_LABELS = {
    ShipmentStatus.PICKED_UP: "Cargo picked up",
    ShipmentStatus.IN_TRANSIT: "Start delivery",
    ShipmentStatus.DELIVERED: "Mark delivered",
}


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="New shipment")],
            [KeyboardButton(text="My shipments"), KeyboardButton(text="Track")],
            [KeyboardButton(text="Become a driver")],
        ],
        resize_keyboard=True,
    )


def driver_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Available jobs")],
            [KeyboardButton(text="My jobs"), KeyboardButton(text="Track")],
        ],
        resize_keyboard=True,
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Cancel", callback_data="cancel")]]
    )


def track_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Refresh status", callback_data=f"track:{code}")]
        ]
    )


def shipment_actions_kb(code: str, status: ShipmentStatus) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=ACTION_LABELS[target], callback_data=f"move:{code}:{target.value}"
            )
        ]
        for target in DRIVER_ACTIONS.get(status, ())
    ]
    if rows and not status.is_terminal:
        rows.append(
            [InlineKeyboardButton(text="Cancel shipment", callback_data=f"cancel:{code}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else InlineKeyboardMarkup(
        inline_keyboard=[]
    )