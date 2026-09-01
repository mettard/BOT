"""Configuration module for CoffeeRun bot."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration from .env file."""

    # Telegram
    bot_token: str
    admin_chat_id: int

    # Database
    database_url: str

    # Google Sheets
    google_sheets_key_file: str
    google_sheets_spreadsheet_id: str

    # Cafe configuration
    cafe_open_time: str = "09:00"  # HH:MM
    cafe_close_time: str = "21:00"  # HH:MM
    max_advance_minutes: int = 720  # 12 hours

    # Logging
    log_level: str = "INFO"

    # Environment
    environment: str = "development"

    class Config:
        """Pydantic settings configuration."""

        env_file = (
            Path(__file__).parent / ".env",
            Path(__file__).parent.parent / ".env",
            ".env",
        )
        case_sensitive = False


settings = Settings()  # type: ignore
