"""Order handling router with FSM flow."""

import logging
from datetime import datetime, time
from typing import Any

from aiogram import Bot, F, Router, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram.types import ReplyKeyboardRemove
from datetime import timedelta

from bot.database.crud import OrderCRUD, SystemSettingCRUD, UserCRUD, WaitlistCRUD
from bot.keyboards.inline import (
    get_confirmation_keyboard, 
    get_menu_keyboard, 
    get_back_to_menu_keyboard, 
    get_back_to_time_keyboard,
    get_notes_keyboard,  # Додано нову клавіатуру
    get_time_keyboard,          # ДОДАЛИ
    get_phone_reply_keyboard,
    get_new_order_reply_keyboard,
    get_view_menu_reply_keyboard,
    FavoriteOrderCallback,
)
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
        "⏰ <b>Коли ти забиреш замовлення?</b>\n\n"
        "Введи час на зразок: <code>10 хв</code> або <code>15:30</code>"
    ),
    "phone_prompt": (
        "📱 <b>Вкажи свій телефон</b>\n\n"
        "Формат: <code>+380xxxxxxxxx</code> або <code>0xxxxxxxxx</code>"
    ),
    "notes_prompt": (
        "📝 <b>Чи є побажання до замовлення?</b>\n\n"
        "Наприклад: <i>без цукру</i>, <i>більше льоду</i>, <i>на безлактозному</i>.\n\n"
        "Напиши їх сюди або натисни «Пропустити»."
    ),
    "confirmation": (
        "✅ <b>Підтвердження замовлення</b>\n\n"
        "☕ Напій: <b>{drink_name}</b> ({volume}ml)\n"
        "💰 Ціна: <b>₴{price}</b>\n"
        "⏰ Час забору: <b>{pickup_time}</b>\n\n"
        "{notes_text}"
        "Усе правильно? Натисни <b>Підтвердити</b>"
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
        "Макс. упередження: 12 годин"
    ),
    "time_in_past": "❌ Цей час вже пройшов. Виберіть майбутній час.",
    "time_outside_hours": "❌ Кав'ярня зачинена у цей час. Ми працюємо з {open_time} до {close_time}.",
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
    "closed_retry": (
        "⏸ <b>Кав'ярня зараз зачинена.</b>\n\n"
        "Кнопка внизу залишилась, тож ти зможеш повернутись до меню, коли ми відкриємось."
    ),
    "orders_paused": (
        "⏸ <b>Прийом онлайн-замовлень тимчасово призупинено кав'ярнею.</b>\n\n"
        "Бариста розбирається з поточними замовленнями або оновлює інгредієнти.\n\n"
        "🔔 <b>Ми одразу сповістимо вас сюди, як тільки відновимо прийом!</b> ☕"
    ),
}

ACTIVE_STATUS_TERMS = (
    "готово",
    "готовий",
    "done",
    "completed",
    "cancel",
    "canceled",
    "cancelled",
    "скасовано",
    "відмінено",
    "завершено",
)


def _format_menu_items(menu: list[dict[str, Any]]) -> str:
    """Render menu items with optional descriptions."""
    menu_items_text = ""
    for item in menu:
        menu_items_text += f"☕️ <b>{item['name']}</b> {item['volume']}ml — {item['price']} ₴\n"
        description = (item.get("description") or "").strip()
        if description:
            menu_items_text += f"<i>{description}</i>\n"
        menu_items_text += "\n"
    return menu_items_text.rstrip()


def _format_closed_notice(open_time: str, close_time: str) -> str:
    return (
        f"⏸ <b>На жаль, кав'ярня зараз зачинена.</b>\n\n"
        f"Ми приймаємо замовлення лише в робочий час з <code>{open_time}</code> до <code>{close_time}</code>.\n"
        f"Завітайте до нас пізніше! ☕️"
    )


def _normalize_status_text(status_text: str | None) -> str:
    return (status_text or "").strip().lower()


def _is_active_order_status(status_text: str | None) -> bool:
    normalized_status = _normalize_status_text(status_text)
    if not normalized_status:
        return False
    return not any(term in normalized_status for term in ACTIVE_STATUS_TERMS)


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _is_current_favorite(user: Any, drink: dict[str, Any], phone: str, notes: str) -> bool:
    return (
        _normalize_text(getattr(user, "favorite_drink_name", None)) == _normalize_text(drink.get("name"))
        and int(getattr(user, "favorite_volume_ml", 0) or 0) == int(drink.get("volume", 0) or 0)
        and float(getattr(user, "favorite_price", 0) or 0) == float(drink.get("price", 0) or 0)
        and _normalize_text(getattr(user, "favorite_phone", None)) == _normalize_text(phone)
        and _normalize_text(getattr(user, "favorite_notes", None)) == _normalize_text(notes)
    )


def _format_active_order_notice(order_number: str, status_text: str | None) -> str:
    status_display = status_text or "в роботі"
    return (
        f"⏳ <b>У тебе вже є активне замовлення #{order_number}</b>\n\n"
        f"Поточний статус: <b>{status_display}</b>\n\n"
        f"Почекай, будь ласка, поки кава буде готова."
    )


async def _clear_warning(event: types.Message | types.CallbackQuery, state: FSMContext) -> None:
    """Видаляє попередження 'Ти вже в процесі', якщо користувач продовжує замовлення."""
    data = await state.get_data()
    warning_msg_id = data.get("warning_msg_id")
    if warning_msg_id:
        try:
            chat_id = event.from_user.id
            await event.bot.delete_message(chat_id=chat_id, message_id=warning_msg_id)
        except Exception:
            pass
        await state.update_data(warning_msg_id=None)


async def _get_latest_order_state(session: AsyncSession, telegram_id: int) -> tuple[Any | None, str | None]:
    recent_orders = await OrderCRUD.get_by_telegram_id_recent(session=session, telegram_id=telegram_id, limit=1)
    if not recent_orders:
        return None, None

    order = recent_orders[0]
    order_status = order.status

    try:
        sheets_service = await get_sheets_service()
        sheet_status = await sheets_service.get_order_status(order.order_number)
        if sheet_status:
            order_status = sheet_status
    except Exception as status_err:
        logger.error(f"Error resolving latest order status: {status_err}")

    return order, order_status


