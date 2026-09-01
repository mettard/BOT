"""Pytest configuration and shared fixtures for CoffeeRun bot tests."""
import asyncio
import os
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from bot.config import settings
from bot.database.models import Base, Order, User


# Test database setup
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def async_engine():
    """Create async test database engine."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create async test database session."""
    async_session_maker = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def sample_user(async_session: AsyncSession) -> User:
    """Create sample user for testing."""
    user = User(
        telegram_id=123456789,
        first_name="Test",
        last_name="User",
        phone="+380501234567",
    )
    async_session.add(user)
    await async_session.commit()
    return user


@pytest_asyncio.fixture
async def sample_order(async_session: AsyncSession, sample_user: User) -> Order:
    """Create sample order for testing."""
    from datetime import datetime, timedelta

    order = Order(
        order_number="ORD-202406171530",
        telegram_id=sample_user.telegram_id,
        customer_name="Test User",
        phone="+380501234567",
        drink_name="Cappuccino",
        volume_ml=250,
        price=45.00,
        pickup_time=datetime.now() + timedelta(minutes=15),
        status="New",
    )
    async_session.add(order)
    await async_session.commit()
    return order


@pytest.fixture
def mock_sheets_service():
    """Mock Google Sheets service."""
    mock_service = AsyncMock()
    mock_service.get_menu = AsyncMock(
        return_value=[
            {
                "name": "Cappuccino",
                "volume": 250,
                "price": 45.00,
                "description": "Classic cappuccino",
            },
            {
                "name": "Latte",
                "volume": 300,
                "price": 50.00,
                "description": "Smooth latte",
            },
        ]
    )
    mock_service.append_order = AsyncMock(return_value=True)
    mock_service.update_order_status = AsyncMock(return_value=True)
    return mock_service


@pytest.fixture
def mock_aiogram_user():
    """Create mock aiogram User object."""
    user = MagicMock()
    user.id = 123456789
    user.first_name = "Test"
    user.last_name = "User"
    return user


@pytest.fixture
def mock_telegram_message(mock_aiogram_user):
    """Create mock Telegram message."""
    message = AsyncMock()
    message.from_user = mock_aiogram_user
    message.text = ""
    message.answer = AsyncMock()
    message.reply = AsyncMock()
    return message


@pytest.fixture
def mock_telegram_callback_query(mock_aiogram_user, mock_telegram_message):
    """Create mock Telegram callback query."""
    query = AsyncMock()
    query.from_user = mock_aiogram_user
    query.message = mock_telegram_message
    query.data = ""
    query.answer = AsyncMock()
    return query


@pytest.fixture
def mock_fsm_context():
    """Create mock FSM context."""
    context = AsyncMock()
    context.get_data = AsyncMock(return_value={})
    context.update_data = AsyncMock()
    context.set_state = AsyncMock()
    context.clear = AsyncMock()
    return context


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    """Mock settings for tests."""
    monkeypatch.setenv("BOT_TOKEN", "test_token_123")
    monkeypatch.setenv("ADMIN_CHAT_ID", "123456789")
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    monkeypatch.setenv("GOOGLE_SHEETS_KEY_FILE", "/fake/path/creds.json")
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "test_spreadsheet_id")
    monkeypatch.setenv("CAFE_OPEN_TIME", "09:00")
    monkeypatch.setenv("CAFE_CLOSE_TIME", "21:00")
    monkeypatch.setenv("MAX_ADVANCE_MINUTES", "720")
    
    # Also patch the already loaded settings object directly
    monkeypatch.setattr(settings, "bot_token", "test_token_123")
    monkeypatch.setattr(settings, "admin_chat_id", 123456789)
    monkeypatch.setattr(settings, "database_url", TEST_DB_URL)
    monkeypatch.setattr(settings, "google_sheets_key_file", "/fake/path/creds.json")
    monkeypatch.setattr(settings, "google_sheets_spreadsheet_id", "test_spreadsheet_id")
    monkeypatch.setattr(settings, "cafe_open_time", "09:00")
    monkeypatch.setattr(settings, "cafe_close_time", "21:00")
    monkeypatch.setattr(settings, "max_advance_minutes", 720)
