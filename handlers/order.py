"""Order handling router with FSM flow."""
from __future__ import annotations

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
    get_new_order_inline_keyboard,
    get_notes_keyboard,
    get_start_menu_inline_keyboard,
    get_menu_keyboard, 
    get_back_to_menu_keyboard, 
    get_back_to_time_keyboard,
    FavoriteOrderCallback,
    get_phone_reply_keyboard, 
    get_time_keyboard,
)
from bot.services.google_sheets import get_sheets_service
from bot.services.ui_manager import UIManager
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
    "cancelled": "❌ Замовлення скасовано.\n\nМожеш зробити нове замовлення, натисни кнопку внизу:",
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

async def _show_active_order_screen(bot: Any, session: AsyncSession, chat_id: int, active_order: Any, active_status: str | None) -> None:
    from bot.keyboards.inline import get_user_cancel_keyboard
    
    can_cancel = active_status == "New"
    
    if can_cancel:
        markup = get_user_cancel_keyboard(order_number=active_order.order_number, admin_msg_id=0)
    else:
        markup = None
        
    await UIManager.show_screen(
        bot=bot,
        session=session,
        chat_id=chat_id,
        text=_format_active_order_notice(active_order.order_number, active_status),
        markup=markup
    )


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
    edit_message_id: int | None = None,
    ignore_pause: bool = False,
) -> None:
    """Load and show the main menu, then switch FSM to menu selection."""
    user_id = message.chat.id
    
    if not ignore_pause and await SystemSettingCRUD.is_orders_paused(session):
        await WaitlistCRUD.add_to_waitlist(session, user_id)
        await UIManager.show_screen(
            bot=message.bot, session=session, chat_id=user_id,
            text=MESSAGES["orders_paused"]
        )
        await state.clear()
        await state.update_data(current_view="orders_paused")
        return

    sheets_service = await get_sheets_service()
    menu = await sheets_service.get_menu()

    if not menu:
        await UIManager.show_screen(
            bot=message.bot, session=session, chat_id=user_id,
            text=MESSAGES["menu_empty"]
        )
        await state.clear()
        await state.update_data(current_view="menu_empty")
        return

    menu_items_text = _format_menu_items(menu)
    text = MESSAGES["menu"].format(menu_items=menu_items_text)
    markup = get_menu_keyboard(menu, favorite_drink_name=favorite_drink_name)

    # UIManager automatically handles remove_reply_keyboard by detecting ReplyKeyboardRemove
    if remove_reply_keyboard:
        # We need to explicitly clear it first, then send the menu
        await UIManager.show_screen(
            bot=message.bot, session=session, chat_id=user_id,
            text="🔄", markup=ReplyKeyboardRemove()
        )

    await UIManager.show_screen(
        bot=message.bot, session=session, chat_id=user_id,
        text=text, markup=markup, edit_msg_id=edit_message_id
    )

    await state.update_data(menu=menu, current_view="menu")
    await state.set_state(OrderFSM.menu_selection)


