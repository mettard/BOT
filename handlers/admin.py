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
        from aiogram import Bot
        from bot.config import settings

        bot = Bot(token=settings.bot_token)
        notification_service = AdminNotificationService(bot)

        await notification_service.send_acknowledgement_confirmation(
            admin_chat_id=query.message.chat.id,
            message_id=query.message.message_id,
        )

        # 💥 СПОВІЩЕННЯ КЛІЄНТУ (Додали цей крок)
        try:
            await bot.send_message(
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
        from aiogram import Bot
        from bot.config import settings

        bot = Bot(token=settings.bot_token)
        notification_service = AdminNotificationService(bot)

        await notification_service.send_cancellation_confirmation(
            admin_chat_id=query.message.chat.id,
            message_id=query.message.message_id,
        )

        # 💥 СПОВІЩЕННЯ КЛІЄНТУ ПРО СКАСУВАННЯ (Додали цей крок)
        try:
            await bot.send_message(
                chat_id=order.telegram_id,
                text=f"❌ <b>На жаль, замовлення #{order_number} скасовано кав'ярнею.</b>\n\nДля уточнення деталей ви можете зв'язатися з адміністратором.",
                parse_mode="HTML"
            )
        except Exception as client_err:
            logger.error(f"Could not send cancellation to client {order.telegram_id}: {client_err}")

        await query.answer("❌ Замовлення скасовано", show_alert=False)
        logger.info(f"Order {order_number} cancelled successfully")

    except Exception as e:
        logger.error(f"Error in admin_cancel_handler: {e}")
        await query.answer("❌ Помилка при обробці замовлення", show_alert=True)