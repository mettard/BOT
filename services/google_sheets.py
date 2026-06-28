"""Google Sheets integration service."""

import asyncio
import json
import logging
from typing import Any, Optional

import gspread
from gspread.exceptions import APIError, GSpreadException
from google.oauth2.service_account import Credentials

from bot.config import settings

logger = logging.getLogger(__name__)

# Sheets tab names
MENU_SHEET = "Menu"
ORDERS_SHEET = "Orders"
CONFIG_SHEET = "Config"


class GoogleSheetsService:
    """Async Google Sheets service with retry logic."""

    def __init__(self) -> None:
        """Initialize Google Sheets service."""
        self._client: Optional[gspread.Client] = None
        self._spreadsheet: Optional[gspread.Spreadsheet] = None
        self._retries = 3
        self._backoff_base = 2

    async def _get_client(self) -> gspread.Client:
        """Get or create gspread client with exponential backoff."""
        if self._client is not None:
            return self._client

        def _create_client() -> gspread.Client:
            """Create client (sync function to run in thread pool)."""
            scope = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(
                settings.google_sheets_key_file,
                scopes=scope,
            )
            return gspread.authorize(creds)

        try:
            self._client = await asyncio.to_thread(_create_client)
            return self._client
        except Exception as e:
            logger.error(f"Failed to create Google Sheets client: {e}")
            raise

    async def _get_spreadsheet(self) -> gspread.Spreadsheet:
        """Get or open spreadsheet."""
        if self._spreadsheet is not None:
            return self._spreadsheet

        client = await self._get_client()

        def _open_sheet() -> gspread.Spreadsheet:
            """Open spreadsheet (sync function)."""
            return client.open_by_key(settings.google_sheets_spreadsheet_id)

        try:
            self._spreadsheet = await asyncio.to_thread(_open_sheet)
            return self._spreadsheet
        except Exception as e:
            logger.error(f"Failed to open spreadsheet: {e}")
            raise

    async def _retry_operation(self, operation: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute operation with exponential backoff retry."""
        last_error: Optional[Exception] = None

        for attempt in range(self._retries):
            try:
                return await asyncio.to_thread(operation, *args, **kwargs)
            except APIError as e:
                last_error = e
                if e.response.status_code == 429:  # Rate limit
                    wait_time = self._backoff_base**attempt
                    logger.warning(
                        f"Rate limited. Retrying in {wait_time}s (attempt {attempt + 1}/{self._retries})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except GSpreadException as e:
                logger.error(f"GSpread error: {e}")
                raise

        if last_error:
            raise last_error

        return None

    async def get_menu(self) -> list[dict[str, Any]]:
        """Get menu from Menu sheet.
        
        Returns:
            List of menu items with columns: name, volume, price, available
        """
        try:
            spreadsheet = await self._get_spreadsheet()

            def _get_menu_data() -> list[dict[str, Any]]:
                """Get menu data (sync)."""
                worksheet = spreadsheet.worksheet(MENU_SHEET)
                records = worksheet.get_all_records()
                return records

            records = await self._retry_operation(_get_menu_data)

            # Filter out items without price
            menu = []
            for item in records:
                if (
                    item.get("Price (₴)") is not None
                    and item.get("Price (₴)") != ""
                    and float(item.get("Price (₴)", 0)) > 0
                    and item.get("Available", True)
                ):
                    menu.append(
                        {
                            "name": item.get("Drink Name", "Unknown"),
                            "volume": int(item.get("Volume (ml)", 0)),
                            "price": float(item.get("Price (₴)", 0)),
                            "description": item.get("Description", ""),
                        }
                    )

            logger.info(f"Loaded {len(menu)} menu items from Sheets")
            return menu

        except Exception as e:
            logger.error(f"Error fetching menu: {e}")
            return []

    async def append_order(
        self,
        order_number: str,
        customer_name: str,
        phone: str,
        drink_name: str,
        price: float,
        pickup_time: str,
        status: str = "New",
        notes: str = "",
    ) -> bool:
        """Append order to Orders sheet.
        
        Args:
            order_number: Order ID
            customer_name: Customer name
            phone: Phone number
            drink_name: Drink name
            price: Price
            pickup_time: Pickup time (ISO format)
            status: Order status
            notes: Additional notes
        Returns:
            True if successful
        """
        try:
            spreadsheet = await self._get_spreadsheet()
            timestamp = asyncio.get_event_loop().time()

            def _append_order() -> bool:
                """Append order (sync)."""
                worksheet = spreadsheet.worksheet(ORDERS_SHEET)
                row = [
                    str(timestamp),  # Timestamp
                    order_number,
                    customer_name,
                    phone,
                    drink_name,
                    price,
                    pickup_time,
                    status,
                    notes,  # Notes
                ]
                worksheet.append_row(row)
                return True

            result = await self._retry_operation(_append_order)
            logger.info(f"Order {order_number} appended to Sheets")
            return result

        except Exception as e:
            logger.error(f"Error appending order to Sheets: {e}")
            return False

    async def update_order_status(self, order_number: str, status: str) -> bool:
        """Update order status in Orders sheet.
        
        Args:
            order_number: Order ID
            status: New status
            
        Returns:
            True if successful
        """
        try:
            spreadsheet = await self._get_spreadsheet()

            def _update_status() -> bool:
                """Update status (sync)."""
                worksheet = spreadsheet.worksheet(ORDERS_SHEET)
                records = worksheet.get_all_records()

                for idx, record in enumerate(records, start=2):  # +2 for header + 1-index
                    if record.get("Order ID") == order_number:
                        worksheet.update_cell(idx, 8, status)  # Column 8 = Status
                        return True

                return False

            result = await self._retry_operation(_update_status)
            if result:
                logger.info(f"Order {order_number} status updated to {status}")
            else:
                logger.warning(f"Order {order_number} not found in Sheets")
            return result

        except Exception as e:
            logger.error(f"Error updating order status: {e}")
            return False

    async def get_business_config(self) -> dict[str, str]:
            """Fetch cafe open and close times from Config sheet horizontally."""
            try:
                spreadsheet = await self._get_spreadsheet()

                def _get_config_data() -> list[list[Any]]:
                    worksheet = spreadsheet.worksheet(CONFIG_SHEET)
                    # Беремо чисту матрицю значень (всі заповнені рядки й стовпчики)
                    return worksheet.get_all_values()

                rows = await self._retry_operation(_get_config_data)
                
                # Якщо таблиця порожня або там менше 2 рядків — повертаємо дефолт
                if len(rows) < 2:
                    return {"CAFE_OPEN_TIME": "09:00", "CAFE_CLOSE_TIME": "23:59"}
                    
                headers = rows[0]  # Перший рядок: ['CAFE_OPEN_TIME', 'CAFE_CLOSE_TIME']
                values = rows[1]   # Другий рядок: ['09:00', '23:59']
                
                # Зліплюємо їх у зручний словник за допомогою zip
                config = {}
                for header, val in zip(headers, values):
                    if header:
                        config[header.strip()] = val.strip()
                        
                return config
            except Exception as e:
                logger.error(f"Error fetching business config: {e}")
                return {"CAFE_OPEN_TIME": "09:00", "CAFE_CLOSE_TIME": "23:59"}
# Global service instance
_sheets_service: Optional[GoogleSheetsService] = None


async def get_sheets_service() -> GoogleSheetsService:
    """Get or create Google Sheets service instance."""
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = GoogleSheetsService()
    return _sheets_service
