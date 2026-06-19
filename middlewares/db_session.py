"""Database session middleware for injecting session into context."""

import logging
from typing import Any, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, Update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.engine import AsyncSessionLocal

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Middleware for injecting database session into handler context."""

    async def __call__(
        self,
        handler: Callable,
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        """Inject session into context.
        
        Args:
            handler: Next handler
            event: Update event
            data: Context data
            
        Returns:
            Handler result
        """
        async with AsyncSessionLocal() as session:
            data["session"] = session
            return await handler(event, data)
