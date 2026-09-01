"""Tests for user input validators."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from bot.services.validators import (
    generate_order_number,
    normalize_phone,
    parse_time_input,
    validate_phone,
    validate_pickup_time,
)


class TestPhoneValidation:
    """Test Ukrainian phone number validation."""

    # Valid phone numbers (15 positive cases)
    VALID_PHONES = [
        "+380501234567",
        "+380631234567",
        "+380661234567",
        "+380671234567",
        "+380681234567",
        "+380731234567",
        "+380911234567",
        "+380921234567",
        "+380931234567",
        "380501234567",
        "0501234567",
        "0631234567",
        "+380951234567",
        "380951234567",
        "0951234567",
    ]

    # Invalid phone numbers (15 negative cases)
    INVALID_PHONES = [
        "+380401234567",  # Invalid operator (04x)
        "+380451234567",  # Invalid operator (04x)
        "+380111234567",  # Invalid operator (01x)
        "+3805012345",  # Too short
        "+3805012345678",  # Too long
        "+48501234567",  # Poland number
        "+358501234567",  # Finland number
        "8501234567",  # Old Soviet format
        "80501234567",  # Old Soviet format
        "+3705012345",  # Typo in country code
        "123456789",  # Random numbers
        "+380",  # Incomplete
        "abc1234567",  # Letters
        "",  # Empty string
    ]

    @pytest.mark.parametrize("phone", VALID_PHONES)
    def test_validate_valid_phones(self, phone: str):
        """Test validation of valid Ukrainian phone numbers."""
        assert validate_phone(phone) is True, f"Phone {phone} should be valid"

    @pytest.mark.parametrize("phone", INVALID_PHONES)
    def test_validate_invalid_phones(self, phone: str):
        """Test validation of invalid phone numbers."""
        assert validate_phone(phone) is False, f"Phone {phone} should be invalid"

    def test_phone_with_spaces(self):
        """Test phone normalization with spaces."""
        assert validate_phone("+380 50 123 4567") is True

    def test_phone_with_dashes(self):
        """Test phone normalization with dashes."""
        assert validate_phone("+380-50-123-4567") is True

    def test_phone_with_mixed_separators(self):
        """Test phone normalization with mixed separators."""
        assert validate_phone("0 50-123 4567") is True


class TestPhoneNormalization:
    """Test phone number normalization to +380 format."""

    def test_normalize_plus_format(self):
        """Test normalization of +380 format."""
        assert normalize_phone("+380501234567") == "+380501234567"

    def test_normalize_380_format(self):
        """Test normalization of 380 format."""
        assert normalize_phone("380501234567") == "+380501234567"

    def test_normalize_0_format(self):
        """Test normalization of 0 format."""
        assert normalize_phone("0501234567") == "+380501234567"

    def test_normalize_with_spaces(self):
        """Test normalization with spaces."""
        assert normalize_phone("+380 50 123 4567") == "+380501234567"

    def test_normalize_with_dashes(self):
        """Test normalization with dashes."""
        assert normalize_phone("0 50-123-4567") == "+380501234567"

    def test_normalize_all_operators(self):
        """Test normalization for all valid operators."""
        operators = ["39", "50", "63", "66", "67", "68", "73", "91", "92", "93", "94", "95", "96", "97", "98", "99"]
        for op in operators:
            phone = f"0{op}1234567"
            normalized = normalize_phone(phone)
            assert normalized == f"+380{op}1234567", f"Failed for operator {op}"


class TestTimeInputParsing:
    """Test time input parsing (relative and absolute)."""

    def test_parse_relative_time_ukrainian_short(self):
        """Test parsing relative time in Ukrainian (short form)."""
        result = parse_time_input("10 хв")
        assert result is not None
        assert result > datetime.now()
        assert result.minute in [
            (datetime.now() + timedelta(minutes=10)).minute,
            ((datetime.now() + timedelta(minutes=10)).minute + 1) % 60,  # Account for second boundary
        ]

    def test_parse_relative_time_english(self):
        """Test parsing relative time in English."""
        result = parse_time_input("15 min")
        assert result is not None
        assert result > datetime.now()

    def test_parse_relative_time_zero(self):
        """Test parsing 0 minutes (should return immediate)."""
        result = parse_time_input("0 хв")
        assert result is not None
        assert result >= datetime.now()

    def test_parse_absolute_time_valid(self):
        """Test parsing valid absolute time."""
        result = parse_time_input("15:30")
        assert result is not None
        assert result.hour == 15
        assert result.minute == 30

    def test_parse_absolute_time_morning(self):
        """Test parsing morning time."""
        result = parse_time_input("09:00")
        assert result is not None
        assert result.hour == 9
        assert result.minute == 0

    def test_parse_absolute_time_past_today(self):
        """Test that past time today becomes tomorrow."""
        now = datetime.now()
        past_hour = (now.hour - 1) % 24
        result = parse_time_input(f"{past_hour:02d}:00")
        assert result is not None
        # Should be tomorrow if time is in past
        if past_hour < now.hour:
            assert result.day != now.day or result.day == 1

    def test_parse_invalid_format(self):
        """Test parsing invalid format."""
        assert parse_time_input("invalid") is None
        assert parse_time_input("not a time") is None
        assert parse_time_input("") is None

    def test_parse_invalid_absolute_time(self):
        """Test parsing invalid absolute time."""
        assert parse_time_input("25:00") is None
        assert parse_time_input("12:60") is None
        assert parse_time_input("12:") is None

    def test_parse_large_relative_time(self):
        """Test parsing large relative time."""
        result = parse_time_input("720 хв")  # 12 hours
        assert result is not None
        assert result > datetime.now()


class TestPickupTimeValidation:
    """Test pickup time validation (future, cafe hours, advance limit)."""

    def test_valid_pickup_time(self):
        """Test valid future pickup time within cafe hours."""
        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 29, 12, 0, 0)

        with patch("bot.services.validators.datetime", MockDateTime):
            future_time = datetime(2026, 7, 29, 14, 0, 0)
            is_valid, error = validate_pickup_time(future_time)
            assert is_valid is True
            assert error == ""

    def test_pickup_time_in_past(self):
        """Test that past time is rejected."""
        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 29, 12, 0, 0)

        with patch("bot.services.validators.datetime", MockDateTime):
            past_time = datetime(2026, 7, 29, 11, 0, 0)
            is_valid, error = validate_pickup_time(past_time)
            assert is_valid is False
            assert error == "MSG_103"

    def test_pickup_time_before_opening(self):
        """Test that time before cafe opening is rejected."""
        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 29, 7, 0, 0)

        with patch("bot.services.validators.datetime", MockDateTime):
            before_opening = datetime(2026, 7, 29, 8, 0, 0)
            is_valid, error = validate_pickup_time(before_opening)
            assert is_valid is False
            assert error == "MSG_104"

    def test_pickup_time_at_opening(self):
        """Test that time at cafe opening is valid."""
        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 29, 8, 30, 0)

        with patch("bot.services.validators.datetime", MockDateTime):
            at_opening = datetime(2026, 7, 29, 9, 0, 0)
            is_valid, error = validate_pickup_time(at_opening)
            assert is_valid is True

    def test_pickup_time_after_closing(self):
        """Test that time after cafe closing is rejected."""
        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 29, 20, 0, 0)

        with patch("bot.services.validators.datetime", MockDateTime):
            after_closing = datetime(2026, 7, 29, 21, 30, 0)
            is_valid, error = validate_pickup_time(after_closing)
            assert is_valid is False
            assert error == "MSG_104"

    def test_pickup_time_before_closing(self):
        """Test that time before cafe closing is valid."""
        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 29, 19, 0, 0)

        with patch("bot.services.validators.datetime", MockDateTime):
            before_closing = datetime(2026, 7, 29, 20, 59, 0)
            is_valid, error = validate_pickup_time(before_closing)
            assert is_valid is True

    def test_pickup_time_too_far_ahead(self):
        """Test that time beyond max advance (12 hours) is rejected."""
        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 29, 20, 0, 0)

        with patch("bot.services.validators.datetime", MockDateTime):
            too_far = datetime(2026, 7, 30, 10, 0, 0)  # Tomorrow 10 AM (14 hours ahead, open hours)
            is_valid, error = validate_pickup_time(too_far)
            assert is_valid is False
            assert error == "MSG_105"

    def test_pickup_time_at_max_advance(self):
        """Test that time at max advance limit is valid."""
        class MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 7, 29, 9, 0, 0)

        with patch("bot.services.validators.datetime", MockDateTime):
            at_max = datetime(2026, 7, 29, 20, 59, 0)  # 11 hours 59 minutes ahead, within open hours
            is_valid, error = validate_pickup_time(at_max)
            assert is_valid is True


class TestOrderNumberGeneration:
    """Test order number generation."""

    def test_order_number_format(self):
        """Test order number format - 4-digit numeric string."""
        order_num = generate_order_number()
        assert order_num.isdigit()
        assert len(order_num) == 4

    def test_order_number_uniqueness(self):
        """Test that order numbers are unique (or rare collision)."""
        numbers = [generate_order_number() for _ in range(100)]
        unique_count = len(set(numbers))
        assert unique_count >= 90  # Allow some rare collisions in 4-digit space
