from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot, types
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import UserCRUD

logger = logging.getLogger(__name__)


class UIManager:
    """Centralized UI Manager to enforce 1-message UI."""

    @staticmethod
    async def show_screen(
        bot: Bot,
        session: AsyncSession,
        chat_id: int,
        text: str,
        markup: Optional[InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove] = None,
        force_reply_keyboard_remove: bool = False,
        force_new: bool = False,
    ) -> types.Message:
        """
        Displays a persistent screen.
        Tries to edit the existing message to prevent flickering, unless a ReplyKeyboard is required.
        Always tracks the active message ID in the database.
        """
        user = await UserCRUD.get_by_telegram_id(session, chat_id)
        last_msg_id = user.last_bot_msg_id if user else None

        requires_new_message = force_new or isinstance(markup, (ReplyKeyboardMarkup, ReplyKeyboardRemove)) or force_reply_keyboard_remove
        new_msg = None

        if last_msg_id and not requires_new_message:
            try:
                msg = await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=last_msg_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                if isinstance(msg, types.Message):
                    new_msg = msg
                else:
                    return types.Message(message_id=last_msg_id, date=None, chat=types.Chat(id=chat_id, type="private"))
            except Exception as e:
                # Fallback to delete and send new if edit fails (e.g. message too old or deleted)
                logger.debug(f"Failed to edit message {last_msg_id}, falling back to new message: {e}")
                requires_new_message = True

        if requires_new_message or not last_msg_id:
            if last_msg_id:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=last_msg_id)
                except Exception:
                    pass

            if force_reply_keyboard_remove:
                # Send with ReplyKeyboardRemove, then instantly edit to attach the actual markup
                new_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove(),
                )
                if markup:
                    try:
                        await bot.edit_message_reply_markup(
                            chat_id=chat_id,
                            message_id=new_msg.message_id,
                            reply_markup=markup
                        )
                    except Exception as edit_err:
                        logger.error(f"Failed to add markup after ReplyKeyboardRemove: {edit_err}")
            else:
                new_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )

            # Update DB with new message ID
            if new_msg:
                await UserCRUD.update_last_bot_msg_id(session, chat_id, new_msg.message_id)

        return new_msg

    @staticmethod
    async def show_toast(
        bot: Bot,
        chat_id: int,
        text: str,
        duration: int = 4,
    ) -> None:
        """
        Displays a temporary message (toast) that deletes itself after a duration.
        Does NOT update the last_bot_msg_id, so the main screen remains intact.
        """
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
            )

            async def delete_later():
                await asyncio.sleep(duration)
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
                except Exception:
                    pass

            asyncio.create_task(delete_later())
        except Exception as e:
            logger.error(f"Failed to send toast: {e}")
