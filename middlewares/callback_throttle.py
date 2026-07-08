"""Callback query throttle middleware to suppress button mashing."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from collections.abc import Callable
from time import monotonic
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Update

logger = logging.getLogger(__name__)


class CallbackThrottleMiddleware(BaseMiddleware):
    """Suppress repeated callback queries from the same user within a short interval."""

    def __init__(self, interval_seconds: float = 0.75) -> None:
        self.interval_seconds = interval_seconds
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Any],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        callback = event if isinstance(event, CallbackQuery) else None
        if callback is None or callback.from_user is None:
            return await handler(event, data)

        user_id = callback.from_user.id
        now = monotonic()
        last_seen = self._last_seen.get(user_id)

        if last_seen is not None and (now - last_seen) < self.interval_seconds:
            try:
                await callback.answer()
            except Exception:
                logger.debug("Failed to answer throttled callback", exc_info=True)
            return None

        self._last_seen[user_id] = now
        return await handler(event, data)