async def _get_active_order_state(session: AsyncSession, telegram_id: int) -> tuple[Any | None, str | None]:
    order, order_status = await _get_latest_order_state(session=session, telegram_id=telegram_id)
    if order is None or not _is_active_order_status(order_status):
        return None, None
    return order, order_status


async def _send_menu(
    message: types.Message,
    state: FSMContext,
    session: AsyncSession,
    favorite_drink_name: str | None = None,
    remove_reply_keyboard: bool = False,
) -> None:
    """Load and show the main menu, then switch FSM to menu selection."""
    if await SystemSettingCRUD.is_orders_paused(session):
        await WaitlistCRUD.add_to_waitlist(session, message.from_user.id)
        await message.answer(MESSAGES["orders_paused"], parse_mode="HTML")
        await state.clear()
        return

    sheets_service = await get_sheets_service()
    menu = await sheets_service.get_menu()

    if not menu:
        await message.answer(MESSAGES["menu_empty"], parse_mode="HTML")
        return

    menu_items_text = _format_menu_items(menu)

    if remove_reply_keyboard:
        remove_msg = await message.answer("🔄", reply_markup=ReplyKeyboardRemove())
        await remove_msg.delete()

    await message.answer(
        MESSAGES["menu"].format(menu_items=menu_items_text),
        parse_mode="HTML",
        reply_markup=get_menu_keyboard(menu, favorite_drink_name=favorite_drink_name),
    )

    await state.update_data(menu=menu)
    await state.set_state(OrderFSM.menu_selection)


@router.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Handle /start command - display menu."""
    logger.info(f"User {message.from_user.id} started bot")

    try:
       # ==========================================
        # 💥 ЗАХИСТ ВІД ДУБЛІВ МЕНЮ ТА ПЕРЕКРИТТЯ КРОКІВ
        current_state = await state.get_state()
        if current_state is not None:
            try:
                await message.delete()  # Очищаємо чат від зайвих команд
            except Exception:
                pass
                
            # Видаляємо старе попередження
            await _clear_warning(message, state)
            
            # Якщо ми на кроці телефону — примусово повертаємо нижню кнопку!
            markup = None
            if current_state == OrderFSM.phone_input.state:
                from bot.keyboards.inline import get_phone_reply_keyboard
                markup = get_phone_reply_keyboard()
                    
            # Відправляємо нове попередження вниз чату
            warning_msg = await message.answer(
                "⚠️ <b>Ти вже в процесі оформлення замовлення!</b>\n\n"
                "Продовж його вище або натисни команду /cancel, щоб скасувати його і відкрити меню заново.",
                parse_mode="HTML",
                reply_markup=markup
            )
            await state.update_data(warning_msg_id=warning_msg.message_id)
            return
        # ==========================================

        # Одразу фіксуємо стан FSM, щоб заблокувати будь-які паралельні дублі /start
        await state.set_state(OrderFSM.menu_selection)

        user = await UserCRUD.get_or_create(
            session=session,
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )

        active_order, active_status = await _get_active_order_state(session=session, telegram_id=message.from_user.id)
        if active_order is not None:
            await message.answer(
                _format_active_order_notice(active_order.order_number, active_status),
                parse_mode="HTML",
            )
            await state.clear()
            return

        await _send_menu(
            message,
            state,
            session,
            favorite_drink_name=user.favorite_drink_name,
        )

    except Exception as e:
        logger.error(f"Error in start_handler: {e}")
        await message.answer("⚠️ Технічна помилка. Спробуй ще раз за хвилину.", parse_mode="HTML")


@router.callback_query(F.data.in_(["cancel_order", "cancel_flow"]))
@router.callback_query(OrderFSM.menu_selection, F.data == "cancel_order")
@router.callback_query(OrderFSM.time_input, F.data == "cancel_order")
@router.callback_query(OrderFSM.phone_input, F.data == "cancel_order")
@router.callback_query(OrderFSM.notes_input, F.data == "cancel_order")
@router.callback_query(OrderFSM.confirmation, F.data == "cancel_order")
@router.message(Command("cancel"))
async def cancel_handler(message_or_query: types.Message | types.CallbackQuery, state: FSMContext) -> None:
    """Handle cancellation from any state."""
    logger.info("User cancelled order flow")

    try:
        await _clear_warning(message_or_query, state)
        data = await state.get_data()

        msg_ids_to_delete = set()
        for key in ("time_prompt_msg_id", "phone_prompt_msg_id", "notes_prompt_msg_id", "warning_msg_id"):
            val = data.get(key)
            if val:
                msg_ids_to_delete.add(val)

        bot = message_or_query.bot

        if isinstance(message_or_query, types.CallbackQuery):
            query = message_or_query
            await query.answer()
            chat_id = query.message.chat.id
            current_msg_id = query.message.message_id

            for msg_id in msg_ids_to_delete:
                if msg_id != current_msg_id:
                    try:
                        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                    except Exception:
                        pass

            try:
                await query.message.edit_text(MESSAGES["cancelled"], parse_mode="HTML", reply_markup=None)
            except Exception:
                await query.message.answer(MESSAGES["cancelled"], parse_mode="HTML")

            try:
                remove_msg = await query.message.answer("⏳", reply_markup=ReplyKeyboardRemove())
                await remove_msg.delete()
            except Exception:
                pass
        else:
            message = message_or_query
            chat_id = message.chat.id

            try:
                await message.delete()  # Видаляємо саму команду /cancel від користувача
            except Exception:
                pass

            for msg_id in msg_ids_to_delete:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass

            try:
                remove_msg = await message.answer("⏳", reply_markup=ReplyKeyboardRemove())
                await remove_msg.delete()
            except Exception:
                pass

            await message.answer(MESSAGES["cancelled"], parse_mode="HTML")

        await state.clear()

    except Exception as e:
        logger.error(f"Error in cancel_handler: {e}")
        await state.clear()


@router.callback_query(OrderFSM.menu_selection, F.data.startswith("drink_"))
async def drink_selected_handler(
    query: types.CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Handle drink selection with instant shop status check."""
    logger.info(f"User {query.from_user.id} selected drink")
    await _clear_warning(query, state)

    try:
        if await SystemSettingCRUD.is_orders_paused(session):
            await WaitlistCRUD.add_to_waitlist(session, query.from_user.id)
            await query.answer()
            try:
                await query.message.delete()
            except Exception:
                pass
            await query.message.answer(MESSAGES["orders_paused"], parse_mode="HTML")
            await state.clear()
            return

        active_order, active_status = await _get_active_order_state(session=session, telegram_id=query.from_user.id)
        if active_order is not None:
            await query.answer("⏳ У тебе вже є активне замовлення", show_alert=True)
            try:
                await query.message.edit_text(
                    _format_active_order_notice(active_order.order_number, active_status),
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except Exception:
                pass
            await state.clear()
            return

        sheets_service = await get_sheets_service()
        config = await sheets_service.get_business_config()
        
        open_time_str = config.get("CAFE_OPEN_TIME", "09:00")
        close_time_str = config.get("CAFE_CLOSE_TIME", "23:59")
        
        current_time = datetime.now().time()
        
        try:
            open_parts = open_time_str.split(":")
            close_parts = close_time_str.split(":")
            start_work = time(int(open_parts[0]), int(open_parts[1]))
            end_work = time(int(close_parts[0]), int(close_parts[1]))
            
            if not (start_work <= current_time <= end_work):
                nice_open = f"{start_work.hour:02d}:{start_work.minute:02d}"
                nice_close = f"{end_work.hour:02d}:{end_work.minute:02d}"
                closed_notice = _format_closed_notice(nice_open, nice_close)

                await query.answer()
                try:
                    await query.message.delete()
                except Exception:
                    pass
                await query.message.answer(closed_notice, parse_mode="HTML")
                await state.clear()
                return
        except Exception as parse_err:
            logger.error(f"Error parsing table times in instant check: {parse_err}")

        data = await state.get_data()
        menu = data.get("menu", [])

        drink_idx = int(query.data.split("_")[1])
        if drink_idx >= len(menu):
            await query.answer("❌ Напій не знайдений", show_alert=True)
            return

        drink = menu[drink_idx]
        await state.update_data(selected_drink=drink, time_prompt_msg_id=query.message.message_id)
        
        await query.answer()
        await query.message.edit_text(
            MESSAGES["time_prompt"], 
            parse_mode="HTML", 
            reply_markup=get_time_keyboard()
        )
        await state.set_state(OrderFSM.time_input)
    except Exception as e:
        logger.error(f"Error in drink_selected_handler: {e}")
        await query.answer("❌ Помилка при виборі напою", show_alert=True)


@router.callback_query(OrderFSM.time_input, F.data.startswith("quick_time:"))
async def quick_time_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _clear_warning(query, state)
    minutes = int(query.data.split(":")[1])
    pickup_time = datetime.now() + timedelta(minutes=minutes)
    
    await state.update_data(pickup_time=pickup_time)

    data = await state.get_data()
    if data.get("favorite_flow"):
        await _show_confirmation(query, state, session=session)
        await query.answer()
        return

    # Перевірка наявності телефону у БД (Автопропуск)
    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=query.from_user.id)
    if user and user.phone:
        await state.update_data(phone=user.phone, phone_autoskipped=True)
        await query.message.edit_text(MESSAGES["notes_prompt"], parse_mode="HTML", reply_markup=get_notes_keyboard())
        await state.update_data(notes_prompt_msg_id=query.message.message_id)
        await state.set_state(OrderFSM.notes_input)
        await query.answer()
        return

    await state.update_data(phone_autoskipped=False)
    await query.message.edit_text(MESSAGES["phone_prompt"], parse_mode="HTML", reply_markup=get_phone_reply_keyboard())
    await state.update_data(phone_prompt_msg_id=query.message.message_id)

    await state.set_state(OrderFSM.phone_input)
    await query.answer()