@router.callback_query(F.data.in_({"new_order_inline", "open_menu_inline"}))
async def inline_menu_triggers_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Handle inline buttons to start a new order or open menu."""
    
    active_order, active_status = await _get_active_order_state(session=session, telegram_id=query.from_user.id)
    if active_order is not None:
        await query.answer()
        await _show_active_order_screen(query.bot, session, query.message.chat.id, active_order, active_status)
        return
        
    await query.answer()
    
    # В усіх цих випадках поточне повідомлення перетвориться на меню
    edit_msg_id = query.message.message_id
    
    # We pretend this was a /start command to use the robust start logic
    await start_handler(query.message, state, session, is_callback=True, edit_msg_id=edit_msg_id)

@router.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext, session: AsyncSession, is_callback: bool = False, edit_msg_id: int | None = None) -> None:
    """Handle /start command - display menu."""
    user_id = message.chat.id if is_callback else message.from_user.id
    logger.info(f"User {user_id} started bot")

    if not is_callback:
        try:
            await message.delete()  # Завжди очищаємо команду /start для чистоти чату
        except Exception:
            pass

    try:
       # ==========================================
        # 💥 ЗАХИСТ ВІД ДУБЛІВ МЕНЮ ТА ПЕРЕКРИТТЯ КРОКІВ
        
        # Завжди очищаємо історію або попередження перед стартом
        
        current_state = await state.get_state()
        if current_state is not None:
            if not is_callback:
                await UIManager.show_toast(
                    bot=message.bot,
                    chat_id=user_id,
                    text="⚠️ <b>Ти вже в процесі оформлення замовлення!</b>\nПродовж його або відправ команду /cancel для скасування.",
                    duration=4
                )
            return
        # ==========================================

        # Одразу фіксуємо стан FSM, щоб заблокувати будь-які паралельні дублі /start
        await state.set_state(OrderFSM.menu_selection)

        user_model_id = message.chat.id if is_callback else message.from_user.id
        first_name = "" if is_callback else message.from_user.first_name
        last_name = "" if is_callback else message.from_user.last_name
        user = await UserCRUD.get_or_create(
            session=session,
            telegram_id=user_model_id,
            first_name=first_name,
            last_name=last_name,
        )

        active_order, active_status = await _get_active_order_state(session=session, telegram_id=user_model_id)
        if active_order is not None:
            await _show_active_order_screen(message.bot, session, user_id, active_order, active_status)
            await state.clear()
            return
            
        await _send_menu(
            message,
            state,
            session,
            favorite_drink_name=user.favorite_drink_name,
            edit_message_id=edit_msg_id
        )

    except Exception as e:
        logger.error(f"Error in start_handler: {e}")
        await UIManager.show_toast(
            bot=message.bot,
            chat_id=message.chat.id,
            text="⚠️ Технічна помилка. Спробуй ще раз за хвилину.",
            duration=4
        )

@router.callback_query(F.data.in_(["cancel_order", "cancel_flow"]))
@router.callback_query(OrderFSM.menu_selection, F.data == "cancel_order")
@router.callback_query(OrderFSM.time_input, F.data == "cancel_order")
@router.callback_query(OrderFSM.phone_input, F.data == "cancel_order")
@router.callback_query(OrderFSM.notes_input, F.data == "cancel_order")
@router.callback_query(OrderFSM.confirmation, F.data == "cancel_order")
@router.message(Command("cancel"))
async def cancel_handler(message_or_query: types.Message | types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Handle cancellation from any state."""
    logger.info("User cancelled order flow")

    try:
        current_state = await state.get_state()
        data = await state.get_data()
        
        # Check if we need to remove reply keyboard (if we were in phone input or changing phone)
        remove_reply_keyboard = False
        if current_state in (OrderFSM.phone_input.state, OrderFSM.changing_phone.state) or not current_state:
            remove_reply_keyboard = True
            
        if isinstance(message_or_query, types.CallbackQuery):
            await message_or_query.answer()
            chat_id = message_or_query.message.chat.id
            bot = message_or_query.message.bot
        else:
            chat_id = message_or_query.chat.id
            bot = message_or_query.bot
            try:
                await message_or_query.delete()  # Видаляємо саму команду /cancel від користувача
            except Exception:
                pass

        # If there is nothing to cancel (state is completely empty), handle quietly
        if not data and not isinstance(message_or_query, types.CallbackQuery):
            await UIManager.show_toast(
                bot=bot,
                chat_id=chat_id,
                text="Скасовувати нічого — у тебе немає активного процесу.",
                duration=4
            )
            await state.clear()
            return

        if current_state == OrderFSM.changing_phone.state:
            text = "✅ <b>Зміну номера телефону скасовано.</b>"
        else:
            text = MESSAGES["cancelled"]
        markup = get_start_menu_inline_keyboard()

        await UIManager.show_screen(
            bot=bot,
            session=session,
            chat_id=chat_id,
            text=text,
            markup=markup
        )

        await state.clear()
        await state.update_data(current_view="cancel")

    except Exception as e:
        logger.error(f"Error in cancel_handler: {e}")
        await state.clear()


