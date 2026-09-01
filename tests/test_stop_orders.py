"""Tests for stop-orders feature, waitlist, and admin toggle handlers."""

import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import SystemSettingCRUD, WaitlistCRUD
from bot.handlers.admin import stop_orders_handler, resume_orders_handler
from bot.keyboards.inline import get_admin_stop_orders_reply_keyboard


@pytest.mark.asyncio
class TestSystemSettingCRUD:
    """Test CRUD operations for system settings."""

    async def test_orders_paused_default_false(self, async_session: AsyncSession) -> None:
        """Verify default state is not paused."""
        is_paused = await SystemSettingCRUD.is_orders_paused(async_session)
        assert is_paused is False

    async def test_set_orders_paused(self, async_session: AsyncSession) -> None:
        """Verify setting orders paused to True and False."""
        await SystemSettingCRUD.set_orders_paused(async_session, paused=True)
        assert await SystemSettingCRUD.is_orders_paused(async_session) is True

        await SystemSettingCRUD.set_orders_paused(async_session, paused=False)
        assert await SystemSettingCRUD.is_orders_paused(async_session) is False


@pytest.mark.asyncio
class TestWaitlistCRUD:
    """Test waitlist operations."""

    async def test_add_and_pop_waitlist(self, async_session: AsyncSession) -> None:
        """Verify adding users to waitlist and popping them."""
        await WaitlistCRUD.add_to_waitlist(async_session, telegram_id=11111)
        await WaitlistCRUD.add_to_waitlist(async_session, telegram_id=22222)

        # Duplicate addition should be ignored
        await WaitlistCRUD.add_to_waitlist(async_session, telegram_id=11111)

        users = await WaitlistCRUD.pop_waitlist_users(async_session)
        assert set(users) == {11111, 22222}

        # After pop, waitlist should be empty
        users_after = await WaitlistCRUD.pop_waitlist_users(async_session)
        assert users_after == []


from bot.handlers.order import confirm_order_handler


@pytest.mark.asyncio
class TestStopOrdersHandlers:
    """Test admin stop/resume order handlers."""

    async def test_confirm_order_blocked_when_paused(self, async_session: AsyncSession) -> None:
        """Verify order confirmation is blocked if orders were paused in the meantime."""
        await SystemSettingCRUD.set_orders_paused(async_session, paused=True)

        query = AsyncMock()
        query.from_user.id = 77777
        state = AsyncMock()
        mock_bot = AsyncMock()

        await confirm_order_handler(query, state, async_session, mock_bot)

        query.answer.assert_called_once_with()
        state.clear.assert_called_once()

        waiters = await WaitlistCRUD.pop_waitlist_users(async_session)
        assert 77777 in waiters

    async def test_stop_orders_admin_only(self, async_session: AsyncSession) -> None:
        """Verify only admin can toggle stop-orders."""
        message = AsyncMock()
        message.from_user.id = 99999
        message.chat.id = 99999
        message.text = "🛑 Стоп-прийом"

        with patch("bot.handlers.admin.settings.admin_chat_id", 12345):
            await stop_orders_handler(message, async_session)
            message.answer.assert_not_called()
            assert await SystemSettingCRUD.is_orders_paused(async_session) is False

    async def test_stop_orders_success(self, async_session: AsyncSession) -> None:
        """Verify admin can enable stop-orders."""
        message = AsyncMock()
        message.from_user.id = 12345
        message.chat.id = 12345
        message.text = "🛑 Стоп-прийом"

        with patch("bot.handlers.admin.settings.admin_chat_id", 12345):
            await stop_orders_handler(message, async_session)
            message.answer.assert_called_once()
            assert await SystemSettingCRUD.is_orders_paused(async_session) is True

    async def test_resume_orders_notifies_waitlist(self, async_session: AsyncSession) -> None:
        """Verify resuming orders notifies users in waitlist."""
        # Enable pause and add waiting user
        await SystemSettingCRUD.set_orders_paused(async_session, paused=True)
        await WaitlistCRUD.add_to_waitlist(async_session, telegram_id=55555)

        message = AsyncMock()
        message.from_user.id = 12345
        message.chat.id = 12345
        message.text = "▶️ Відновити прийом"

        mock_bot = AsyncMock()

        with patch("bot.handlers.admin.settings.admin_chat_id", 12345), \
             patch("aiogram.Bot", return_value=mock_bot):
            await resume_orders_handler(message, async_session)

            assert await SystemSettingCRUD.is_orders_paused(async_session) is False
            mock_bot.send_message.assert_called_once()
            assert mock_bot.send_message.call_args[1]["chat_id"] == 55555
            message.answer.assert_called_once()


def test_admin_stop_orders_reply_keyboard() -> None:
    """Test reply keyboard generation for stop/resume mode."""
    kb_active = get_admin_stop_orders_reply_keyboard(is_paused=False)
    assert kb_active.keyboard[0][0].text == "🛑 Стоп-прийом"

    kb_paused = get_admin_stop_orders_reply_keyboard(is_paused=True)
    assert kb_paused.keyboard[0][0].text == "▶️ Відновити прийом"
