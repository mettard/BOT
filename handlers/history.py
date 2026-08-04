"""History command handler."""
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.crud import OrderCRUD

logger = logging.getLogger(__name__)
router = Router()

def get_close_history_keyboard() -> types.InlineKeyboardMarkup:
    """Кнопка для закриття історії."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Закрити", callback_data="close_history")
    return builder.as_markup()

@router.message(Command("orders"))
async def history_command_handler(message: types.Message, state: FSMContext, session: AsyncSession) -> None:
    """Показує історію замовлень клієнта."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested order history")

    try:
        await message.delete()  # Видаляємо команду /orders для чистоти
    except Exception:
        pass

    current_state = await state.get_state()
    from bot.handlers.order import _clear_warning, _get_active_order_state
    
    active_order, _ = await _get_active_order_state(session=session, telegram_id=user_id)
    
    if current_state is not None or active_order is not None:
        # Клієнт в процесі замовлення або вже очікує на напій
        await _clear_warning(message, state)
        warning_msg = await message.answer(
            "⚠️ <b>Закінчи або дочекайся поточного замовлення перед тим, як переглядати історію.</b>",
            parse_mode="HTML"
        )
        await state.update_data(warning_msg_id=warning_msg.message_id)
        return

    # Отримуємо останні замовлення
    recent_orders = await OrderCRUD.get_by_telegram_id_recent(session, telegram_id=user_id, limit=10)
    
    if not recent_orders:
        await message.answer(
            "У тебе ще немає історії замовлень ☕️",
            reply_markup=get_close_history_keyboard()
        )
        return

    history_lines = ["📜 <b>Твої останні замовлення:</b>\n"]
    for order in recent_orders:
        date_str = order.created_at.strftime("%d.%m.%Y")
        
        status_map = {
            "New": "⏳ Нове",
            "Прийнято": "🟡 Прийнято",
            "Готується": "🔥 Готується",
            "Готово": "✅ Готово",
            "Скасовано": "❌ Скасовано",
        }
        status_emoji = status_map.get(order.status, order.status)
        
        history_lines.append(f"📅 {date_str} | ☕ {order.drink_name} | 💵 {order.price:g} грн | {status_emoji}")

    history_text = "\n\n".join(history_lines)
    
    history_msg = await message.answer(
        history_text,
        parse_mode="HTML",
        reply_markup=get_close_history_keyboard()
    )
    await state.update_data(history_msg_id=history_msg.message_id)

@router.callback_query(F.data == "close_history")
async def close_history_handler(query: types.CallbackQuery, state: FSMContext) -> None:
    """Закриває повідомлення з історією."""
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass
    await state.update_data(history_msg_id=None)
