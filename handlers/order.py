"""Order handling router with FSM flow."""

import logging
from datetime import datetime, time
from typing import Any

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram.types import ReplyKeyboardRemove
from datetime import timedelta

from bot.database.crud import OrderCRUD, UserCRUD
from bot.keyboards.inline import (
    get_confirmation_keyboard, 
    get_menu_keyboard, 
    get_back_to_menu_keyboard, 
    get_back_to_time_keyboard,
    get_notes_keyboard,  # Додано нову клавіатуру
    get_time_keyboard,          # ДОДАЛИ
    get_phone_reply_keyboard    # ДОДАЛИ
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
        "⏰ <b>Коли ти забираш замовлення?</b>\n\n"
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
}


@router.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Handle /start command - display menu."""
    logger.info(f"User {message.from_user.id} started bot")

    try:
        await UserCRUD.get_or_create(
            session=session,
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )

        sheets_service = await get_sheets_service()
        menu = await sheets_service.get_menu()

        if not menu:
            await message.answer(MESSAGES["menu_empty"], parse_mode="HTML")
            return

        menu_items_text = ""
        for item in menu:
            menu_items_text += f"☕️ <b>{item['name']}</b> {item['volume']}ml — {item['price']} ₴\n"

        keyboard = get_menu_keyboard(menu)
        await message.answer(
            MESSAGES["menu"].format(menu_items=menu_items_text),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        await state.update_data(menu=menu)
        await state.set_state(OrderFSM.menu_selection)

    except Exception as e:
        logger.error(f"Error in start_handler: {e}")
        await message.answer("⚠️ Технічна помилка. Спробуй ще раз за хвилину.", parse_mode="HTML")


@router.callback_query(OrderFSM.menu_selection, F.data.startswith("drink_"))
async def drink_selected_handler(
    query: types.CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Handle drink selection with instant shop status check."""
    logger.info(f"User {query.from_user.id} selected drink")

    try:
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
                
                await query.message.answer(
                    f"⏸ <b>На жаль, кав'ярня зараз зачинена.</b>\n\n"
                    f"Ми приймаємо замовлення лише в робочий час з <code>{nice_open}</code> до <code>{nice_close}</code>.\n"
                    f"Завітайте до нас пізніше! ☕️",
                    parse_mode="HTML"
                )
                await query.answer()
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
        await state.update_data(selected_drink=drink)
        
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
async def quick_time_handler(query: types.CallbackQuery, state: FSMContext) -> None:
    minutes = int(query.data.split(":")[1])
    pickup_time = datetime.now() + timedelta(minutes=minutes)
    
    await state.update_data(pickup_time=pickup_time)
    await query.message.edit_reply_markup(reply_markup=None)
    
    # Трюк з двома повідомленнями
    await query.message.answer("👇 Для швидкого замовлення натисніть кнопку внизу:", reply_markup=get_phone_reply_keyboard())
    await query.message.answer(MESSAGES["phone_prompt"], parse_mode="HTML", reply_markup=get_back_to_time_keyboard())
    
    await state.set_state(OrderFSM.phone_input)
    await query.answer()

@router.message(OrderFSM.time_input)
async def time_input_handler(message: types.Message, state: FSMContext) -> None:
    """Handle time input."""
    logger.info(f"User {message.from_user.id} entered time: {message.text}")

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

        await state.update_data(pickup_time=pickup_time)
        await message.answer(MESSAGES["phone_prompt"], parse_mode="HTML", reply_markup=get_back_to_time_keyboard())
        await state.set_state(OrderFSM.phone_input)

    except Exception as e:
        logger.error(f"Error in time_input_handler: {e}")
        await state.update_data(pickup_time=pickup_time)
        
        await message.answer("👇 Для швидкого замовлення натисніть кнопку внизу:", reply_markup=get_phone_reply_keyboard())
        await message.answer(MESSAGES["phone_prompt"], parse_mode="HTML", reply_markup=get_back_to_time_keyboard())
        
        await state.set_state(OrderFSM.phone_input)


@router.message(OrderFSM.phone_input)
async def phone_input_handler(message: types.Message, state: FSMContext) -> None:
    logger.info(f"User {message.from_user.id} entered phone")
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

        # Непомітно прибираємо нижню клавіатуру
        remove_msg = await message.answer("⏳", reply_markup=ReplyKeyboardRemove())
        await remove_msg.delete()

        await message.answer(MESSAGES["notes_prompt"], parse_mode="HTML", reply_markup=get_notes_keyboard())
        await state.set_state(OrderFSM.notes_input)

    except Exception as e:
        logger.error(f"Error in phone_input_handler: {e}")
        await message.answer(MESSAGES["invalid_phone"], parse_mode="HTML")
