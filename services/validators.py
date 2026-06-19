"""Validators for user input (phone, time, etc)."""

import logging
import re
from datetime import datetime, timedelta

from bot.config import settings

logger = logging.getLogger(__name__)

# Ukrainian phone pattern: +380/380/0 + valid prefix + 7 digits
UA_PHONE_PATTERN = re.compile(
    r"^(?:\+380|380|0)(?:39|50|63|66|67|68|73|91|92|93|94|95|96|97|98|99)\d{7}$"
)


def validate_phone(phone: str) -> bool:
    """Validate Ukrainian phone number.
    
    Accepts:
    - +380xxxxxxxxx
    - 380xxxxxxxxx
    - 0xxxxxxxxx
    
    Args:
        phone: Phone number string
        
    Returns:
        True if valid, False otherwise
    """
    phone_clean = phone.replace(" ", "").replace("-", "")
    return bool(UA_PHONE_PATTERN.match(phone_clean))


def normalize_phone(phone: str) -> str:
    """Normalize phone to +380 format.
    
    Args:
        phone: Phone number in any valid format
        
    Returns:
        Normalized phone in +380xxxxxxxxx format
    """
    phone_clean = phone.replace(" ", "").replace("-", "")

    if phone_clean.startswith("0"):
        return "+38" + phone_clean
    elif phone_clean.startswith("380"):
        return "+" + phone_clean
    elif phone_clean.startswith("+380"):
        return phone_clean

    return phone_clean


def parse_time_input(time_str: str) -> datetime | None:
    """Parse time input from user.
    
    Accepts:
    - Relative: "10 хв", "10 min", "20 хв"
    - Absolute: "15:30", "14:45"
    
    Args:
        time_str: Time input string
        
    Returns:
        datetime object or None if invalid
    """
    time_str = time_str.strip().lower()

    # Try relative format (e.g., "10 хв", "10 min")
    relative_match = re.match(r"^(\d+)\s*(?:хв|min|minutes?|хвилин)$", time_str)
    if relative_match:
        minutes = int(relative_match.group(1))
        return datetime.now() + timedelta(minutes=minutes)

    # Try absolute format (e.g., "15:30")
    absolute_match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if absolute_match:
        hour, minute = int(absolute_match.group(1)), int(absolute_match.group(2))
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If time is in the past today, assume tomorrow
        if target <= now:
            target += timedelta(days=1)

        return target

    return None


def validate_pickup_time(pickup_time: datetime) -> tuple[bool, str]:
    """Validate pickup time.
    
    Checks:
    - Must be in future
    - Must be within cafe hours (09:00-21:00)
    - Must be within 12 hours ahead
    
    Args:
        pickup_time: datetime object
        
    Returns:
        (is_valid, error_message)
    """
    now = datetime.now()

    # Check if in past
    if pickup_time <= now:
        return False, "MSG_103"  # Time in past

    # Check cafe hours
    open_time = datetime.strptime(settings.cafe_open_time, "%H:%M").time()
    close_time = datetime.strptime(settings.cafe_close_time, "%H:%M").time()

    if not (open_time <= pickup_time.time() < close_time):
        return False, "MSG_104"  # Outside hours

    # Check advance limit
    max_future = now + timedelta(minutes=settings.max_advance_minutes)
    if pickup_time > max_future:
        return False, "MSG_105"  # Too far ahead

    return True, ""


def generate_order_number() -> str:
    """Generate order number in format ORD-YYYYMMDDnnnn.
    
    Returns:
        Order number string
    """
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    # In production, increment nnnn based on DB count, for now use timestamp
    time_str = now.strftime("%H%M%S")[:4]
    return f"ORD-{date_str}{time_str}"