@router.message(OrderFSM.time_input, F.text, ~F.text.startswith("/"))
async def time_input_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Handle time input."""
    logger.info(f"User {message.from_user.id} entered time: {message.text}")
    pickup_time = None
    await _clear_warning(message, state)

    try:
        pickup_time = parse_time_input(message.text)
        if pickup_time is None:
            await message.answer(MESSAGES["invalid_time"], parse_mode="HTML")
            return

        sheets_service = await get_sheets_service()
        config = await sheets_service.get_business_config()
        
        open_time_str = config.get("CAFE_OPEN_TIME", "09:00")
        close_time_str = config.get("CAFE_CLOSE_TIME", "23:59")

        is_valid, error_key = validate_pickup_time(pickup_time)
        if not is_valid and error_key != "MSG_104":
            error_msg = {
                "MSG_103": MESSAGES["time_in_past"],
                "MSG_105": MESSAGES["time_too_far"],
            }.get(error_key, MESSAGES["invalid_time"])

            await message.answer(error_msg, parse_mode="HTML")
            return

        try:
            open_parts = open_time_str.split(":")
            close_parts = close_time_str.split(":")
            
            open_h, open_m = int(open_parts[0]), int(open_parts[1])
            close_h, close_m = int(close_parts[0]), int(close_parts[1])
            
            start_work = time(open_h, open_m)
            end_work = time(close_h, close_m)
            
            order_time = pickup_time.time()
            
            if not (start_work <= order_time <= end_work):
                nice_open = f"{open_h:02d}:{open_m:02d}"
                nice_close = f"{close_h:02d}:{close_m:02d}"
                
                await message.answer(
                    MESSAGES["time_outside_hours"].format(open_time=nice_open, close_time=nice_close),
                    parse_mode="HTML"
                )
                return
        except Exception as parse_err:
            logger.error(f"Error parsing table times ({open_time_str}/{close_time_str}): {parse_err}")

        data = await state.get_data()
        time_prompt_msg_id = data.get("time_prompt_msg_id")
        if time_prompt_msg_id:
            try:
                await message.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=time_prompt_msg_id,
                )
            except Exception as delete_err:
                logger.error(f"Failed to delete time keyboard: {delete_err}")

        favorite_flow = bool(data.get("favorite_flow", False))
        await state.update_data(pickup_time=pickup_time)

        if favorite_flow:
            await _show_confirmation(message, state, session=session, source_message_id=time_prompt_msg_id)
            return

        # Перевірка наявності телефону у БД (Автопропуск)
        user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=message.from_user.id)
        if user and user.phone:
            await state.update_data(phone=user.phone, phone_autoskipped=True)
            notes_prompt_msg = await message.answer(MESSAGES["notes_prompt"], parse_mode="HTML", reply_markup=get_notes_keyboard())
            await state.update_data(notes_prompt_msg_id=notes_prompt_msg.message_id)
            await state.set_state(OrderFSM.notes_input)
            return

        await state.update_data(phone_autoskipped=False)
        phone_prompt_msg = await message.answer(MESSAGES["phone_prompt"], parse_mode="HTML", reply_markup=get_phone_reply_keyboard())
        await state.update_data(phone_prompt_msg_id=phone_prompt_msg.message_id)

        await state.set_state(OrderFSM.phone_input)

    except Exception as e:
        logger.error(f"Error in time_input_handler: {e}")
        data = await state.get_data()
        favorite_flow = bool(data.get("favorite_flow", False))
        time_prompt_msg_id = data.get("time_prompt_msg_id")
        await state.update_data(pickup_time=pickup_time)

        if favorite_flow:
            await _show_confirmation(message, state, session=session, source_message_id=time_prompt_msg_id)
            return

        # Перевірка наявності телефону у БД при помилці
        user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=message.from_user.id)
        if user and user.phone:
            await state.update_data(phone=user.phone, phone_autoskipped=True)
            notes_prompt_msg = await message.answer(MESSAGES["notes_prompt"], parse_mode="HTML", reply_markup=get_notes_keyboard())
            await state.update_data(notes_prompt_msg_id=notes_prompt_msg.message_id)
            await state.set_state(OrderFSM.notes_input)
            return

        await state.update_data(phone_autoskipped=False)
        phone_prompt_msg = await message.answer(MESSAGES["phone_prompt"], parse_mode="HTML", reply_markup=get_phone_reply_keyboard())
        await state.update_data(phone_prompt_msg_id=phone_prompt_msg.message_id)
        
        await state.set_state(OrderFSM.phone_input)


@router.message(OrderFSM.phone_input, F.contact | (F.text & ~F.text.startswith("/")))
async def phone_input_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    logger.info(f"User {message.from_user.id} entered phone")
    await _clear_warning(message, state)
    try:
        if message.contact:
            phone = message.contact.phone_number
        else:
            phone = message.text.strip()

        if not validate_phone(phone):
            await message.answer(MESSAGES["invalid_phone"], parse_mode="HTML")
            return

        normalized_phone = normalize_phone(phone)
        await state.update_data(phone=normalized_phone)

        # Зберігаємо номер у базі даних при першому введенні
        await UserCRUD.get_or_create(
            session=session,
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        await UserCRUD.update_phone(session=session, telegram_id=message.from_user.id, phone=normalized_phone)

        data = await state.get_data()
        phone_prompt_msg_id = data.get("phone_prompt_msg_id")
        if phone_prompt_msg_id:
            try:
                await message.bot.edit_message_reply_markup(
                    chat_id=message.chat.id,
                    message_id=phone_prompt_msg_id,
                    reply_markup=None,
                )
            except Exception as edit_err:
                logger.error(f"Failed to clear phone back button: {edit_err}")

        # Непомітно прибираємо нижню клавіатуру контакту
        remove_msg = await message.answer("⏳", reply_markup=ReplyKeyboardRemove())
        await remove_msg.delete()

        notes_prompt_msg = await message.answer(MESSAGES["notes_prompt"], parse_mode="HTML", reply_markup=get_notes_keyboard())
        await state.update_data(notes_prompt_msg_id=notes_prompt_msg.message_id)
        await state.set_state(OrderFSM.notes_input)

    except Exception as e:
        logger.error(f"Error in phone_input_handler: {e}")
        await _clear_warning(message, state)
        await message.answer(MESSAGES["invalid_phone"], parse_mode="HTML")
# ==========================================
# ХЕНДЛЕРИ КОМЕНТАРІВ (НОВІ)
# ==========================================

async def _show_confirmation(
    message_or_query: types.Message | types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    source_message_id: int | None = None,
):
    """Helper to generate and show the confirmation screen."""
    data = await state.get_data()
    drink = data.get("selected_drink", {})
    pickup_time = data.get("pickup_time")
    notes = data.get("notes", "")
    favorite_flow = bool(data.get("favorite_flow", False))
    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=message_or_query.from_user.id)

    pickup_time_str = pickup_time.strftime("%d.%m.%Y %H:%M") if pickup_time else "—"
    notes_text = f"📝 Побажання: <b>{notes}</b>\n\n" if notes else ""

    confirmation_text = MESSAGES["confirmation"].format(
        drink_name=drink.get("name", "—"),
        volume=drink.get("volume", "—"),
        price=drink.get("price", "—"),
        pickup_time=pickup_time_str,
        notes_text=notes_text
    )

    show_save_favorite = bool(user) and not favorite_flow and not _is_current_favorite(user, drink, data.get("phone", ""), notes)
    keyboard = get_confirmation_keyboard(
        show_save_favorite=show_save_favorite,
        allow_back_to_notes=not favorite_flow,
    )

    if isinstance(message_or_query, types.CallbackQuery):
        await message_or_query.message.edit_text(confirmation_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        if source_message_id is not None:
            await message_or_query.bot.edit_message_text(
                chat_id=message_or_query.chat.id,
                message_id=source_message_id,
                text=confirmation_text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            await message_or_query.answer(confirmation_text, parse_mode="HTML", reply_markup=keyboard)

    await state.set_state(OrderFSM.confirmation)

@router.message(OrderFSM.notes_input, F.text, ~F.text.startswith("/"))
async def notes_input_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Handle text notes input."""
    logger.info(f"User {message.from_user.id} entered notes")
    await _clear_warning(message, state)
    await state.update_data(notes=message.text.strip())
    data = await state.get_data()
    notes_prompt_msg_id = data.get("notes_prompt_msg_id")
    await _show_confirmation(message, state, session=session, source_message_id=notes_prompt_msg_id)