# ==========================================
# ХЕНДЛЕРИ КОМЕНТАРІВ (НОВІ)
# ==========================================

async def _show_confirmation(message_or_query: types.Message | types.CallbackQuery, state: FSMContext):
    """Helper to generate and show the confirmation screen."""
    data = await state.get_data()
    drink = data.get("selected_drink", {})
    pickup_time = data.get("pickup_time")
    notes = data.get("notes", "")

    pickup_time_str = pickup_time.strftime("%d.%m.%Y %H:%M") if pickup_time else "—"
    notes_text = f"📝 Побажання: <b>{notes}</b>\n\n" if notes else ""

    confirmation_text = MESSAGES["confirmation"].format(
        drink_name=drink.get("name", "—"),
        volume=drink.get("volume", "—"),
        price=drink.get("price", "—"),
        pickup_time=pickup_time_str,
        notes_text=notes_text
    )

    keyboard = get_confirmation_keyboard()

    if isinstance(message_or_query, types.CallbackQuery):
        await message_or_query.message.edit_text(confirmation_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message_or_query.answer(confirmation_text, parse_mode="HTML", reply_markup=keyboard)

    await state.set_state(OrderFSM.confirmation)

@router.message(OrderFSM.notes_input)
async def notes_input_handler(message: types.Message, state: FSMContext) -> None:
    """Handle text notes input."""
    logger.info(f"User {message.from_user.id} entered notes")
    await state.update_data(notes=message.text.strip())
    await _show_confirmation(message, state)

@router.callback_query(OrderFSM.notes_input, F.data == "skip_notes")
async def skip_notes_handler(query: types.CallbackQuery, state: FSMContext) -> None:
    """Handle skip notes button."""
    logger.info(f"User {query.from_user.id} skipped notes")
    await state.update_data(notes="")
    await query.answer()
    await _show_confirmation(query, state)

# ==========================================

@router.callback_query(OrderFSM.confirmation, F.data == "confirm_order")
async def confirm_order_handler(
    query: types.CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Handle order confirmation."""
    logger.info(f"User {query.from_user.id} confirmed order")

    try:
        data = await state.get_data()
        drink = data.get("selected_drink", {})
        pickup_time = data.get("pickup_time")
        phone = data.get("phone")
        notes = data.get("notes", "")

        order_number = generate_order_number()

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
            notes=notes, # Передаємо коментар у Google Sheets
        )

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
            notes=notes, # Передаємо коментар в адмінську групу
            user_id=query.from_user.id,
        )

        pickup_time_str_display = pickup_time.strftime("%d.%m.%Y %H:%M") if pickup_time else "—"
        success_text = MESSAGES["success"].format(
            order_id=order_number,
            pickup_time=pickup_time_str_display,
        )

        await query.answer()
        await query.message.edit_text(success_text, parse_mode="HTML")

        await state.clear()
        logger.info(f"Order {order_number} created successfully")

    except Exception as e:
        logger.error(f"Error in confirm_order_handler: {e}")
        await query.answer("❌ Помилка при збереженні замовлення", show_alert=True)

# ==========================================
# ХЕНДЛЕРИ КНОПОК "НАЗАД"
# ==========================================

@router.callback_query(StateFilter(OrderFSM.time_input), F.data == "back_to_menu")
async def back_to_menu_handler(query: types.CallbackQuery, state: FSMContext) -> None:
    logger.info(f"User {query.from_user.id} went back to menu")
    data = await state.get_data()
    menu = data.get("menu")

    if not menu:
        sheets_service = await get_sheets_service()
        menu = await sheets_service.get_menu()
        await state.update_data(menu=menu)

    menu_items_text = ""
    for item in menu:
        menu_items_text += f"☕️ <b>{item['name']}</b> {item['volume']}ml — {item['price']} ₴\n"

    keyboard = get_menu_keyboard(menu)
    await query.message.edit_text(
        MESSAGES["menu"].format(menu_items=menu_items_text),
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await state.set_state(OrderFSM.menu_selection)
    await query.answer()


@router.callback_query(StateFilter(OrderFSM.phone_input), F.data == "back_to_time")
async def back_to_time_handler(query: types.CallbackQuery, state: FSMContext) -> None:
    logger.info(f"User {query.from_user.id} went back to time input")
    
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
    """Go back to phone input from notes."""
    logger.info(f"User {query.from_user.id} went back to phone input")
    await query.message.edit_text(
        MESSAGES["phone_prompt"],
        parse_mode="HTML",
        reply_markup=get_back_to_time_keyboard()
    )
    await state.set_state(OrderFSM.phone_input)
    await query.answer()


@router.callback_query(StateFilter(OrderFSM.confirmation), F.data == "back_to_notes")
async def back_to_notes_handler(query: types.CallbackQuery, state: FSMContext) -> None:
    """Go back to notes input from confirmation."""
    logger.info(f"User {query.from_user.id} went back to notes input")
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

@router.callback_query(F.data.in_(["back_to_menu", "back_to_time", "back_to_phone", "back_to_notes"]))
async def outdated_back_buttons_handler(query: types.CallbackQuery) -> None:
    """Catch clicks on old back buttons from chat history and remove them."""
    await query.answer("⏳ Цей крок вже пройдено", show_alert=False)
    await query.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.in_(["cancel_order", "cancel_flow"]))
@router.callback_query(OrderFSM.menu_selection, F.data == "cancel_order")
@router.callback_query(OrderFSM.time_input, F.data == "cancel_order")
@router.callback_query(OrderFSM.phone_input, F.data == "cancel_order")
@router.callback_query(OrderFSM.notes_input, F.data == "cancel_order")
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
            await query.message.edit_reply_markup(reply_markup=None)
            await query.message.answer(MESSAGES["cancelled"], parse_mode="HTML")
        else:
            message = message_or_query
            await message.answer(MESSAGES["cancelled"], parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in cancel_handler: {e}")


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
    
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer("❌ Помилка даних кнопки", show_alert=True)
        return
        
    _, status_key, order_number, user_id_str, client_msg_id_str = parts
    user_id = int(user_id_str)
    client_msg_id = int(client_msg_id_str)
    
    status_name, client_message = STATUS_MAP.get(status_key, ("Невідомо", ""))
    
    # 1. Оновлюємо статус в Google Таблицях
    try:
        from bot.services.google_sheets import get_sheets_service
        sheets_service = await get_sheets_service()
        await sheets_service.update_order_status(order_number, status_name)
    except Exception as e:
        logger.error(f"Не вдалося оновити статус в таблиці: {e}")

    # 2. МАГІЯ ЄДИНОГО ВІКНА + PUSH-ПОВІДОМЛЕННЯ
    formatted_message = client_message.format(order_number=order_number)
    new_client_msg_id = client_msg_id

    try:
        if status_key in ["rdy", "canc"]:
            # Коли кава ГОТОВА або СКАСОВАНА — ВИДАЛЯЄМО старе повідомлення і ВІДПРАВЛЯЄМО нове.
            # Це гарантовано викличе гучний PUSH на телефоні клієнта!
            if client_msg_id != 0:
                try:
                    await query.bot.delete_message(chat_id=user_id, message_id=client_msg_id)
                except Exception:
                    pass  # Якщо клієнт випадково сам видалив повідомлення, просто ігноруємо помилку
            
            msg = await query.bot.send_message(chat_id=user_id, text=formatted_message, parse_mode="HTML")
            new_client_msg_id = msg.message_id

        elif client_msg_id == 0:
            # Це перший крок (Прийнято) — відправляємо перше повідомлення (теж PUSH 🔔)
            msg = await query.bot.send_message(chat_id=user_id, text=formatted_message, parse_mode="HTML")
            new_client_msg_id = msg.message_id
            
        else:
            # Крок "Готується" — просто тихо оновлюємо текст (Беззвучно 🔕)
            await query.bot.edit_message_text(
                chat_id=user_id,
                message_id=client_msg_id,
                text=formatted_message,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Не зміг оновити/відправити повідомлення клієнту {user_id}: {e}")

    # 3. Генеруємо нову клавіатуру для адміна, зберігаючи новий ID повідомлення
    new_keyboard = get_admin_order_keyboard(
        order_number, 
        user_id, 
        current_status=status_key, 
        client_msg_id=new_client_msg_id
    )
    
    # 4. Оновлюємо адмінську картку баристи
    old_text = query.message.html_text
    new_text = re.sub(r"🔔 <b>Статус:</b>.*", f"🔔 <b>Статус:</b> {status_name}", old_text)
    
    await query.message.edit_text(new_text, parse_mode="HTML", reply_markup=new_keyboard)
    await query.answer(f"Статус змінено на {status_name}.")