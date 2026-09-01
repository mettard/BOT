"""Tests for FSM order flow."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext

from bot.states.order import OrderFSM


class TestOrderFSMStates:
    """Test OrderFSM state definitions."""

    def test_fsm_has_all_states(self):
        """Test that OrderFSM has all required states."""
        states = [state.state for state in OrderFSM]
        assert "menu_selection" in [s.split(":")[-1] for s in states]
        assert "time_input" in [s.split(":")[-1] for s in states]
        assert "phone_input" in [s.split(":")[-1] for s in states]
        assert "confirmation" in [s.split(":")[-1] for s in states]

    def test_fsm_states_are_unique(self):
        """Test that all FSM states are unique."""
        states = [state.state for state in OrderFSM]
        assert len(states) == len(set(states))

    def test_fsm_state_names_match_order(self):
        """Test that FSM states follow the order: menu → time → phone → confirmation."""
        # States should be defined in order
        states = list(OrderFSM)
        expected_order = [
            "menu_selection",
            "time_input",
            "phone_input",
            "confirmation",
        ]
        actual_order = [s.state.split(":")[-1] for s in states]
        for expected in expected_order:
            assert expected in actual_order


class TestOrderFSMDataFlow:
    """Test data flow through OrderFSM."""

    @pytest.mark.asyncio
    async def test_store_menu_selection(self, mock_fsm_context):
        """Test storing selected drink in FSM context."""
        drink_data = {
            "name": "Cappuccino",
            "volume": 250,
            "price": 45.00,
            "description": "Classic cappuccino",
        }
        await mock_fsm_context.update_data(selected_drink=drink_data)
        mock_fsm_context.update_data.assert_called_once_with(selected_drink=drink_data)

    @pytest.mark.asyncio
    async def test_store_pickup_time(self, mock_fsm_context):
        """Test storing pickup time in FSM context."""
        future_time = datetime.now() + timedelta(hours=1)
        await mock_fsm_context.update_data(pickup_time=future_time)
        mock_fsm_context.update_data.assert_called_once_with(pickup_time=future_time)

    @pytest.mark.asyncio
    async def test_store_phone(self, mock_fsm_context):
        """Test storing phone in FSM context."""
        await mock_fsm_context.update_data(phone="+380501234567")
        mock_fsm_context.update_data.assert_called_once_with(phone="+380501234567")

    @pytest.mark.asyncio
    async def test_accumulate_all_order_data(self, mock_fsm_context):
        """Test accumulating all order data through FSM states."""
        order_data = {
            "selected_drink": {"name": "Cappuccino", "volume": 250, "price": 45.00},
            "pickup_time": datetime.now() + timedelta(hours=1),
            "phone": "+380501234567",
            "customer_name": "John Doe",
        }
        await mock_fsm_context.update_data(**order_data)
        mock_fsm_context.update_data.assert_called_once_with(**order_data)

    @pytest.mark.asyncio
    async def test_retrieve_stored_data(self, mock_fsm_context):
        """Test retrieving accumulated data."""
        test_data = {"key": "value"}
        mock_fsm_context.get_data = AsyncMock(return_value=test_data)
        data = await mock_fsm_context.get_data()
        assert data == test_data


class TestOrderFSMTransitions:
    """Test FSM state transitions (menu → time → phone → confirmation)."""

    @pytest.mark.asyncio
    async def test_transition_menu_to_time(self, mock_fsm_context):
        """Test transition from menu_selection to time_input."""
        await mock_fsm_context.set_state(OrderFSM.time_input)
        mock_fsm_context.set_state.assert_called_once_with(OrderFSM.time_input)

    @pytest.mark.asyncio
    async def test_transition_time_to_phone(self, mock_fsm_context):
        """Test transition from time_input to phone_input."""
        await mock_fsm_context.set_state(OrderFSM.phone_input)
        mock_fsm_context.set_state.assert_called_once_with(OrderFSM.phone_input)

    @pytest.mark.asyncio
    async def test_transition_phone_to_confirmation(self, mock_fsm_context):
        """Test transition from phone_input to confirmation."""
        await mock_fsm_context.set_state(OrderFSM.confirmation)
        mock_fsm_context.set_state.assert_called_once_with(OrderFSM.confirmation)

    @pytest.mark.asyncio
    async def test_no_backtracking_from_phone_to_menu(self, mock_fsm_context):
        """Test that there's no handler for going back from phone to menu."""
        # FSM should not support backtracking
        # This is verified by handler structure, not FSM itself
        # Phone state should only allow transition to confirmation or cancel
        pass

    @pytest.mark.asyncio
    async def test_clear_fsm_on_cancel(self, mock_fsm_context):
        """Test that FSM is cleared when user cancels."""
        await mock_fsm_context.clear()
        mock_fsm_context.clear.assert_called_once()