@router.message(StateFilter(OrderFSM.time_input, OrderFSM.phone_input, OrderFSM.notes_input))
async def wrong_content_fsm_handler(message: types.Message) -> None:
    """Ловить стікери, фото, відео під час FSM і видаляє їх."""
    try:
        await message.delete()
    except Exception:
        pass
        
    warning = await message.answer("⚠️ <b>Будь ласка, надішли звичайний текст або використай кнопки!</b>", parse_mode="HTML")
    
    # Видаляємо це попередження через 3 секунди, щоб не засмічувати чат
    import asyncio
    await asyncio.sleep(3)
    try:
        await warning.delete()
    except Exception:
        pass

@router.callback_query(OrderFSM.notes_input, F.data == "skip_notes")
async def skip_notes_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Handle skip notes button."""
    logger.info(f"User {query.from_user.id} skipped notes")
    await state.update_data(notes="")
    await query.answer()
    await _clear_warning(query, state)
    await _show_confirmation(query, state, session=session)

# ==========================================


@router.callback_query(FavoriteOrderCallback.filter(F.action == "save"))
async def save_favorite_order_handler(
    query: types.CallbackQuery,
    callback_data: FavoriteOrderCallback,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Save the current FSM order as the user's favorite."""
    logger.info(f"User {query.from_user.id} saved favorite order")

    data = await state.get_data()
    drink = data.get("selected_drink", {})
    phone = data.get("phone", "")
    notes = data.get("notes", "")

    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=query.from_user.id)
    if user is None:
        await query.answer("❌ Користувача не знайдено", show_alert=True)
        return

    if _is_current_favorite(user, drink, phone, notes):
        await query.answer("⭐️ Вже збережено як улюблене", show_alert=False)
        await query.message.edit_reply_markup(
            reply_markup=get_confirmation_keyboard(
                show_save_favorite=False,
                allow_back_to_notes=not bool(data.get("favorite_flow", False)),
            )
        )
        return

    await UserCRUD.save_favorite_order(
        session=session,
        telegram_id=query.from_user.id,
        drink_name=drink.get("name", ""),
        volume_ml=int(drink.get("volume", 0) or 0),
        price=float(drink.get("price", 0) or 0),
        phone=phone,
        notes=notes,
    )

    await query.message.edit_reply_markup(
        reply_markup=get_confirmation_keyboard(
            show_save_favorite=False,
            allow_back_to_notes=not bool(data.get("favorite_flow", False)),
        )
    )
    await query.answer("⭐️ Збережено як улюблене", show_alert=False)


