"""FSM states for order flow."""

from aiogram.fsm.state import State, StatesGroup


class OrderFSM(StatesGroup):
    """Main order creation FSM."""

    menu_selection = State()
    time_input = State()
    phone_input = State()
    notes_input = State()
    confirmation = State()
    changing_phone = State()


class CancelFSM(StatesGroup):
    """Admin cancel order FSM (if needed for future)."""

    waiting_for_confirmation = State()