@router.callback_query(OrderFSM.menu_selection, F.data.startswith("drink_"))
async def drink_selected_handler(
    query: types.CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Handle drink selection with instant shop status check."""
    logger.info(f"User {query.from_user.id} selected drink")

    try:
        if await SystemSettingCRUD.is_orders_paused(session):
            await WaitlistCRUD.add_to_waitlist(session, query.from_user.id)
            await query.answer()
            await UIManager.show_screen(
                bot=query.message.bot,
                session=session,
                chat_id=query.message.chat.id,
                text=MESSAGES["orders_paused"]
            )
            await state.clear()
            await state.update_data(current_view="orders_paused")
            return

        active_order, active_status = await _get_active_order_state(session=session, telegram_id=query.from_user.id)
        if active_order is not None:
            await query.answer()
            await _show_active_order_screen(query.message.bot, session, query.message.chat.id, active_order, active_status)
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

                from bot.keyboards.inline import get_orders_paused_keyboard
                await query.answer()
                await UIManager.show_screen(
                    bot=query.message.bot,
                    session=session,
                    chat_id=query.message.chat.id,
                    text=closed_notice,
                    markup=get_orders_paused_keyboard()
                )
                await state.clear()
                await state.update_data(current_view="closed")
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
        await state.update_data(selected_drink=drink, time_prompt_msg_id=query.message.message_id, menu_msg_id=None)
        
        await query.answer()
        await UIManager.show_screen(
            bot=query.message.bot,
            session=session,
            chat_id=query.message.chat.id,
            text=MESSAGES["time_prompt"],
            markup=get_time_keyboard()
        )
        await state.set_state(OrderFSM.time_input)
    except Exception as e:
        logger.error(f"Error in drink_selected_handler: {e}")
        await query.answer("❌ Помилка при виборі напою", show_alert=True)


@router.callback_query(OrderFSM.time_input, F.data.startswith("quick_time:"))
async def quick_time_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    minutes = int(query.data.split(":")[1])
    pickup_time = datetime.now() + timedelta(minutes=minutes)
    
    await state.update_data(pickup_time=pickup_time)

    data = await state.get_data()
    if data.get("favorite_flow"):
        await _show_confirmation(query.message, state, session=session)
        await query.answer()
        return

    # Перевірка наявності телефону у БД (Автопропуск)
    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=query.from_user.id)
    if user and user.phone:
        await state.update_data(phone=user.phone, phone_autoskipped=True)
        await UIManager.show_screen(
            bot=query.message.bot,
            session=session,
            chat_id=query.message.chat.id,
            text=MESSAGES["notes_prompt"],
            markup=get_notes_keyboard()
        )
        await state.set_state(OrderFSM.notes_input)
        await query.answer()
        return

    await state.update_data(phone_autoskipped=False)
    await UIManager.show_screen(
        bot=query.message.bot,
        session=session,
        chat_id=query.message.chat.id,
        text=MESSAGES["phone_prompt"],
        markup=get_phone_reply_keyboard()
    )

    await state.set_state(OrderFSM.phone_input)
    await query.answer()

@router.message(OrderFSM.time_input, F.text, ~F.text.startswith("/"))
async def time_input_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Handle time input."""
    try:
        await message.delete()
    except Exception:
        pass
    logger.info(f"User {message.from_user.id} entered time: {message.text}")
    pickup_time = None

    try:
        pickup_time = parse_time_input(message.text)
        async def _show_time_error(error_text: str):
            await UIManager.show_toast(
                bot=message.bot,
                chat_id=message.chat.id,
                text=f"⚠️ <b>{error_text}</b>",
                duration=4
            )

        if pickup_time is None:
            await _show_time_error(MESSAGES["invalid_time"])
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

            await _show_time_error(error_msg)
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
                
                await _show_time_error(MESSAGES["time_outside_hours"].format(open_time=nice_open, close_time=nice_close))
                return
        except Exception as parse_err:
            logger.error(f"Error parsing table times ({open_time_str}/{close_time_str}): {parse_err}")

        data = await state.get_data()
        
        favorite_flow = bool(data.get("favorite_flow", False))
        await state.update_data(pickup_time=pickup_time)

        if favorite_flow:
            await _show_confirmation(message, state, session=session)
            return

        # Перевірка наявності телефону у БД (Автопропуск)
        user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=message.from_user.id)
        if user and user.phone:
            await state.update_data(phone=user.phone, phone_autoskipped=True)
            await UIManager.show_screen(
                bot=message.bot,
                session=session,
                chat_id=message.chat.id,
                text=MESSAGES["notes_prompt"],
                markup=get_notes_keyboard()
            )
            await state.set_state(OrderFSM.notes_input)
            return

        await state.update_data(phone_autoskipped=False)
        await UIManager.show_screen(
            bot=message.bot,
            session=session,
            chat_id=message.chat.id,
            text=MESSAGES["phone_prompt"],
            markup=get_phone_reply_keyboard()
        )
        await state.set_state(OrderFSM.phone_input)

    except Exception as e:
        logger.error(f"Error in time_input_handler: {e}")
        await _show_time_error(MESSAGES["invalid_time"])