@router.callback_query(FavoriteOrderCallback.filter(F.action == "open"))
async def open_favorite_order_handler(
    query: types.CallbackQuery,
    callback_data: FavoriteOrderCallback,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Start the favorite-order shortcut from the main menu."""
    logger.info(f"User {query.from_user.id} opened favorite order")

    if await SystemSettingCRUD.is_orders_paused(session):
        await WaitlistCRUD.add_to_waitlist(session, query.from_user.id)
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.answer(MESSAGES["orders_paused"], parse_mode="HTML")
        await state.clear()
        return

    active_order, active_status = await _get_active_order_state(session=session, telegram_id=query.from_user.id)
    if active_order is not None:
        await query.answer("⏳ У тебе вже є активне замовлення", show_alert=True)
        try:
            await query.message.edit_text(
                _format_active_order_notice(active_order.order_number, active_status),
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass
        await state.clear()
        return

    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=query.from_user.id)
    if user is None or not user.favorite_drink_name:
        await query.answer("⭐️ У тебе ще немає збереженого улюбленого замовлення", show_alert=True)
        return

    sheets_service = await get_sheets_service()
    config = await sheets_service.get_business_config()

    open_time_str = config.get("CAFE_OPEN_TIME", "09:00")
    close_time_str = config.get("CAFE_CLOSE_TIME", "23:59")

    current_time = datetime.now().time()
    try:
        open_parts = open_time_str.split(":")
        close_parts = close_time_str.split(":")
        start_work = time(int(open_parts[0]), int(open_parts[1]))
        end_work = time(int(close_parts[0]), int(close_parts[1]))

        if not (start_work <= current_time <= end_work):
            nice_open = f"{start_work.hour:02d}:{start_work.minute:02d}"
            nice_close = f"{end_work.hour:02d}:{end_work.minute:02d}"
            await query.message.edit_text(_format_closed_notice(nice_open, nice_close), parse_mode="HTML")
            await query.answer()
            await state.clear()
            return
    except Exception as parse_err:
        logger.error(f"Error parsing table times in favorite open handler: {parse_err}")

    favorite_drink = {
        "name": user.favorite_drink_name,
        "volume": user.favorite_volume_ml or 0,
        "price": user.favorite_price or 0,
    }

    await state.clear()
    await state.update_data(
        selected_drink=favorite_drink,
        phone=user.favorite_phone or "",
        notes=user.favorite_notes or "",
        favorite_flow=True,
        time_prompt_msg_id=query.message.message_id,
    )

    await query.message.edit_text(
        MESSAGES["time_prompt"],
        parse_mode="HTML",
        reply_markup=get_time_keyboard(),
    )
    await state.set_state(OrderFSM.time_input)
    await query.answer()

@router.callback_query(OrderFSM.confirmation, F.data == "confirm_order")
async def confirm_order_handler(
    query: types.CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    """Handle order confirmation."""
    logger.info(f"User {query.from_user.id} confirmed order")

    try:
        if await SystemSettingCRUD.is_orders_paused(session):
            await WaitlistCRUD.add_to_waitlist(session, query.from_user.id)
            await query.answer()
            try:
                await query.message.delete()
            except Exception:
                pass
            await query.message.answer(MESSAGES["orders_paused"], parse_mode="HTML")
            await state.clear()
            return

        active_order, active_status = await _get_active_order_state(session=session, telegram_id=query.from_user.id)
        if active_order is not None:
            await query.answer("⏳ У тебе вже є активне замовлення", show_alert=True)
            try:
                await query.message.edit_text(
                    _format_active_order_notice(active_order.order_number, active_status),
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except Exception:
                pass
            await state.clear()
            return

        # Get data
        data = await state.get_data()
        drink = data.get("selected_drink", {})
        pickup_time = data.get("pickup_time")
        phone = data.get("phone")
        notes = data.get("notes", "")  # Дістаємо побажання (якщо вони є)

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
            notes=notes,
        )

        # Send notification to admin
        from bot.services.notifications import AdminNotificationService
        
        # Використовуємо існуючого бота з параметрів функції!
        notification_service = AdminNotificationService(bot)

        # ЗБЕРІГАЄМО ID картки баристи
        admin_msg_id = await notification_service.send_order_notification(
            order_number=order_number,
            customer_name=query.from_user.first_name,
            phone=phone,
            drink_name=drink.get("name", "Unknown"),
            volume_ml=drink.get("volume", 0),
            price=drink.get("price", 0),
            pickup_time=pickup_time,
            notes=notes,
            user_id=query.from_user.id,
            receipt_msg_id=query.message.message_id,  
        )

        # Show success message
        pickup_time_str_display = pickup_time.strftime("%d.%m.%Y %H:%M") if pickup_time else "—"
        success_text = MESSAGES["success"].format(
            order_id=order_number,
            pickup_time=pickup_time_str_display,
        )

        await query.answer()
        await query.message.edit_reply_markup(reply_markup=None)

        await query.message.delete()
        await bot.send_message(
            chat_id=query.message.chat.id,
            text=success_text,
            parse_mode="HTML",
            reply_markup=get_new_order_reply_keyboard(),
        )

        # Clear FSM and keep the success screen until the user asks for a new order
        await state.clear()

        logger.info(f"Order {order_number} created successfully")

    except Exception as e:
        logger.error(f"Error in confirm_order_handler: {e}")
        await query.answer("❌ Помилка при збереженні замовлення", show_alert=True)
# ==========================================
# ХЕНДЛЕРИ КНОПОК "НАЗАД"
# ==========================================

@router.callback_query(StateFilter(OrderFSM.time_input), F.data == "back_to_menu")
async def back_to_menu_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    logger.info(f"User {query.from_user.id} went back to menu")
    await _clear_warning(query, state)
    data = await state.get_data()
    menu = data.get("menu")
    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=query.from_user.id)

    active_order, active_status = await _get_active_order_state(session=session, telegram_id=query.from_user.id)
    if active_order is not None:
        await query.answer("⏳ У тебе вже є активне замовлення", show_alert=True)
        await query.message.edit_text(
            _format_active_order_notice(active_order.order_number, active_status),
            parse_mode="HTML",
            reply_markup=None,
        )
        await state.clear()
        return

    if not menu:
        sheets_service = await get_sheets_service()
        menu = await sheets_service.get_menu()
        await state.update_data(menu=menu)

    keyboard = get_menu_keyboard(menu, favorite_drink_name=getattr(user, "favorite_drink_name", None))
    await query.message.edit_text(
        MESSAGES["menu"].format(menu_items=_format_menu_items(menu)),
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await state.set_state(OrderFSM.menu_selection)
    await query.answer()


@router.callback_query(StateFilter(OrderFSM.phone_input), F.data == "back_to_time")
async def back_to_time_handler(query: types.CallbackQuery, state: FSMContext) -> None:
    logger.info(f"User {query.from_user.id} went back to time input")
    await _clear_warning(query, state)
    # Непомітно прибираємо нижню клавіатуру
    remove_msg = await query.message.answer("🔄", reply_markup=ReplyKeyboardRemove())
    await remove_msg.delete()
    
    await query.message.edit_text(
        MESSAGES["time_prompt"],
        parse_mode="HTML",
        reply_markup=get_time_keyboard()
    )
    
    await state.set_state(OrderFSM.time_input)
    await query.answer()


@router.callback_query(StateFilter(OrderFSM.notes_input), F.data == "back_to_phone")
async def back_to_phone_handler(query: types.CallbackQuery, state: FSMContext) -> None:
    """Go back from notes (to time input if phone was auto-skipped, or to phone input if manual)."""
    logger.info(f"User {query.from_user.id} went back from notes input")
    await _clear_warning(query, state)
    data = await state.get_data()

    if data.get("phone_autoskipped"):
        await query.message.edit_text(
            MESSAGES["time_prompt"],
            parse_mode="HTML",
            reply_markup=get_time_keyboard()
        )
        await state.update_data(time_prompt_msg_id=query.message.message_id)
        await state.set_state(OrderFSM.time_input)
        await query.answer()
        return

    phone_prompt_msg = await query.message.edit_text(
        MESSAGES["phone_prompt"],
        parse_mode="HTML",
        reply_markup=get_phone_reply_keyboard()
    )
    await state.update_data(phone_prompt_msg_id=query.message.message_id)
    await state.set_state(OrderFSM.phone_input)
    await query.answer()


@router.callback_query(StateFilter(OrderFSM.confirmation), F.data == "back_to_notes")
async def back_to_notes_handler(query: types.CallbackQuery, state: FSMContext) -> None:
    """Go back to notes input from confirmation."""
    logger.info(f"User {query.from_user.id} went back to notes input")
    await _clear_warning(query, state)
    await query.message.edit_text(
        MESSAGES["notes_prompt"],
        parse_mode="HTML",
        reply_markup=get_notes_keyboard()
    )
    await state.set_state(OrderFSM.notes_input)
    await query.answer()


# ==========================================
# ЧИСТИЛЬНИК СТАРИХ КНОПОК
# ==========================================


@router.message(F.text.in_({"☕ Ще одне замовлення", "☕ Переглянути меню", "☕️ Переглянути меню"}))
async def new_order_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Open the menu again from the bottom reply keyboard."""
    logger.info(f"User {message.from_user.id} requested a new order")

    # ==========================================
    # 💥 ЗАХИСТ ВІД ДУБЛІВ МЕНЮ ТА ПЕРЕКРИТТЯ КРОКІВ
    current_state = await state.get_state()
    if current_state is not None:
        try:
            await message.delete()  # Очищаємо чат від зайвих команд
        except Exception:
            pass
            
        # Видаляємо старе попередження
        await _clear_warning(message, state)
        
        # Якщо ми на кроці телефону — примусово повертаємо нижню кнопку!
        markup = None
        if current_state == OrderFSM.phone_input.state:
            from bot.keyboards.inline import get_phone_reply_keyboard
            markup = get_phone_reply_keyboard()
                
        # Відправляємо нове попередження вниз чату
        warning_msg = await message.answer(
            "⚠️ <b>Ти вже в процесі оформлення замовлення!</b>\n\n"
            "Продовж його вище або натисни команду /cancel, щоб скасувати його і відкрити меню заново.",
            parse_mode="HTML",
            reply_markup=markup
        )
        await state.update_data(warning_msg_id=warning_msg.message_id)
        return
        # ==========================================

    active_order, active_status = await _get_active_order_state(session=session, telegram_id=message.from_user.id)
    if active_order is not None:
        await message.answer(
            _format_active_order_notice(active_order.order_number, active_status),
            parse_mode="HTML",
        )
        await state.clear()
        return

    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=message.from_user.id)

    sheets_service = await get_sheets_service()
    config = await sheets_service.get_business_config()

    open_time_str = config.get("CAFE_OPEN_TIME", "09:00")
    close_time_str = config.get("CAFE_CLOSE_TIME", "23:59")

    try:
        open_parts = open_time_str.split(":")
        close_parts = close_time_str.split(":")
        start_work = time(int(open_parts[0]), int(open_parts[1]))
        end_work = time(int(close_parts[0]), int(close_parts[1]))
        current_time = datetime.now().time()

        if not (start_work <= current_time <= end_work):
            nice_open = f"{start_work.hour:02d}:{start_work.minute:02d}"
            nice_close = f"{end_work.hour:02d}:{end_work.minute:02d}"
            await message.answer(
                _format_closed_notice(nice_open, nice_close),
                parse_mode="HTML",
                reply_markup=get_new_order_reply_keyboard(),
            )
            await state.clear()
            return
    except Exception as parse_err:
        logger.error(f"Error parsing table times in new_order_handler: {parse_err}")

    await _send_menu(
        message,
        state,
        session,
        favorite_drink_name=getattr(user, "favorite_drink_name", None),
        remove_reply_keyboard=True,
    )


