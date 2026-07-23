"""Throttle middleware to suppress button mashing and message spam."""

from __future__ import annotations

import logging
from collections.abc import Callable
from time import monotonic
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)

class CallbackThrottleMiddleware(BaseMiddleware):
    """Suppress repeated interactions (messages/callbacks) from the same user."""

    def __init__(self, interval_seconds: float = 1.5) -> None:
        self.interval_seconds = interval_seconds
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Any],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        
        # Дістаємо користувача незалежно від того, це клік чи текст
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        user_id = user.id
        now = monotonic()
        last_seen = self._last_seen.get(user_id)

        # Якщо з минулої дії пройшло менше 1.5 секунди - блокуємо спам
        if last_seen is not None and (now - last_seen) < self.interval_seconds:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer() # Прибираємо годинник завантаження на кнопці
                except Exception:
                    pass
            logger.info(f"Blocked spam from user {user_id}")
            return None # 💥 Бот просто ігнорує цей дубль!

        self._last_seen[user_id] = now
        return await handler(event, data)