@router.message(OrderFSM.phone_input, F.contact | (F.text & ~F.text.startswith("/")))
async def phone_input_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        await message.delete()
    except Exception:
        pass
    logger.info(f"User {message.from_user.id} entered phone")
    try:
        from_contact = False
        if message.contact:
            phone = message.contact.phone_number
            from_contact = True
        else:
            phone = message.text.strip()

        if phone == "🔙 Назад":
            from bot.keyboards.inline import get_time_keyboard
            await UIManager.show_screen(
                bot=message.bot,
                session=session,
                chat_id=message.chat.id,
                text=MESSAGES["time_prompt"],
                markup=get_time_keyboard(),
                force_reply_keyboard_remove=True
            )
            await state.set_state(OrderFSM.time_input)
            return

        async def _show_phone_error(error_text: str):
            await UIManager.show_toast(
                bot=message.bot,
                chat_id=message.chat.id,
                text=f"⚠️ <b>{error_text}</b>",
                duration=4
            )

        if not from_contact and not validate_phone(phone):
            await _show_phone_error(MESSAGES["invalid_phone"])
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

        await UIManager.show_screen(
            bot=message.bot,
            session=session,
            chat_id=message.chat.id,
            text=MESSAGES["notes_prompt"],
            markup=get_notes_keyboard(),
            force_reply_keyboard_remove=True,
        )
        await state.set_state(OrderFSM.notes_input)

    except Exception as e:
        logger.error(f"Error in phone_input_handler: {e}")
        pass
# ==========================================
# ХЕНДЛЕРИ КОМЕНТАРІВ (НОВІ)
# ==========================================

async def _show_confirmation(
    message_or_query: types.Message | types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    source_message_id: int | None = None,
):
    """Показує фінальне підтвердження замовлення."""
    data = await state.get_data()
    drink = data.get("selected_drink", {})
    pickup_time = data.get("pickup_time")
    notes = data.get("notes", "")
    favorite_flow = bool(data.get("favorite_flow", False))
    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=message_or_query.from_user.id)
    
    if pickup_time is None:
        if isinstance(message_or_query, types.CallbackQuery):
            await message_or_query.answer("⚠️ Час не обрано", show_alert=True)
        return
        
    pickup_time_str = pickup_time.strftime("%d.%m.%Y %H:%M")

    # Якщо пропустили, notes_text буде "Немає"
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
        back_button_type="time" if favorite_flow else "notes",
    )

    bot = message_or_query.bot if isinstance(message_or_query, types.Message) else message_or_query.message.bot
    chat_id = message_or_query.chat.id if isinstance(message_or_query, types.Message) else message_or_query.message.chat.id

    await UIManager.show_screen(
        bot=bot,
        session=session,
        chat_id=chat_id,
        text=confirmation_text,
        markup=keyboard
    )

    await state.set_state(OrderFSM.confirmation)

@router.message(OrderFSM.notes_input, F.text, ~F.text.startswith("/"))
async def notes_input_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Handle custom notes input."""
    try:
        await message.delete()
    except Exception:
        pass
    logger.info(f"User {message.from_user.id} entered notes: {message.text}")
    notes = message.text.strip()
    
    if len(notes) > 100:
        await UIManager.show_toast(
            bot=message.bot,
            chat_id=message.chat.id,
            text="⚠️ <b>Побажання занадто довге!</b> Максимум 100 символів.",
            duration=4
        )
        return
        
    await state.update_data(notes=notes)
    await _show_confirmation(message, state, session=session)

@router.message(Command("phone"))
@router.message(Command("change_phone"))
async def change_phone_cmd_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Обробляє команду /phone для зміни номера телефону."""
    from bot.keyboards.inline import get_phone_reply_keyboard
    
    try:
        await message.delete()
    except Exception:
        pass
    logger.info(f"User {message.from_user.id} requested phone change")

    # 💥 ЗАХИСТ ВІД ДУБЛІВ ТА ПЕРЕКРИТТЯ КРОКІВ
    current_state = await state.get_state()
    if current_state is not None and current_state != OrderFSM.menu_selection.state:
        await UIManager.show_toast(
            bot=message.bot,
            chat_id=message.chat.id,
            text="⚠️ <b>Ти вже в процесі замовлення.</b>\nБудь ласка, закінчи або скасуй його.",
            duration=4
        )
        return

    active_order, active_status = await _get_active_order_state(session=session, telegram_id=message.from_user.id)
    if active_order is not None:
        await _show_active_order_screen(message.bot, session, message.chat.id, active_order, active_status)
        return

    await state.clear()
    await UserCRUD.get_or_create(
        session=session,
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    
    await UIManager.show_screen(
        bot=message.bot,
        session=session,
        chat_id=message.chat.id,
        text="📱 <b>Введи новий номер телефону</b> (наприклад: 0501234567) або скористайся кнопкою внизу:",
        markup=get_phone_reply_keyboard(),
    )
    await state.set_state(OrderFSM.changing_phone)


@router.message(OrderFSM.changing_phone, F.contact | (F.text & ~F.text.startswith("/")))
async def changing_phone_input_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Приймає новий номер телефону при виклику /phone."""
    try:
        await message.delete()
    except Exception:
        pass
    logger.info(f"User {message.from_user.id} changing phone input")
    try:
        from_contact = False
        if message.contact:
            phone = message.contact.phone_number
            from_contact = True
        else:
            phone = message.text.strip()

        if phone == "🔙 Назад":
            await state.clear()
            msg = await message.answer("🔄", reply_markup=ReplyKeyboardRemove())
            try:
                await msg.delete()
            except Exception:
                pass
            await start_handler(message, state, session, is_callback=False)
            return

        async def _show_phone_error(error_text: str):
            await UIManager.show_toast(
                bot=message.bot,
                chat_id=message.chat.id,
                text=f"⚠️ <b>{error_text}</b>",
                duration=4
            )

        if not from_contact and not validate_phone(phone):
            await _show_phone_error("Некоректний номер телефону. Спробуй ще раз.")
            return

        normalized_phone = normalize_phone(phone)
        await UserCRUD.update_phone(session=session, telegram_id=message.from_user.id, phone=normalized_phone)

        await state.clear()

        await UIManager.show_screen(
            bot=message.bot,
            session=session,
            chat_id=message.chat.id,
            text=f"✅ <b>Номер телефону успішно змінено на {normalized_phone}!</b>\n\nТепер для всіх твоїх нових замовлень буде використовуватись цей номер.",
            markup=get_view_menu_reply_keyboard(),
        )
    except Exception as e:
        logger.error(f"Error in changing_phone_input_handler: {e}")
        try:
            await _show_phone_error("Технічна помилка. Спробуй ще раз.")
        except Exception:
            pass


@router.message(F.text.in_({"☕ Переглянути меню", "☕️ Переглянути меню"}))
async def view_menu_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Обробляє натискання кнопки '☕ Переглянути меню'."""
    try:
        await message.delete()
    except Exception:
        pass
    logger.info(f"User {message.from_user.id} clicked view menu button")
    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=message.from_user.id)
    await _send_menu(
        message,
        state,
        session,
        favorite_drink_name=getattr(user, "favorite_drink_name", None),
    )