@router.callback_query(F.data.startswith("usr_cancel:"))
async def user_cancel_active_order_handler(query: types.CallbackQuery) -> None:
    """Обробляє спробу клієнта скасувати вже створене замовлення."""
    
    # Розпаковуємо дані (тепер у нас 3 елементи: назва, номер_замовлення, ID_повідомлення_адміна)
    parts = query.data.split(":")
    order_number = parts[1]
    admin_msg_id = int(parts[2]) if len(parts) > 2 else 0
    
    await query.message.edit_reply_markup(reply_markup=None)
    
    sheets_service = await get_sheets_service()
    current_status = await sheets_service.get_order_status(order_number)
    
    if current_status in ["🔥 Готується", "✅ Готово"]:
        await query.answer("⚠️ Сорі, бариста вже готує вашу каву! Скасувати неможливо.", show_alert=True)
        return
        
    if current_status == "❌ Скасовано":
        await query.answer("Це замовлення вже скасовано.", show_alert=True)
        return
        
    try:
        await sheets_service.update_order_status(order_number, "❌ Скасовано")
        
        from bot.config import settings
        
        # 💥 МАГІЯ: ВИДАЛЯЄМО СТАРУ КАРТКУ ЗАМОВЛЕННЯ У БАРИСТИ!
        if admin_msg_id != 0:
            try:
                await query.bot.delete_message(chat_id=settings.admin_chat_id, message_id=admin_msg_id)
            except Exception as e:
                import logging
                logging.error(f"Не зміг видалити повідомлення адміна: {e}")

        # Відправляємо свіже повідомлення-алерт
        await query.bot.send_message(
            chat_id=settings.admin_chat_id,
            text=f"🚨 <b>УВАГА!</b> Клієнт самостійно скасував замовлення <b>{order_number}</b>!\n🗑 <i>Картку замовлення було видалено.</i>",
            parse_mode="HTML"
        )
        
        await query.message.edit_text(
            f"❌ Ваше замовлення <b>{order_number}</b> успішно скасовано.\n\nЧекаємо вас наступного разу! ☕️",
            parse_mode="HTML",
            reply_markup=None
        )
        await query.answer("Замовлення скасовано.")
        
    except Exception as e:
        import logging
        logging.error(f"Помилка при скасуванні активного замовлення: {e}")
        await query.answer("Виникла технічна помилка. Напишіть баристі.", show_alert=True)




