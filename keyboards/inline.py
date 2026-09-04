"""Inline and reply keyboards for CoffeeRun bot."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


class FavoriteOrderCallback(CallbackData, prefix="fav_order"):
    """Callback data for favorite-order actions."""

    action: str


def get_menu_keyboard(menu_items: list[dict], favorite_drink_name: str | None = None) -> InlineKeyboardMarkup:
    """Build inline keyboard for menu selection.
    
    Args:
        menu_items: List of menu items with keys: name, volume, price
        
    Returns:
        InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()

    if favorite_drink_name:
        builder.button(
            text=f"⭐️ Order Favorite ({favorite_drink_name})",
            callback_data=FavoriteOrderCallback(action="open").pack(),
        )

    for idx, item in enumerate(menu_items):
        button_text = f"☕ {item['name']} {item['volume']}ml — ₴{item['price']}"
        callback_data = f"drink_{idx:03d}"
        builder.button(text=button_text, callback_data=callback_data)

    builder.adjust(1)  # 1 button per row
    return builder.as_markup()


def get_confirmation_keyboard(
    show_save_favorite: bool = False,
    back_button_type: str = "notes",  # "notes", "time", or "none"
) -> InlineKeyboardMarkup:
    """Build inline keyboard for order confirmation.
    
    Returns:
        InlineKeyboardMarkup with Confirm/Cancel buttons
    """
    builder = InlineKeyboardBuilder()

    if show_save_favorite:
        builder.button(
            text="⭐️ Зберегти як улюблене",
            callback_data=FavoriteOrderCallback(action="save").pack(),
        )

    builder.button(text="✅ Підтвердити", callback_data="confirm_order")
    builder.button(text="❌ Скасувати", callback_data="cancel_order")

    if back_button_type == "notes":
        builder.button(text="🔙 Назад", callback_data="back_to_notes")
    elif back_button_type == "time":
        builder.button(text="🔙 Назад", callback_data="back_to_time")

    if show_save_favorite and back_button_type != "none":
        builder.adjust(1, 2, 1)
    elif show_save_favorite:
        builder.adjust(1, 2)
    elif back_button_type != "none":
        builder.adjust(2, 1)
    else:
        builder.adjust(2)

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

def get_admin_order_keyboard(order_number: str, user_id: int, current_status: str = "new") -> InlineKeyboardMarkup | None:
    """Динамічна клавіатура для керування статусом замовлення."""
    builder = InlineKeyboardBuilder()
    
    if current_status == "new":
        builder.button(text="🟡 Прийняти", callback_data=f"adm_st:acc:{order_number}:{user_id}")
        builder.button(text="❌ Скасувати", callback_data=f"adm_st:canc:{order_number}:{user_id}")
        builder.adjust(2)
        
    elif current_status == "acc":
        builder.button(text="🔥 Готується", callback_data=f"adm_st:prep:{order_number}:{user_id}")
        builder.button(text="❌ Скасувати", callback_data=f"adm_st:canc:{order_number}:{user_id}")
        builder.adjust(2)
        
    elif current_status == "prep":
        builder.button(text="✅ Готово", callback_data=f"adm_st:rdy:{order_number}:{user_id}")
        builder.adjust(1)
        
    else:
        return None
        
    return builder.as_markup()


def get_time_keyboard() -> InlineKeyboardMarkup:
    """Клавіатура для часу з швидкими варіантами."""
    builder = InlineKeyboardBuilder()
    builder.button(text="10 хв", callback_data="quick_time:10")
    builder.button(text="15 хв", callback_data="quick_time:15")
    builder.button(text="20 хв", callback_data="quick_time:20")
    builder.button(text="🔙 Назад до меню", callback_data="back_to_menu")
    builder.adjust(3, 1) # 3 кнопки в ряд, 1 під ними
    return builder.as_markup()

def get_phone_reply_keyboard() -> ReplyKeyboardMarkup:
    """Нижня кнопка ТІЛЬКИ для контакту."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Надіслати мій номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_user_cancel_keyboard(order_number: str, admin_msg_id: int) -> InlineKeyboardMarkup:
    """Кнопка скасування, яка висить під чеком клієнта, і запам'ятовує ID повідомлення адміна."""
    builder = InlineKeyboardBuilder()
    
    # Ховаємо ID повідомлення адміна прямо в callback_data!
    builder.button(text="❌ Скасувати замовлення", callback_data=f"usr_cancel:{order_number}:{admin_msg_id}")
    
    return builder.as_markup()


def get_new_order_inline_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard for starting a new order from a status message."""
    builder = InlineKeyboardBuilder()
    builder.button(text="☕ Нове замовлення", callback_data="new_order_inline")
    return builder.as_markup()

def get_admin_stop_orders_reply_keyboard(is_paused: bool = False) -> ReplyKeyboardMarkup:
    """Bottom reply keyboard for admin to toggle stop-orders mode."""
    button_text = "▶️ Відновити прийом" if is_paused else "🛑 Стоп-прийом"
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=button_text)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def get_start_menu_inline_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard for opening the menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="☕ Відкрити меню", callback_data="open_menu_inline")
    return builder.as_markup()