@router.message(StateFilter(
    OrderFSM.menu_selection, 
    OrderFSM.time_input, 
    OrderFSM.phone_input, 
    OrderFSM.notes_input,
    OrderFSM.confirmation,
    OrderFSM.changing_phone
))
async def wrong_content_fsm_handler(message: types.Message) -> None:
    """Ловить невідповідний текст, стікери, фото, відео під час FSM і видаляє їх."""
    try:
        await message.delete()
    except Exception:
        pass
    await UIManager.show_toast(
        bot=message.bot,
        chat_id=message.chat.id,
        text="⚠️ <b>Будь ласка, надішли звичайний текст або використай кнопки!</b>",
        duration=3
    )

@router.callback_query(OrderFSM.notes_input, F.data == "skip_notes")
async def skip_notes_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Handle skip notes button."""
    logger.info(f"User {query.from_user.id} skipped notes")
    await state.update_data(notes="")
    await query.answer()
    await _show_confirmation(query.message, state, session=session)

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
                back_button_type="time" if bool(data.get("favorite_flow", False)) else "notes",
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
            back_button_type="time" if bool(data.get("favorite_flow", False)) else "notes",
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
        await UIManager.show_screen(
            bot=query.message.bot,
            session=session,
            chat_id=query.message.chat.id,
            text=MESSAGES["orders_paused"]
        )
        await state.clear()
        await state.update_data(current_view="orders_paused")
        return

    active_order, active_status = await _get_active_order_state(session=session, telegram_id=query.from_user.id)
    if active_order is not None:
        await query.answer()
        await _show_active_order_screen(query.message.bot, session, query.message.chat.id, active_order, active_status)
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
            from bot.keyboards.inline import get_orders_paused_keyboard
            await UIManager.show_screen(
                bot=query.message.bot,
                session=session,
                chat_id=query.message.chat.id,
                text=_format_closed_notice(nice_open, nice_close),
                markup=get_orders_paused_keyboard()
            )
            await query.answer()
            await state.clear()
            await state.update_data(current_view="closed")
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

    await UIManager.show_screen(
        bot=query.message.bot,
        session=session,
        chat_id=query.message.chat.id,
        text=MESSAGES["time_prompt"],
        markup=get_time_keyboard(),
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
            await UIManager.show_screen(
                bot=query.message.bot,
                session=session,
                chat_id=query.message.chat.id,
                text=MESSAGES["orders_paused"]
            )
            await state.clear()
            await state.update_data(current_view="orders_paused")
            return
            
        from datetime import datetime, time
        from bot.services.google_sheets import get_sheets_service
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
                from bot.keyboards.inline import get_orders_paused_keyboard
                await UIManager.show_screen(
                    bot=query.message.bot,
                    session=session,
                    chat_id=query.message.chat.id,
                    text=_format_closed_notice(nice_open, nice_close),
                    markup=get_orders_paused_keyboard()
                )
                await query.answer()
                await state.clear()
                await state.update_data(current_view="closed")
                return
        except Exception as e:
            logger.error(f"Error checking time in confirm_order_handler: {e}")

        active_order, active_status = await _get_active_order_state(session=session, telegram_id=query.from_user.id)
        if active_order is not None:
            await query.answer()
            await _show_active_order_screen(query.message.bot, session, query.message.chat.id, active_order, active_status)
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

        await query.answer()

        # Send notification to admin FIRST to get admin_msg_id
        from bot.services.notifications import AdminNotificationService
        notification_service = AdminNotificationService(bot)
        admin_msg_id = await notification_service.send_order_notification(
            order_number=order_number,
            customer_name=query.from_user.first_name,
            phone=phone,
            drink_name=drink.get("name", "Unknown"),
            volume_ml=drink.get("volume", 0),
            price=drink.get("price", 0),
            pickup_time=pickup_time,
            notes=notes,
            user_id=query.from_user.id
        )

        # Show success message (RECEIPT)
        pickup_time_str_display = pickup_time.strftime("%d.%m.%Y %H:%M") if pickup_time else "—"
        text = MESSAGES["success"].format(order_id=order.order_number, pickup_time=pickup_time_str_display)
        
        from bot.keyboards.inline import get_user_cancel_keyboard
        markup = get_user_cancel_keyboard(order_number=order_number, admin_msg_id=admin_msg_id or 0)

        receipt_msg = await UIManager.show_screen(
            bot=bot,
            session=session,
            chat_id=query.message.chat.id,
            text=text,
            markup=markup
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
    data = await state.get_data()
    menu = data.get("menu")
    user = await UserCRUD.get_by_telegram_id(session=session, telegram_id=query.from_user.id)

    active_order, active_status = await _get_active_order_state(session=session, telegram_id=query.from_user.id)
    if active_order is not None:
        await query.answer()
        await _show_active_order_screen(query.message.bot, session, query.message.chat.id, active_order, active_status)
        await state.clear()
        return

    if not menu:
        sheets_service = await get_sheets_service()
        menu = await sheets_service.get_menu()
        await state.update_data(menu=menu)

    keyboard = get_menu_keyboard(menu, favorite_drink_name=getattr(user, "favorite_drink_name", None))
    await UIManager.show_screen(
        bot=query.message.bot,
        session=session,
        chat_id=query.message.chat.id,
        text=MESSAGES["menu"].format(menu_items=_format_menu_items(menu)),
        markup=keyboard
    )
    await state.set_state(OrderFSM.menu_selection)
    await query.answer()


@router.callback_query(StateFilter(OrderFSM.phone_input), F.data == "back_to_time")
async def back_to_time_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    logger.info(f"User {query.from_user.id} went back to time input")
    await UIManager.show_screen(
        bot=query.message.bot,
        session=session,
        chat_id=query.message.chat.id,
        text=MESSAGES["time_prompt"],
        markup=get_time_keyboard(),
        force_reply_keyboard_remove=True
    )
    await state.set_state(OrderFSM.time_input)
    await query.answer()

@router.callback_query(StateFilter(OrderFSM.notes_input), F.data == "back_to_phone")
async def back_to_phone_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Go back from notes (to time input if phone was auto-skipped, or to phone input if manual)."""
    logger.info(f"User {query.from_user.id} went back from notes input")
    data = await state.get_data()

    if data.get("phone_autoskipped"):
        await UIManager.show_screen(
            bot=query.message.bot,
            session=session,
            chat_id=query.message.chat.id,
            text=MESSAGES["time_prompt"],
            markup=get_time_keyboard()
        )
        await state.set_state(OrderFSM.time_input)
        await query.answer()
        return

    await UIManager.show_screen(
        bot=query.message.bot,
        session=session,
        chat_id=query.message.chat.id,
        text=MESSAGES["phone_prompt"],
        markup=get_phone_reply_keyboard()
    )
    await state.set_state(OrderFSM.phone_input)
    await query.answer()

