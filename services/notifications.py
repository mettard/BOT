"""Admin notifications service."""

import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import settings
from bot.keyboards.inline import get_admin_order_keyboard

logger = logging.getLogger(__name__)


class AdminNotificationService:
    """Service for sending admin notifications."""

    def __init__(self, bot: Bot) -> None:
        """Initialize notification service.
        
        Args:
            bot: aiogram Bot instance
        """
        self.bot = bot
        self.admin_chat_id = settings.admin_chat_id

    async def send_order_notification(
        self,
        order_number: str,
        customer_name: str,
        phone: str,
        drink_name: str,
        volume_ml: int,
        price: float,
        pickup_time: datetime,
        notes: str = "",
        user_id: int = 0,
        receipt_msg_id: int = 0,
    ) -> int | None:
        """Send order notification to admin chat.
        
        Args:
            order_number: Order ID
            customer_name: Customer name
            phone: Phone number
            drink_name: Drink name
            volume_ml: Volume in ml
            price: Price in UAH
            pickup_time: Pickup time
            notes: Additional notes
            receipt_msg_id: Message ID of the receipt
        Returns:
            Message ID if sent successfully, None otherwise
        """
        try:
            # Format pickup time
            pickup_str = pickup_time.strftime("%Y-%m-%d %H:%M:%S")
            notes_text = f"📝 <b>Побажання:</b> <i>{notes}</i>\n\n" if notes else ""
            # Build message text (HTML format)
            message = (
                f"📋 <b>Нове замовлення</b>\n\n"
                f"<b>ID замовлення:</b> {order_number}\n"
                f"<b>Час отримання:</b> {pickup_str}\n\n"
                f"👤 <b>Клієнт:</b> {customer_name}\n"
                f"📱 <b>Телефон:</b> <code>{phone}</code>\n\n"
                f"☕ <b>Напій:</b> {drink_name} ({volume_ml}ml)\n"
                f"💰 <b>Ціна:</b> ₴{price}\n\n"
                f"{notes_text}"
                f"🔔 <b>Статус:</b> 🆕 Нове"
            )

            # Build inline keyboard
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✓ Прийняти",
                            callback_data=f"admin_ack_{order_number}",
                        ),
                        InlineKeyboardButton(
                            text="✗ Скасувати",
                            callback_data=f"admin_cancel_{order_number}",
                        ),
                    ]
                ]
            )

            keyboard = get_admin_order_keyboard(order_number, user_id, receipt_msg_id=receipt_msg_id)
            # Send message
            msg = await self.bot.send_message(
                chat_id=self.admin_chat_id,
                text=message,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

            logger.info(f"Order notification sent for {order_number}, message_id: {msg.message_id}")
            return msg.message_id

        except Exception as e:
            logger.error(f"Error sending order notification: {e}")
            return None

    async def send_acknowledgement_confirmation(self, admin_chat_id: int, message_id: int) -> bool:
        """Send acknowledgement confirmation to admin.
        
        Args:
            admin_chat_id: Admin chat ID
            message_id: Message ID to edit
            
        Returns:
            True if successful
        """
        try:
            await self.bot.edit_message_text(
                chat_id=admin_chat_id,
                message_id=message_id,
                text="✅ Замовлення прийнято. Готуємо!",
                parse_mode="HTML",
            )
            return True
        except Exception as e:
            logger.error(f"Error sending acknowledgement: {e}")
            return False

    async def send_cancellation_confirmation(self, admin_chat_id: int, message_id: int) -> bool:
        """Send cancellation confirmation to admin.
        
        Args:
            admin_chat_id: Admin chat ID
            message_id: Message ID to edit
            
        Returns:
            True if successful
        """
        try:
            await self.bot.edit_message_text(
                chat_id=admin_chat_id,
                message_id=message_id,
                text="❌ Замовлення скасовано.",
                parse_mode="HTML",
            )
            return True
        except Exception as e:
            logger.error(f"Error sending cancellation: {e}")
            return False
