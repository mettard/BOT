"""Order handling router with FSM flow."""

import logging
from datetime import datetime
from typing import Any

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import OrderCRUD, UserCRUD
from bot.keyboards.inline import get_confirmation_keyboard, get_menu_keyboard
from bot.services.google_sheets import get_sheets_service
from bot.services.notifications import AdminNotificationService
from bot.services.validators import (
    generate_order_number,
    normalize_phone,
    parse_time_input,
    validate_phone,
    validate_pickup_time,
)
from bot.states.order import OrderFSM

logger = logging.getLogger(__name__)
router = Router()

# Message templates
MESSAGES = {
    "menu": (
        "☕ <b>Меню CoffeeRun</b>\n\n"
        "Обери свій улюблений напій:\n\n"
        "{menu_items}"
    ),
    "time_prompt": (
        "⏰ <b>Коли ти забираш замовлення?</b>\n\n"
        "Введи час на зразок: <code>10 хв</code> або <code>15:30</code>"
    ),
    "phone_prompt": (
        "📱 <b>Вкажи свій телефон</b>\n\n"
        "Формат: <code>+380xxxxxxxxx</code> або <code>0xxxxxxxxx</code>"
    ),
    "confirmation": (
        "✅ <b>Підтвердження замовлення</b>\n\n"
        "☕ Напій: <b>{drink_name}</b> ({volume}ml)\n"
        "💰 Ціна: <b>₴{price}</b>\n"
        "⏰ Час забору: <b>{pickup_time}</b>\n\n"
        "Се правильно? Натисни <b>Підтвердити</b>"
    ),
    "success": (
        "✅ <b>Замовлення підтверджено!</b>\n\n"
        "Твій номер замовлення: <b>{order_id}</b>\n"
        "⏰ Час забору: <b>{pickup_time}</b>\n\n"
        "Дякуємо! 🎉"
    ),
    "cancelled": "❌ Замовлення скасовано.\n\nМожеш зробити нове замовлення, натисни /start",
    "invalid_time": (
        "❌ <b>Неправильний час.</b>\n\n"
        "Введи як: <code>10 хв</code>, <code>20 хв</code> або <code>15:30</code>\n\n"
        "⏰ Кав'ярня працює: 09:00–21:00\n"
        "Макс. упередження: 12 годин"
    ),
    "time_in_past": "❌ Цей час вже пройшов. Виберіть майбутній час.",
    "time_outside_hours": "❌ Кав'ярня працює лише 09:00–21:00. Виберіть час у межах роботи.",
    "time_too_far": "❌ Максимальне упередження — 12 годин. Виберіть раніший час.",
    "invalid_phone": (
        "❌ <b>Неправильний формат номера.</b>\n\n"
        "Приклади коректних номерів:\n"
        "• <code>+380501234567</code>\n"
        "• <code>380501234567</code>\n"
        "• <code>0501234567</code>"
    ),
    "menu_empty": (
        "⚠️ <b>Меню на даний момент недоступне.</b>\n\n"
        "Спробуй пізніше або зв'яжись з кав'ярнею."
    ),
}


@router.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Handle /start command - display menu."""
    logger.info(f"User {message.from_user.id} started bot")

    try:
        # Get or create user
        await UserCRUD.get_or_create(
            session=session,
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )

        # Fetch menu from Google Sheets
        sheets_service = await get_sheets_service()
        menu = await sheets_service.get_menu()

        if not menu:
            await message.answer(MESSAGES["menu_empty"], parse_mode="HTML")
            return

        # Формуємо красивий текстовий рядок для меню
        menu_items_text = ""
        for item in menu:
            menu_items_text += f"☕️ <b>{item['name']}</b> {item['volume']}ml — {item['price']} ₴\n"
        # Build keyboard
        keyboard = get_menu_keyboard(menu)

        # Send menu message
        await message.answer(
            MESSAGES["menu"].format(menu_items=menu_items_text),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        # Store menu in context for later access
        await state.update_data(menu=menu)
        await state.set_state(OrderFSM.menu_selection)

    except Exception as e:
        logger.error(f"Error in start_handler: {e}")
        await message.answer("⚠️ Технічна помилка. Спробуй ще раз за хвилину.", parse_mode="HTML")


@router.callback_query(OrderFSM.menu_selection, F.data.startswith("drink_"))
async def drink_selected_handler(
    query: types.CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Handle drink selection."""
    logger.info(f"User {query.from_user.id} selected drink")

    try:
        # Get menu from context
        data = await state.get_data()
        menu = data.get("menu", [])

        # Parse drink index
        drink_idx = int(query.data.split("_")[1])
        if drink_idx >= len(menu):
            await query.answer("❌ Напій не знайдений", show_alert=True)
            return

        drink = menu[drink_idx]

        # Store drink in context
        await state.update_data(selected_drink=drink)

        # Acknowledge callback
        await query.answer()

        # Ask for time
        await query.message.answer(MESSAGES["time_prompt"], parse_mode="HTML")
        await state.set_state(OrderFSM.time_input)

    except Exception as e:
        logger.error(f"Error in drink_selected_handler: {e}")
        await query.answer("❌ Помилка при виборі напою", show_alert=True)