import re
from bot.keyboards.inline import get_admin_order_keyboard

STATUS_MAP = {
    "acc": ("🟡 Прийнято", "Ваше замовлення <b>{order_number}</b> прийнято і скоро почне готуватися! ⏳"),
    "prep": ("🔥 Готується", "Бариста вже чаклує над вашим замовленням <b>{order_number}</b>! ☕️"),
    "rdy": ("✅ Готово", "🎉 Ваша кава <b>{order_number}</b> готова! Можете забирати на барі!"),
    "canc": ("❌ Скасовано", "На жаль, ваше замовлення <b>{order_number}</b> було скасовано.")
}

@router.callback_query(F.data.startswith("adm_st:"))
async def admin_status_handler(query: types.CallbackQuery) -> None:
    """Обробляє зміну статусу з динамічним оновленням ЄДИНОГО повідомлення у клієнта."""
    
    # Розпаковуємо дані (тепер у нас 6 елементів)
    parts = query.data.split(":")
    if len(parts) < 5:
        await query.answer("❌ Помилка даних кнопки", show_alert=True)
        return
        
    status_key = parts[1]
    order_number = parts[2]
    user_id = int(parts[3])
    client_msg_id = int(parts[4])
    receipt_msg_id = int(parts[5]) if len(parts) >= 6 else 0

    # 1. ЗАХИСТ ВІД "МЕРТВИХ КНОПОК"
    try:
        from bot.services.google_sheets import get_sheets_service
        sheets_service = await get_sheets_service()
        current_sheet_status = await sheets_service.get_order_status(order_number)
        
        if current_sheet_status == "❌ Скасовано":
            await query.answer("⚠️ Клієнт вже самостійно скасував це замовлення!", show_alert=True)
            old_text = query.message.html_text
            import re
            new_text = re.sub(r"🔔 <b>Статус:</b>.*", f"🔔 <b>Статус:</b> ❌ Скасовано (клієнтом)", old_text)
            await query.message.edit_text(new_text, parse_mode="HTML", reply_markup=None)
            return
    except Exception as e:
        import logging
        logging.error(f"Помилка перевірки актуального статусу: {e}")

    # ==========================================
    # 💥 НОВЕ: ЗНИЩУЄМО КНОПКУ "СКАСУВАТИ" У КЛІЄНТА
    # ==========================================
    # Якщо бариста натиснув "Готується", "Готово" або "Скасувати"
    if status_key in ["prep", "rdy", "canc"] and receipt_msg_id != 0:
        try:
            # Змінюємо клавіатуру оригінального чека на None (порожнечу)
            await query.bot.edit_message_reply_markup(
                chat_id=user_id, 
                message_id=receipt_msg_id, 
                reply_markup=None
            )
        except Exception as e:
            import logging
            logging.error(f"Не зміг прибрати кнопку скасування у клієнта: {e}")
    # ==========================================
    
    status_name, client_message = STATUS_MAP.get(status_key, ("Невідомо", ""))
    
    # 2. Оновлюємо статус в Google Таблицях
    try:
        await sheets_service.update_order_status(order_number, status_name)
    except Exception as e:
        import logging
        logging.error(f"Не вдалося оновити статус в таблиці: {e}")

    # 3. МАГІЯ ЄДИНОГО ВІКНА + PUSH-ПОВІДОМЛЕННЯ
    formatted_message = client_message.format(order_number=order_number)
    new_client_msg_id = client_msg_id

    try:
        if status_key in ["rdy", "canc"]:
            if client_msg_id != 0:
                try:
                    await query.bot.delete_message(chat_id=user_id, message_id=client_msg_id)
                except Exception:
                    pass
            msg = await query.bot.send_message(chat_id=user_id, text=formatted_message, parse_mode="HTML")
            new_client_msg_id = msg.message_id

        elif client_msg_id == 0:
            msg = await query.bot.send_message(chat_id=user_id, text=formatted_message, parse_mode="HTML")
            new_client_msg_id = msg.message_id
            
        else:
            await query.bot.edit_message_text(
                chat_id=user_id,
                message_id=client_msg_id,
                text=formatted_message,
                parse_mode="HTML"
            )
    except Exception as e:
        import logging
        logging.error(f"Не зміг оновити/відправити повідомлення клієнту {user_id}: {e}")

    # 4. Генеруємо нову клавіатуру для адміна (передаємо обидва ID)
    new_keyboard = get_admin_order_keyboard(
        order_number, 
        user_id, 
        current_status=status_key, 
        client_msg_id=new_client_msg_id,
        receipt_msg_id=receipt_msg_id
    )
    
    # 5. Оновлюємо адмінську картку баристи
    old_text = query.message.html_text
    import re
    new_text = re.sub(r"🔔 <b>Статус:</b>.*", f"🔔 <b>Статус:</b> {status_name}", old_text)
    
    await query.message.edit_text(new_text, parse_mode="HTML", reply_markup=new_keyboard)
    await query.answer(f"Статус змінено на {status_name}.")


