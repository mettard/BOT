"""Tests for Telegram bot handlers."""
import pytest
from unittest.mock import AsyncMock

from bot.handlers.order import global_dead_callback_catcher


@pytest.mark.asyncio
async def test_global_dead_callback_catcher(mock_telegram_callback_query, mock_fsm_context):
    """Test that global_dead_callback_catcher cleans keyboard, sends warning and clears state."""
    # Call the handler
    await global_dead_callback_catcher(mock_telegram_callback_query, mock_fsm_context)

    # 1. Answer callback query silently
    mock_telegram_callback_query.answer.assert_called_once_with()

    # 2. Send guidance message to user
    mock_telegram_callback_query.message.answer.assert_called_once()
    args, kwargs = mock_telegram_callback_query.message.answer.call_args
    assert "Сесія застаріла" in args[0]
    assert "/start" in args[0]
    assert kwargs.get("parse_mode") == "HTML"

    # 3. State cleared
    mock_fsm_context.clear.assert_called_once()




@pytest.mark.asyncio
async def test_change_phone_cmd_handler(mock_telegram_message, mock_fsm_context, async_session):
    """Test that /phone command clears state and prompts for new phone."""
    from bot.handlers.order import change_phone_cmd_handler
    from bot.states.order import OrderFSM

    mock_telegram_message.from_user.id = 999888
    mock_telegram_message.from_user.first_name = "PhoneTest"
    mock_telegram_message.from_user.last_name = "User"

    await change_phone_cmd_handler(mock_telegram_message, mock_fsm_context, async_session)

    mock_fsm_context.clear.assert_called_once()
    mock_fsm_context.set_state.assert_called_once_with(OrderFSM.changing_phone)
    assert mock_telegram_message.answer.call_count == 1


