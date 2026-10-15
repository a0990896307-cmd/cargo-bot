"""Telegram handlers. Thin wrappers over cargo_bot.services."""
from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .config import settings
from .keyboards import (
    cancel_kb,
    driver_menu,
    main_menu,
    shipment_actions_kb,
    track_kb,
)
from .models import Shipment, ShipmentStatus
from .render import progress_card, shipment_card, shipment_summary, stats_card
from .services import (
    InvalidTransition,
    ServiceError,
    ShipmentNotFound,
    get_shipment,
    advance,
    assign_driver,
    available_shipments,
    cancel,
    customer_shipments,
    driver_shipments,
    get_or_create_customer,
    register_driver,
    revenue,
    shipment_history,
    stats,
)

router = Router()


class ShipmentForm(StatesGroup):
    pickup = State()
    dropoff = State()
    cargo_type = State()
    weight = State()
    price = State()


def _price_for(weight_kg: float) -> float:
    """Flat demo tariff: 3.0 per kg, minimum 10."""
    return max(10.0, round(weight_kg * 3.0, 2))


async def _notify_customer(bot: Bot, shipment: Shipment, text: str) -> None:
    if shipment.customer is None:
        return
    try:
        await bot.send_message(shipment.customer.telegram_id, text, parse_mode="HTML")
    except Exception:  # noqa: BLE001 - a dead customer must not break the flow
        pass


