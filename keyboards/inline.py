"""Inline and reply keyboards for CoffeeRun bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_menu_keyboard(menu_items: list[dict]) -> InlineKeyboardMarkup:
    """Build inline keyboard for menu selection.
    
    Args:
        menu_items: List of menu items with keys: name, volume, price
        
    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    for idx, item in enumerate(menu_items):
        button_text = f"☕ {item['name']} {item['volume']}ml — ₴{item['price']}"
        callback_data = f"drink_{idx:03d}"
        builder.button(text=button_text, callback_data=callback_data)

    builder.adjust(1)  # 1 button per row
    return builder.as_markup()


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard for order confirmation.
    
    Returns:
        InlineKeyboardMarkup with Confirm/Cancel buttons
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Підтвердити", callback_data="confirm_order")
    builder.button(text="❌ Скасувати", callback_data="cancel_order")
    builder.button(text="🔙 Назад", callback_data="back_to_notes")

    builder.adjust(2, 1)  # 2 buttons per row
    return builder.as_markup()

def get_notes_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for notes step (skip and back)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустити", callback_data="skip_notes")
    builder.button(text="🔙 Назад", callback_data="back_to_phone")
    builder.adjust(1, 1)
    return builder.as_markup()


def get_cancel_button() -> InlineKeyboardMarkup:
    """Build inline keyboard with single cancel button.
    
    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="⏸ Скасувати замовлення", callback_data="cancel_flow")
    return builder.as_markup()


def get_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard to go back to menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад до меню", callback_data="back_to_menu")
    return builder.as_markup()

def get_back_to_time_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard to go back to time input."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_to_time")
    return builder.as_markup()