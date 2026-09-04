"""Admin handler for order management."""

import logging

from aiogram import F, Router, types
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import OrderCRUD
from bot.services.google_sheets import get_sheets_service
from bot.services.notifications import AdminNotificationService

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("admin_ack_"))
async def admin_acknowledge_handler(
    query: types.CallbackQuery, session: AsyncSession
) -> None:
    """Handle admin acknowledgement of order."""
    logger.info(f"Admin {query.from_user.id} acknowledged order")

    try:
        # Extract order number from callback data
        order_number = query.data.split("admin_ack_")[1]

        # Update order status in DB
        order = await OrderCRUD.update_status(session=session, order_number=order_number, status="Ready")

        if not order:
            await query.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        # Update in Google Sheets
        sheets_service = await get_sheets_service()
        await sheets_service.update_order_status(order_number=order_number, status="Ready")

        # Update notification message
        notification_service = AdminNotificationService(query.bot)

        await notification_service.send_acknowledgement_confirmation(
            admin_chat_id=query.message.chat.id,
            message_id=query.message.message_id,
        )

        # Сповіщення клієнту про прийняття
        try:
            await query.bot.send_message(
                chat_id=order.telegram_id,
                text=f"☕️ <b>Ваше замовлення #{order_number} прийнято!</b>\n\nБариста вже готує вашу каву. Очікуйте на вказаний час! 🎉",
                parse_mode="HTML"
            )
        except Exception as client_err:
            logger.error(f"Could not send message to client {order.telegram_id}: {client_err}")

        await query.answer("✅ Замовлення прийнято", show_alert=False)
        logger.info(f"Order {order_number} acknowledged successfully")

    except Exception as e:
        logger.error(f"Error in admin_acknowledge_handler: {e}")
        await query.answer("❌ Помилка при обробці замовлення", show_alert=True)


@router.callback_query(F.data.startswith("admin_cancel_"))
async def admin_cancel_handler(query: types.CallbackQuery, session: AsyncSession) -> None:
    """Handle admin cancellation of order."""
    logger.info(f"Admin {query.from_user.id} cancelled order")

    try:
        # Extract order number from callback data
        order_number = query.data.split("admin_cancel_")[1]

        # Update order status in DB
        order = await OrderCRUD.update_status(session=session, order_number=order_number, status="Canceled")

        if not order:
            await query.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        # Update in Google Sheets
        sheets_service = await get_sheets_service()
        await sheets_service.update_order_status(order_number=order_number, status="Canceled")

        # Update notification message
        notification_service = AdminNotificationService(query.bot)

        await notification_service.send_cancellation_confirmation(
            admin_chat_id=query.message.chat.id,
            message_id=query.message.message_id,
        )

        # Сповіщення клієнту про скасування
        try:
            await query.bot.send_message(
                chat_id=order.telegram_id,
                text=f"❌ <b>Ваше замовлення #{order_number} було скасовано.</b>\n\nЯкщо у вас є питання, зверніться до баристи.",
                parse_mode="HTML"
            )
        except Exception as client_err:
            logger.error(f"Could not send message to client {order.telegram_id}: {client_err}")

        await query.answer("❌ Замовлення скасовано", show_alert=False)
        logger.info(f"Order {order_number} cancelled successfully")

    except Exception as e:
        logger.error(f"Error in admin_cancel_handler: {e}")
        await query.answer("❌ Помилка при обробці замовлення", show_alert=True)


from aiogram.filters import Command
from bot.config import settings
from bot.database.crud import SystemSettingCRUD, WaitlistCRUD
from bot.keyboards.inline import get_admin_stop_orders_reply_keyboard


def is_admin(user_id: int, chat_id: int) -> bool:
    """Check if message is from an admin user or admin chat."""
    return user_id == settings.admin_chat_id or chat_id == settings.admin_chat_id


@router.message(Command("admin"))
async def admin_panel_handler(message: types.Message, session: AsyncSession) -> None:
    """Show admin panel keyboard."""
    if not is_admin(message.from_user.id, message.chat.id):
        return

    is_paused = await SystemSettingCRUD.is_orders_paused(session)
    status_text = "⏸ <b>Прийом замовлень призупинено</b>" if is_paused else "✅ <b>Прийом замовлень активний</b>"
    keyboard = get_admin_stop_orders_reply_keyboard(is_paused=is_paused)

    await message.answer(
        f"⚙️ <b>Панель адміністратора CoffeeRun</b>\n\nПоточний стан: {status_text}",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


@router.message(F.text == "🛑 Стоп-прийом")
@router.message(Command("stop_orders"))
async def stop_orders_handler(message: types.Message, session: AsyncSession) -> None:
    """Pause order intake."""
    if not is_admin(message.from_user.id, message.chat.id):
        return

    await SystemSettingCRUD.set_orders_paused(session, paused=True)
    keyboard = get_admin_stop_orders_reply_keyboard(is_paused=True)

    await message.answer(
        "🛑 <b>Прийом замовлень призупинено (Стоп-Прийом активовано).</b>\n\n"
        "Клієнти, які намагатимуться зробити замовлення, будуть додані до списку очікування і отримають сповіщення при відновленні.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    logger.info(f"Admin {message.from_user.id} enabled stop-orders mode.")


@router.message(F.text == "▶️ Відновити прийом")
@router.message(Command("start_orders"))
async def resume_orders_handler(message: types.Message, session: AsyncSession) -> None:
    """Resume order intake and notify waiting clients."""
    if not is_admin(message.from_user.id, message.chat.id):
        return

    await SystemSettingCRUD.set_orders_paused(session, paused=False)
    keyboard = get_admin_stop_orders_reply_keyboard(is_paused=False)

    # Fetch waiting clients
    waiting_users = await WaitlistCRUD.pop_waitlist_users(session)

    # Send notifications to waiting clients
    notified_count = 0

    from bot.keyboards.inline import get_start_menu_inline_keyboard

    client_keyboard = get_start_menu_inline_keyboard()

    from bot.services.ui_manager import UIManager

    for user_id in waiting_users:
        try:
            await UIManager.show_screen(
                bot=message.bot,
                session=session,
                chat_id=user_id,
                text="☕️ <b>Кав'ярня знову приймає замовлення!</b>\n\nЗапрошуємо обрати свій улюблений напій. Натисніть кнопку внизу! 🎉",
                markup=client_keyboard,
                force_new=True
            )
            notified_count += 1
        except Exception as e:
            logger.error(f"Could not notify waiting user {user_id}: {e}")

    await message.answer(
        f"▶️ <b>Прийом замовлень відновлено!</b>\n\n"
        f"Сповіщено очікуючих клієнтів: <b>{notified_count}</b>.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    logger.info(f"Admin {message.from_user.id} resumed orders. Notified {notified_count} users.")