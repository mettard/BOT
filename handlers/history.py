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
    from bot.handlers.order import _get_active_order_state
    from bot.services.ui_manager import UIManager
    from bot.states.order import OrderFSM
    
    active_order, _ = await _get_active_order_state(session=session, telegram_id=user_id)
    
    if (current_state is not None and current_state != OrderFSM.menu_selection.state) or active_order is not None:
        # Клієнт в процесі замовлення (але не просто в меню) або вже очікує на напій
        await UIManager.show_toast(
            bot=message.bot,
            chat_id=user_id,
            text="⚠️ <b>Ти вже в процесі замовлення.</b>\nЗакінчи або скасуй його, щоб переглянути історію.",
            duration=4
        )
        return
        
    await state.clear()

    # Отримуємо останні замовлення
    recent_orders = await OrderCRUD.get_by_telegram_id_recent(session, telegram_id=user_id, limit=10)
    
    if not recent_orders:
        history_text = "У тебе ще немає історії замовлень ☕️"
    else:
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
    
    await UIManager.show_screen(
        bot=message.bot,
        session=session,
        chat_id=user_id,
        text=history_text,
        markup=get_close_history_keyboard()
    )

@router.callback_query(F.data == "close_history")
async def close_history_handler(query: types.CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Відновлює головне меню замість історії."""
    await query.answer()
    
    from bot.handlers.order import start_handler
    
    # Викликаємо start_handler, який автоматично відновить правильний екран (меню або паузу)
    # через наш новий UIManager
    await start_handler(query.message, state, session, is_callback=True)
