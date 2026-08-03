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

    async def notify_sheets_error(self, order_number: str) -> None:
        """Send notification about Google Sheets sync error."""
        try:
            await self.bot.send_message(
                chat_id=self.admin_chat_id,
                text=f"⚠️ <b>Помилка синхронізації з Таблицями!</b>\n\nНе вдалося оновити статус замовлення <b>#{order_number}</b> у Google Таблиці.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to send sheets error notification: {e}")

    async def notify_client_unreachable(self, order_number: str, phone: str, action_description: str) -> None:
        """Send notification when client cannot be messaged via Telegram."""
        try:
            await self.bot.send_message(
                chat_id=self.admin_chat_id,
                text=(
                    f"⚠️ <b>Клієнт недоступний!</b>\n\n"
                    f"Замовлення: <b>#{order_number}</b>\n"
                    f"Дія: <i>{action_description}</i>\n"
                    f"Зателефонуйте клієнту: <code>{phone}</code>"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to send client unreachable notification: {e}")

    async def notify_menu_load_error(self) -> None:
        """Send notification when Google Sheets menu fails to load."""
        try:
            await self.bot.send_message(
                chat_id=self.admin_chat_id,
                text="⚠️ <b>Помилка зчитування Меню!</b>\n\nНе вдалося зчитати позиції меню з Google Таблиці.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to send menu load error notification: {e}")

    async def notify_db_error(self, order_number: str) -> None:
        """Send notification when database query fails."""
        try:
            await self.bot.send_message(
                chat_id=self.admin_chat_id,
                text=f"⚠️ <b>Помилка Бази Даних!</b>\n\nНе вдалося зберегти/обробити замовлення <b>#{order_number}</b> у локальній БД.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to send DB error notification: {e}")
