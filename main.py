"""Main entry point for CoffeeRun bot."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.database.engine import engine
from bot.database.models import Base
from bot.handlers import admin, order
from bot.middlewares.db_session import DbSessionMiddleware

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def on_startup() -> None:
    """Initialize database on startup."""
    logger.info("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")


async def on_shutdown() -> None:
    """Cleanup on shutdown."""
    logger.info("Shutting down bot...")
    await engine.dispose()


async def main() -> None:
    """Main bot entry point."""
    try:
        # Initialize bot and dispatcher
        bot = Bot(token=settings.bot_token)
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)

        # Register middleware
        dp.message.middleware(DbSessionMiddleware())
        dp.callback_query.middleware(DbSessionMiddleware())

        # Register routers (admin first, then order)
        dp.include_router(admin.router)
        dp.include_router(order.router)

        # Startup
        await on_startup()

        # Start polling
        logger.info("Starting bot polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