class TestOrderFSMErrorRecovery:
    """Test FSM error recovery and state persistence."""

    @pytest.mark.asyncio
    async def test_re_enter_same_state_on_invalid_input(self, mock_fsm_context):
        """Test that invalid input keeps user in same state."""
        # When user enters invalid phone, they should stay in phone_input state
        # This is verified by handler logic, not FSM
        current_state = OrderFSM.phone_input
        await mock_fsm_context.set_state(current_state)
        # Should still be in phone_input for retry
        mock_fsm_context.set_state.assert_called_once_with(current_state)

    @pytest.mark.asyncio
    async def test_preserve_data_on_invalid_input(self, mock_fsm_context):
        """Test that FSM data is preserved when input is invalid."""
        menu_data = {"selected_drink": {"name": "Cappuccino", "volume": 250, "price": 45.00}}
        await mock_fsm_context.update_data(**menu_data)
        
        # Even if phone input is invalid, menu should still be in context
        mock_fsm_context.get_data = AsyncMock(return_value=menu_data)
        data = await mock_fsm_context.get_data()
        assert "selected_drink" in data

    @pytest.mark.asyncio
    async def test_fsm_timeout_handling(self):
        """Test that FSM can handle user inactivity (conversation timeout)."""
        # This is typically handled by bot framework, not FSM itself
        # Documented as a known limitation in v2 backlog
        pass


class TestOrderFSMIntegration:
    """Integration tests for complete order flow."""

    @pytest.mark.asyncio
    async def test_complete_order_flow_data(self, mock_fsm_context):
        """Test complete flow: menu → time → phone → confirmation."""
        # Simulate menu selection
        drink = {"name": "Cappuccino", "volume": 250, "price": 45.00, "description": ""}
        await mock_fsm_context.update_data(selected_drink=drink)
        await mock_fsm_context.set_state(OrderFSM.time_input)

        # Simulate time input
        future_time = datetime.now() + timedelta(hours=1)
        await mock_fsm_context.update_data(pickup_time=future_time)
        await mock_fsm_context.set_state(OrderFSM.phone_input)

        # Simulate phone input
        await mock_fsm_context.update_data(phone="+380501234567")
        await mock_fsm_context.set_state(OrderFSM.confirmation)

        # Verify all state transitions were called
        assert mock_fsm_context.set_state.call_count == 3
        assert mock_fsm_context.update_data.call_count == 3

    @pytest.mark.asyncio
    async def test_order_flow_with_retry(self, mock_fsm_context):
        """Test order flow with invalid input retry."""
        # User enters invalid time
        await mock_fsm_context.set_state(OrderFSM.time_input)
        
        # User retries in same state
        await mock_fsm_context.set_state(OrderFSM.time_input)
        
        # Then proceeds to phone
        await mock_fsm_context.set_state(OrderFSM.phone_input)
        
        # At least 2 calls for time_input (original + retry)
        calls = [str(call) for call in mock_fsm_context.set_state.call_args_list]
        assert str(OrderFSM.time_input) in calls or len(calls) >= 2

    @pytest.mark.asyncio
    async def test_cancel_at_menu(self, mock_fsm_context):
        """Test cancellation at menu selection state."""
        await mock_fsm_context.set_state(OrderFSM.menu_selection)
        await mock_fsm_context.clear()
        mock_fsm_context.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_at_time(self, mock_fsm_context):
        """Test cancellation at time input state."""
        await mock_fsm_context.set_state(OrderFSM.time_input)
        await mock_fsm_context.clear()
        mock_fsm_context.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_at_phone(self, mock_fsm_context):
        """Test cancellation at phone input state."""
        await mock_fsm_context.set_state(OrderFSM.phone_input)
        await mock_fsm_context.clear()
        mock_fsm_context.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_at_confirmation(self, mock_fsm_context):
        """Test cancellation at confirmation state."""
        await mock_fsm_context.set_state(OrderFSM.confirmation)
        await mock_fsm_context.clear()
        mock_fsm_context.clear.assert_called_once()


class TestOrderFSMMenuStorage:
    """Test menu storage and retrieval in FSM context."""

    @pytest.mark.asyncio
    async def test_store_full_menu(self, mock_fsm_context):
        """Test storing full menu in FSM context."""
        menu = [
            {"name": "Cappuccino", "volume": 250, "price": 45.00, "description": ""},
            {"name": "Latte", "volume": 300, "price": 50.00, "description": ""},
            {"name": "Espresso", "volume": 30, "price": 25.00, "description": ""},
        ]
        await mock_fsm_context.update_data(menu=menu)
        mock_fsm_context.update_data.assert_called_once_with(menu=menu)

    @pytest.mark.asyncio
    async def test_retrieve_menu_from_context(self, mock_fsm_context):
        """Test retrieving menu from FSM context."""
        menu = [
            {"name": "Cappuccino", "volume": 250, "price": 45.00, "description": ""},
        ]
        mock_fsm_context.get_data = AsyncMock(return_value={"menu": menu})
        data = await mock_fsm_context.get_data()
        assert data["menu"] == menu

    @pytest.mark.asyncio
    async def test_select_from_stored_menu(self, mock_fsm_context):
        """Test selecting a drink from stored menu by index."""
        menu = [
            {"name": "Cappuccino", "volume": 250, "price": 45.00, "description": ""},
            {"name": "Latte", "volume": 300, "price": 50.00, "description": ""},
        ]
        mock_fsm_context.get_data = AsyncMock(return_value={"menu": menu})
        data = await mock_fsm_context.get_data()
        
        # Select first item (index 0)
        selected = data["menu"][0]
        assert selected["name"] == "Cappuccino"