# ---------------------------------------------------------------- customer


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Cargo bot\n\n"
        "Book a shipment, track its status, or take jobs as a driver.",
        reply_markup=main_menu(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled.", reply_markup=main_menu())


@router.message(F.text == "New shipment")
async def new_shipment(message: Message, state: FSMContext) -> None:
    await state.set_state(ShipmentForm.pickup)
    await message.answer("Pickup address?", reply_markup=cancel_kb())


@router.message(ShipmentForm.pickup)
async def form_pickup(message: Message, state: FSMContext) -> None:
    await state.update_data(pickup=message.text)
    await state.set_state(ShipmentForm.dropoff)
    await message.answer("Dropoff address?")


@router.message(ShipmentForm.dropoff)
async def form_dropoff(message: Message, state: FSMContext) -> None:
    await state.update_data(dropoff=message.text)
    await state.set_state(ShipmentForm.cargo_type)
    await message.answer("Cargo type? (e.g. boxes, furniture)")


@router.message(ShipmentForm.cargo_type)
async def form_cargo(message: Message, state: FSMContext) -> None:
    await state.update_data(cargo_type=message.text)
    await state.set_state(ShipmentForm.weight)
    await message.answer("Weight in kg? (number only)")


@router.message(ShipmentForm.weight)
async def form_weight(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        weight = float(raw)
    except ValueError:
        await message.answer("That is not a number. Weight in kg?")
        return
    data = await state.get_data()
    await state.update_data(weight=weight, price=_price_for(weight))
    await state.set_state(ShipmentForm.price)
    await message.answer(
        f"Weight {weight:g} kg. Auto price: {settings.currency}{_price_for(weight):g}\n"
        "Send a custom price, or type <code>ok</code> to accept."
    )


@router.message(ShipmentForm.price)
async def form_price(message: Message, state: FSMContext, session) -> None:
    data = await state.get_data()
    raw = (message.text or "").strip().lower()
    if raw != "ok":
        try:
            data["price"] = float(raw.replace(",", "."))
        except ValueError:
            await message.answer("Send a number or <code>ok</code>.")
            return

    await state.clear()
    customer = get_or_create_customer(session, message.from_user.id, message.from_user.full_name)
    try:
        shipment = create_from_payload(session, customer, data)
    except ServiceError as exc:
        await message.answer(f"Cannot book: {exc}", reply_markup=main_menu())
        return

    await message.answer(
        "Shipment booked:\n\n" + shipment_card(shipment), reply_markup=track_kb(shipment.code)
    )
    await broadcast_new_shipment(message.bot, session, shipment)


def create_from_payload(session, customer, data):
    from .services import create_shipment

    return create_shipment(
        session,
        customer,
        pickup=data["pickup"],
        dropoff=data["dropoff"],
        cargo_type=data["cargo_type"],
        weight_kg=data["weight"],
        price=data["price"],
        max_weight_kg=settings.max_weight_kg,
    )


async def broadcast_new_shipment(bot: Bot, session, shipment: Shipment) -> None:
    """Ping active drivers about an open job."""
    from sqlalchemy import select

    from .models import Driver

    drivers = session.scalars(select(Driver).where(Driver.is_active.is_(True))).all()
    if not drivers:
        return
    text = f"<b>New job available</b>\n\n{shipment_summary(shipment)}"
    for driver in drivers:
        try:
            await bot.send_message(driver.telegram_id, text, parse_mode="HTML")
        except Exception:  # noqa: BLE001
            continue


@router.message(F.text == "My shipments")
async def my_shipments(message: Message, session) -> None:
    customer = get_or_create_customer(session, message.from_user.id, message.from_user.full_name)
    rows = customer_shipments(session, customer)
    if not rows:
        await message.answer("No shipments yet.", reply_markup=main_menu())
        return
    await message.answer(
        "Your shipments:\n\n" + "\n".join(shipment_summary(s) for s in rows),
        reply_markup=main_menu(),
    )


@router.message(F.text == "Track")
async def track_prompt(message: Message) -> None:
    await message.answer("Send the ticket code, e.g. CRG-ABCD")


@router.message(F.text.regexp(r"^[A-Za-z]{3}-[A-Za-z0-9]{4}$"))
async def track_code(message: Message, session) -> None:
    code = message.text.strip().upper()
    try:
        shipment = get_shipment(session, code)
    except ShipmentNotFound:
        await message.answer(f"No shipment with code {code}.")
        return
    await message.answer(progress_card(shipment), reply_markup=track_kb(shipment.code))


@router.callback_query(F.data.startswith("track:"))
async def track_refresh(callback: CallbackQuery, session) -> None:
    code = callback.data.split(":", 1)[1]
    try:
        shipment = get_shipment(session, code)
    except ShipmentNotFound:
        await callback.answer("Not found", show_alert=True)
        return
    await callback.message.edit_text(
        progress_card(shipment), parse_mode="HTML", reply_markup=track_kb(code)
    )
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cancel_form(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Cancelled.", reply_markup=main_menu())
    await callback.answer()


# ------------------------------------------------------------------ driver


@router.message(F.text == "Become a driver")
async def driver_signup(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Driver registration.\nSend: <name> | <phone>\nexample: Sam | +380501112233",
        reply_markup=cancel_kb(),
    )


@router.message(F.text.contains("|"))
async def driver_register(message: Message, session) -> None:
    name, _, phone = (message.text or "").partition("|")
    if not phone.strip():
        await message.answer("Use the format: <name> | <phone>")
        return
    try:
        register_driver(session, message.from_user.id, name.strip(), phone.strip())
    except ServiceError as exc:
        await message.answer(f"Cannot register: {exc}")
        return
    await message.answer("You are registered as a driver.", reply_markup=driver_menu())


@router.message(F.text == "Available jobs")
async def jobs(message: Message, session) -> None:
    rows = available_shipments(session)
    if not rows:
        await message.answer("No open jobs right now.", reply_markup=driver_menu())
        return
    await message.answer(
        "Open jobs:\n\n" + "\n\n".join(shipment_summary(s) for s in rows),
        parse_mode="HTML",
        reply_markup=driver_menu(),
    )


@router.message(F.text == "My jobs")
async def my_jobs(message: Message, session) -> None:
    from sqlalchemy import select

    from .models import Driver

    driver = session.scalar(select(Driver).where(Driver.telegram_id == message.from_user.id))
    if driver is None:
        await message.answer("Register first: send <name> | <phone>")
        return
    rows = driver_shipments(session, driver)
    if not rows:
        await message.answer("No jobs assigned yet.", reply_markup=driver_menu())
        return
    lines = []
    for shipment in rows:
        lines.append(shipment_card(shipment))
    await message.answer("\n\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data.startswith("move:"))
async def driver_move(callback: CallbackQuery, session) -> None:
    from sqlalchemy import select

    from .models import Driver

    _, code, target_value = callback.data.split(":", 2)
    target = ShipmentStatus(target_value)
    driver = session.scalar(
        select(Driver).where(Driver.telegram_id == callback.from_user.id)
    )
    if driver is None:
        await callback.answer("Register as a driver first", show_alert=True)
        return

    try:
        shipment = advance(session, code, target, actor_id=driver.telegram_id)
    except (ServiceError, InvalidTransition) as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await _notify_customer(
        callback.bot,
        shipment,
        f"Update for <b>{shipment.code}</b>:\n{progress_card(shipment)}",
    )
    await callback.message.edit_text(
        shipment_card(shipment),
        parse_mode="HTML",
        reply_markup=shipment_actions_kb(shipment.code, shipment.status),
    )
    await callback.answer("Updated")


@router.callback_query(F.data.startswith("cancel:"))
async def driver_cancel(callback: CallbackQuery, session) -> None:
    code = callback.data.split(":", 1)[1]
    try:
        shipment = cancel(session, code, actor_id=callback.from_user.id)
    except ServiceError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await _notify_customer(callback.bot, shipment, f"<b>{shipment.code}</b> was cancelled.")
    await callback.message.edit_text(shipment_card(shipment), parse_mode="HTML")
    await callback.answer("Cancelled")


# ------------------------------------------------------------------- admin


@router.message(Command("admin_stats"), Command("stats"))
async def admin_stats(message: Message, session) -> None:
    if not settings.is_admin(message.from_user.id):
        await message.answer("Admins only.")
        return
    await message.answer(
        stats_card(stats(session), revenue(session)), parse_mode="HTML"
    )


def build_dispatcher(session_middleware) -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    dp.update.middleware(session_middleware)
    return dp