@router.callback_query(StateFilter(OrderFSM.confirmation), F.data == "back_to_notes")
async def back_to_notes_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Go back to notes input from confirmation."""
    logger.info(f"User {query.from_user.id} went back to notes input")
    await UIManager.show_screen(
        bot=query.message.bot,
        session=session,
        chat_id=query.message.chat.id,
        text=MESSAGES["notes_prompt"],
        markup=get_notes_keyboard()
    )
    await state.set_state(OrderFSM.notes_input)
    await query.answer()


@router.callback_query(StateFilter(OrderFSM.confirmation), F.data == "back_to_time")
async def back_to_time_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Go back to time input from confirmation (usually in favorite flow)."""
    logger.info(f"User {query.from_user.id} went back to time input")
    from bot.keyboards.inline import get_time_keyboard
    await UIManager.show_screen(
        bot=query.message.bot,
        session=session,
        chat_id=query.message.chat.id,
        text=MESSAGES["time_prompt"],
        markup=get_time_keyboard()
    )
    await state.set_state(OrderFSM.time_input)
    await query.answer()


# ==========================================
# ЧИСТИЛЬНИК СТАРИХ КНОПОК
# ==========================================


@router.message(F.text.in_({"☕ Ще одне замовлення", "☕ Переглянути меню", "☕️ Переглянути меню"}))
async def new_order_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Open the menu again from the bottom reply keyboard."""
    try:
        await message.delete()
    except Exception:
        pass
    logger.info(f"User {message.from_user.id} requested a new order")

    # ==========================================
    # 💥 ЗАХИСТ ВІД ДУБЛІВ МЕНЮ ТА ПЕРЕКРИТТЯ КРОКІВ
    current_state = await state.get_state()
    if current_state is not None:
        try:
            await message.delete()  # Очищаємо чат від зайвих команд
        except Exception:
            pass
            
        await UIManager.show_toast(
            bot=message.bot,
            chat_id=message.chat.id,
            text="⚠️ <b>Ти вже в процесі оформлення замовлення!</b>\n\nПродовж його вище або натисни команду /cancel, щоб скасувати його.",
            duration=5
        )
        return

    active_order, active_status = await _get_active_order_state(session=session, telegram_id=message.from_user.id)
    if active_order is not None:
        await _show_active_order_screen(message.bot, session, message.chat.id, active_order, active_status)
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
            from bot.keyboards.inline import get_orders_paused_keyboard
            await UIManager.show_screen(
                bot=message.bot,
                session=session,
                chat_id=message.chat.id,
                text=_format_closed_notice(nice_open, nice_close),
                markup=get_orders_paused_keyboard(),
                force_reply_keyboard_remove=True
            )
            await state.clear()
            await state.update_data(current_view="closed")
            return
    except Exception as parse_err:
        logger.error(f"Error parsing table times in new_order_handler: {parse_err}")

    await _send_menu(
        message,
        state,
        session,
        favorite_drink_name=getattr(user, "favorite_drink_name", None),
    )


@router.callback_query(F.data.startswith("usr_cancel:"))
async def user_cancel_active_order_handler(query: types.CallbackQuery, session: AsyncSession) -> None:
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
                await query.bot.edit_message_text(
                    chat_id=settings.admin_chat_id,
                    message_id=admin_msg_id,
                    text=f"❌ <b>Замовлення {order_number} скасовано клієнтом.</b>",
                    parse_mode="HTML",
                    reply_markup=None
                )
            except Exception as e:
                import logging
                logging.error(f"Не зміг відредагувати повідомлення адміна: {e}")
                # Якщо не вийшло відредагувати (наприклад повідомлення застаре), надсилаємо нове
                await query.bot.send_message(
                    chat_id=settings.admin_chat_id,
                    text=f"🚨 <b>УВАГА!</b> Клієнт самостійно скасував замовлення <b>{order_number}</b>!",
                    parse_mode="HTML"
                )
        else:
            # Якщо admin_msg_id = 0 (стара сесія), просто надсилаємо нове
            await query.bot.send_message(
                chat_id=settings.admin_chat_id,
                text=f"🚨 <b>УВАГА!</b> Клієнт самостійно скасував замовлення <b>{order_number}</b>!",
                parse_mode="HTML"
            )
        
        await UIManager.show_screen(
            bot=query.message.bot,
            session=session,
            chat_id=query.message.chat.id,
            text=f"❌ Ваше замовлення <b>{order_number}</b> успішно скасовано.\n\nЧекаємо вас наступного разу! ☕️",
            markup=get_start_menu_inline_keyboard()
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
async def admin_status_handler(query: types.CallbackQuery, session: AsyncSession) -> None:
    """Обробляє зміну статусу з динамічним оновленням ЄДИНОГО повідомлення у клієнта."""
    
    # Розпаковуємо дані
    parts = query.data.split(":")
    if len(parts) < 4:
        await query.answer("❌ Помилка даних кнопки", show_alert=True)
        return
        
    status_key = parts[1]
    order_number = parts[2]
    user_id = int(parts[3])

    # 1. ЗАХИСТ ВІД "МЕРТВИХ КНОПОК"
    sheets_service = None
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
    # 💥 НОВЕ: ЗНИЩУЄМО КНОПКУ У КЛІЄНТА НА ЧЕКУ
    # ==========================================
    # Якщо бариста натиснув будь-який статус, прибираємо кнопку з оригінального чека
    if status_key in ["acc", "prep", "rdy", "canc"]:
        try:
            from bot.database.crud import UserCRUD
            user = await UserCRUD.get_by_telegram_id(session, user_id)
            if user and user.last_bot_msg_id:
                # Змінюємо клавіатуру оригінального чека на None (порожнечу)
                await query.bot.edit_message_reply_markup(
                    chat_id=user_id, 
                    message_id=user.last_bot_msg_id, 
                    reply_markup=None
                )
        except Exception as e:
            pass
    # ==========================================
    
    status_name, client_message = STATUS_MAP.get(status_key, ("Невідомо", ""))
    
    # 2. Оновлюємо статус в Google Таблицях
    if sheets_service:
        try:
            await sheets_service.update_order_status(order_number, status_name)
        except Exception as e:
            import logging
            logging.error(f"Не вдалося оновити статус в таблиці: {e}")

    # 3. МАГІЯ ЄДИНОГО ВІКНА + PUSH-ПОВІДОМЛЕННЯ
    formatted_message = client_message.format(order_number=order_number)

    try:
        force_new_msg = status_key in ["rdy", "canc"]
        markup = get_new_order_inline_keyboard() if force_new_msg else None
        
        msg = await UIManager.show_screen(
            bot=query.message.bot,
            session=session,
            chat_id=user_id,
            text=formatted_message,
            markup=markup,
            force_new=force_new_msg
        )
        if msg:
            new_client_msg_id = msg.message_id

    except Exception as e:
        import logging
        logging.error(f"Не зміг оновити/відправити повідомлення клієнту {user_id}: {e}")

    # 4. Генеруємо нову клавіатуру для адміна
    new_keyboard = get_admin_order_keyboard(
        order_number, 
        user_id, 
        current_status=status_key
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

@router.callback_query(F.data == "view_menu_only")
async def view_menu_only_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Показує меню для перегляду, коли кав'ярня зачинена."""
    from bot.database.crud import SystemSettingCRUD
    from datetime import datetime, time
    
    from bot.services.google_sheets import get_sheets_service
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
            await query.answer("⚠️ Кав'ярня досі зачинена! Спробуйте натиснути пізніше.", show_alert=True)
            return
    except Exception as e:
        logger.error(f"Error checking time in view_menu: {e}")
        
    await query.answer()
    logger.info(f"User {query.from_user.id} requested to view menu while paused")
    
    from bot.database.crud import UserCRUD
    user = await UserCRUD.get_by_telegram_id(session, query.from_user.id)
    
    await _send_menu(
        message=query.message,
        state=state,
        session=session,
        favorite_drink_name=getattr(user, "favorite_drink_name", None),
        ignore_pause=False
    )

    # ==========================================