# ==========================================
# ЗМІНА НОМЕРА ТЕЛЕФОНУ ТА МЕНЮ
# ==========================================


@router.message(Command("phone"))
@router.message(Command("change_phone"))
async def change_phone_cmd_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Обробляє команду /phone для зміни номера телефону."""
    logger.info(f"User {message.from_user.id} requested phone change")
    await _clear_warning(message, state)
    await state.clear()
    await UserCRUD.get_or_create(
        session=session,
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    await message.answer(
        "📱 <b>Введи новий номер телефону</b> (наприклад: 0501234567) або скористайся кнопкою внизу:",
        parse_mode="HTML",
        reply_markup=get_phone_reply_keyboard(),
    )
    await state.set_state(OrderFSM.changing_phone)


@router.message(OrderFSM.changing_phone, F.contact | (F.text & ~F.text.startswith("/")))
async def changing_phone_input_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Приймає новий номер телефону при виклику /phone."""
    logger.info(f"User {message.from_user.id} changing phone input")
    try:
        phone = message.contact.phone_number if message.contact else message.text.strip()
        if not validate_phone(phone):
            await message.answer(
                "⚠️ Некоректний номер телефону. Спробуй ще раз (наприклад: 0501234567) або натисни кнопку внизу.",
                parse_mode="HTML",
            )
            return

        normalized_phone = normalize_phone(phone)
        await UserCRUD.update_phone(session=session, telegram_id=message.from_user.id, phone=normalized_phone)
        await state.clear()

        await message.answer(
            f"✅ <b>Номер телефону успішно змінено на {normalized_phone}!</b>\n\nТепер для всіх твоїх нових замовлень буде використовуватись цей номер.",
            parse_mode="HTML",
            reply_markup=get_view_menu_reply_keyboard(),
        )
    except Exception as e:
        logger.error(f"Error in changing_phone_input_handler: {e}")
        await message.answer("⚠️ Некоректний номер телефону. Спробуй ще раз.", parse_mode="HTML")


@router.message(F.text.in_({"☕ Переглянути меню", "☕️ Переглянути меню"}))
async def view_menu_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Обробляє натискання кнопки '☕ Переглянути меню'."""
    logger.info(f"User {message.from_user.id} clicked view menu button")
    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=message.from_user.id)
    await _send_menu(
        message,
        state,
        session,
        favorite_drink_name=getattr(user, "favorite_drink_name", None),
    )


# ==========================================
# ГЛОБАЛЬНИЙ СМІТТЄЗБІРНИК
# ==========================================
@router.message()
async def global_trash_catcher(message: types.Message) -> None:
    """
    Ця функція стоїть у самому кінці. Вона ловить ВСЕ, 
    що не спіймали інші хендлери (випадковий текст, стікери поза замовленням).
    Ми просто тихо це видаляємо.
    """
    try:
        await message.delete()
    except Exception:
        pass

    # ==========================================
# ГЛОБАЛЬНИЙ ПЕРЕХОПЛЮВАЧ "МЕРТВИХ" КНОПОК
# ==========================================
@router.callback_query()
async def global_dead_callback_catcher(query: types.CallbackQuery, state: FSMContext) -> None:
    """
    Ця функція ловить кліки по інлайн-кнопках від застарілих сесій.
    Видаляє накопичені підказки FSM та виводить чисте сповіщення про застарілу сесію.
    """
    try:
        await query.answer()  # Без popup алерта!
    except Exception:
        pass

    try:
        await _clear_warning(query, state)
        data = await state.get_data()

        # Видаляємо всі попередні повідомлення підказок FSM
        for msg_key in ("time_prompt_msg_id", "phone_prompt_msg_id", "notes_prompt_msg_id", "warning_msg_id"):
            msg_id = data.get(msg_key)
            if msg_id:
                try:
                    await query.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_id)
                except Exception:
                    pass

        # Видаляємо застаріле повідомлення з кнопками
        try:
            await query.message.delete()
        except Exception:
            try:
                await query.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        await state.clear()
    except Exception as e:
        logger.error(f"Error cleaning dead callback session: {e}")

    # Даємо клієнту чітку інструкцію, що робити далі
    await query.message.answer(
        "🔌 <b>Сесія застаріла (можливо, бот щойно оновлювався).</b>\n\n"
        "Щоб зробити нове замовлення, просто натисни /start ☕️",
        parse_mode="HTML"
    )