@router.message(OrderFSM.time_input)
async def time_input_handler(message: types.Message, state: FSMContext) -> None:
    """Handle time input."""
    logger.info(f"User {message.from_user.id} entered time: {message.text}")

    try:
        # Parse time input
        pickup_time = parse_time_input(message.text)
        if pickup_time is None:
            await message.answer(MESSAGES["invalid_time"], parse_mode="HTML")
            return

        # Validate time
        is_valid, error_key = validate_pickup_time(pickup_time)
        if not is_valid:
            error_msg = {
                "MSG_103": MESSAGES["time_in_past"],
                "MSG_104": MESSAGES["time_outside_hours"],
                "MSG_105": MESSAGES["time_too_far"],
            }.get(error_key, MESSAGES["invalid_time"])

            await message.answer(error_msg, parse_mode="HTML")
            return

        # Store time in context
        await state.update_data(pickup_time=pickup_time)

        # Ask for phone
        await message.answer(MESSAGES["phone_prompt"], parse_mode="HTML")
        await state.set_state(OrderFSM.phone_input)

    except Exception as e:
        logger.error(f"Error in time_input_handler: {e}")
        await message.answer(MESSAGES["invalid_time"], parse_mode="HTML")


@router.message(OrderFSM.phone_input)
async def phone_input_handler(message: types.Message, state: FSMContext) -> None:
    """Handle phone input."""
    logger.info(f"User {message.from_user.id} entered phone")

    try:
        phone = message.text.strip()

        # Validate phone
        if not validate_phone(phone):
            await message.answer(MESSAGES["invalid_phone"], parse_mode="HTML")
            return

        # Normalize phone
        normalized_phone = normalize_phone(phone)

        # Store phone in context
        await state.update_data(phone=normalized_phone)

        # Get data and prepare confirmation
        data = await state.get_data()
        drink = data.get("selected_drink", {})
        pickup_time = data.get("pickup_time")

        pickup_time_str = pickup_time.strftime("%d.%m.%Y %H:%M") if pickup_time else "—"

        # Show confirmation
        confirmation_text = MESSAGES["confirmation"].format(
            drink_name=drink.get("name", "—"),
            volume=drink.get("volume", "—"),
            price=drink.get("price", "—"),
            pickup_time=pickup_time_str,
        )

        keyboard = get_confirmation_keyboard()
        await message.answer(confirmation_text, parse_mode="HTML", reply_markup=keyboard)

        await state.set_state(OrderFSM.confirmation)

    except Exception as e:
        logger.error(f"Error in phone_input_handler: {e}")
        await message.answer(MESSAGES["invalid_phone"], parse_mode="HTML")


@router.callback_query(OrderFSM.confirmation, F.data == "confirm_order")
async def confirm_order_handler(
    query: types.CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Handle order confirmation."""
    logger.info(f"User {query.from_user.id} confirmed order")

    try:
        # Get data
        data = await state.get_data()
        drink = data.get("selected_drink", {})
        pickup_time = data.get("pickup_time")
        phone = data.get("phone")

        # Generate order number
        order_number = generate_order_number()

        # Create order in DB
        order = await OrderCRUD.create(
            session=session,
            order_number=order_number,
            telegram_id=query.from_user.id,
            customer_name=query.from_user.first_name,
            phone=phone,
            drink_name=drink.get("name", "Unknown"),
            volume_ml=drink.get("volume", 0),
            price=drink.get("price", 0),
            pickup_time=pickup_time,
        )

        # Send to Google Sheets
        sheets_service = await get_sheets_service()
        pickup_time_str = pickup_time.isoformat() if pickup_time else ""
        await sheets_service.append_order(
            order_number=order_number,
            customer_name=query.from_user.first_name,
            phone=phone,
            drink_name=drink.get("name", "Unknown"),
            price=drink.get("price", 0),
            pickup_time=pickup_time_str,
            status="New",
        )

        # Send notification to admin
        from aiogram import Bot
        from bot.config import settings

        bot = Bot(token=settings.bot_token)
        notification_service = AdminNotificationService(bot)

        await notification_service.send_order_notification(
            order_number=order_number,
            customer_name=query.from_user.first_name,
            phone=phone,
            drink_name=drink.get("name", "Unknown"),
            volume_ml=drink.get("volume", 0),
            price=drink.get("price", 0),
            pickup_time=pickup_time,
        )

        # Show success message
        pickup_time_str_display = pickup_time.strftime("%d.%m.%Y %H:%M") if pickup_time else "—"
        success_text = MESSAGES["success"].format(
            order_id=order_number,
            pickup_time=pickup_time_str_display,
        )

        await query.answer()
        await query.message.answer(success_text, parse_mode="HTML")

        # Clear FSM
        await state.clear()

        logger.info(f"Order {order_number} created successfully")

    except Exception as e:
        logger.error(f"Error in confirm_order_handler: {e}")
        await query.answer("❌ Помилка при збереженні замовлення", show_alert=True)


@router.callback_query(F.data.in_(["cancel_order", "cancel_flow"]))
@router.callback_query(OrderFSM.menu_selection, F.data == "cancel_order")
@router.callback_query(OrderFSM.time_input, F.data == "cancel_order")
@router.callback_query(OrderFSM.phone_input, F.data == "cancel_order")
@router.callback_query(OrderFSM.confirmation, F.data == "cancel_order")
@router.message(Command("cancel"))
async def cancel_handler(message_or_query: types.Message | types.CallbackQuery, state: FSMContext) -> None:
    """Handle cancellation from any state."""
    logger.info(f"User cancelled order flow")

    try:
        await state.clear()

        if isinstance(message_or_query, types.CallbackQuery):
            query = message_or_query
            await query.answer()
            await query.message.answer(MESSAGES["cancelled"], parse_mode="HTML")
        else:
            message = message_or_query
            await message.answer(MESSAGES["cancelled"], parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in cancel_handler: {e}")
