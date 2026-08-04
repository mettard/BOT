"""Main entry point for CoffeeRun bot."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.database.engine import engine
from bot.database.models import Base
from bot.handlers import admin, order, history
from bot.middlewares.callback_throttle import CallbackThrottleMiddleware
from bot.middlewares.db_session import DbSessionMiddleware

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


from aiogram.types import BotCommand


async def set_bot_commands(bot: Bot) -> None:
    """Register bot commands menu in Telegram."""
    commands = [
        BotCommand(command="start", description="☕ Відкрити меню замовлення"),
        BotCommand(command="orders", description="📜 Історія замовлень"),
        BotCommand(command="phone", description="📱 Змінити номер телефону"),
        BotCommand(command="cancel", description="❌ Скасувати замовлення"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as e:
        logger.error(f"Error setting bot commands: {e}")


async def on_startup(bot: Bot) -> None:
    """Initialize database and commands on startup."""
    logger.info("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")
    await set_bot_commands(bot)


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
        dp.message.middleware(CallbackThrottleMiddleware(interval_seconds=1.0))
        dp.callback_query.middleware(CallbackThrottleMiddleware())
        dp.message.middleware(DbSessionMiddleware())
        dp.callback_query.middleware(DbSessionMiddleware())

        # Register routers (admin first, then order)
        dp.include_router(admin.router)
        dp.include_router(history.router)
        dp.include_router(order.router)

        # Startup
        await on_startup(bot)

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