# ГЛОБАЛЬНИЙ ПЕРЕХОПЛЮВАЧ "МЕРТВИХ" КНОПОК
# ==========================================
@router.callback_query()
async def global_dead_callback_catcher(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """
    Ця функція ловить кліки по інлайн-кнопках від застарілих сесій.
    Видаляє накопичені підказки FSM та виводить чисте сповіщення про застарілу сесію.
    """
    try:
        await query.answer()  # Без popup алерта!
    except Exception:
        pass

    try:
        data = await state.get_data()

        # Видаляємо всі попередні повідомлення підказок FSM
        for msg_key in ("menu_msg_id", "time_prompt_msg_id", "phone_prompt_msg_id", "notes_prompt_msg_id", "warning_msg_id"):
            msg_id = data.get(msg_key)
            if msg_id and msg_id != query.message.message_id:
                try:
                    await query.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_id)
                except Exception:
                    pass

        await state.clear()
    except Exception as e:
        logger.error(f"Error cleaning dead callback session: {e}")

    text = (
        "🔌 <b>Сесія застаріла (можливо, бот щойно оновлювався).</b>\n\n"
        "Щоб зробити нове замовлення, натисни кнопку нижче ☕️"
    )
    markup = get_start_menu_inline_keyboard()
    
    await UIManager.show_screen(
        bot=query.message.bot,
        session=session,
        chat_id=query.message.chat.id,
        text=text,
        markup=markup,
    )

@router.message()
async def global_fallback_handler(message: types.Message) -> None:
    """Глобальний перехоплювач для будь-яких невідомих повідомлень, щоб зберігати чистоту чату (1-message UI)."""
    try:
        await message.delete()
    except Exception:
        pass