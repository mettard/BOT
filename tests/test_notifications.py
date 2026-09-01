"""Tests for AdminNotificationService operational error alerts."""

import pytest
from unittest.mock import AsyncMock, patch
from bot.services.notifications import AdminNotificationService


@pytest.mark.asyncio
class TestAdminSmartAlerts:
    """Test smart admin error alerts."""

    async def test_notify_sheets_error(self) -> None:
        """Test sending Google Sheets error notification."""
        mock_bot = AsyncMock()
        service = AdminNotificationService(mock_bot)

        await service.notify_sheets_error(order_number="ORD-100")

        mock_bot.send_message.assert_called_once()
        text = mock_bot.send_message.call_args[1]["text"]
        assert "ORD-100" in text
        assert "Google Таблиці" in text

    async def test_notify_client_unreachable(self) -> None:
        """Test sending unreachable client notification."""
        mock_bot = AsyncMock()
        service = AdminNotificationService(mock_bot)

        await service.notify_client_unreachable(
            order_number="ORD-200",
            phone="+380501234567",
            action_description="прийняття",
        )

        mock_bot.send_message.assert_called_once()
        text = mock_bot.send_message.call_args[1]["text"]
        assert "ORD-200" in text
        assert "+380501234567" in text
        assert "Клієнт недоступний" in text

    async def test_notify_menu_load_error(self) -> None:
        """Test sending menu loading error notification."""
        mock_bot = AsyncMock()
        service = AdminNotificationService(mock_bot)

        await service.notify_menu_load_error()

        mock_bot.send_message.assert_called_once()
        text = mock_bot.send_message.call_args[1]["text"]
        assert "Помилка зчитування Меню" in text

    async def test_notify_db_error(self) -> None:
        """Test sending DB error notification."""
        mock_bot = AsyncMock()
        service = AdminNotificationService(mock_bot)

        await service.notify_db_error(order_number="ORD-300")

        mock_bot.send_message.assert_called_once()
        text = mock_bot.send_message.call_args[1]["text"]
        assert "ORD-300" in text
        assert "Помилка Бази Даних" in text
