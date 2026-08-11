"""Async CRUD operations for database models."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Order, PausedWaitlist, SystemSetting, User


class UserCRUD:
    """User CRUD operations."""

    @staticmethod
    async def get_or_create(
        session: AsyncSession, telegram_id: int, first_name: str, last_name: Optional[str] = None
    ) -> User:
        """Get user by telegram_id or create if not exists."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                first_name=first_name,
                last_name=last_name,
            )
            session.add(user)
            await session.commit()

        return user

    @staticmethod
    async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
        """Get user by telegram_id."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_last_bot_msg_id(session: AsyncSession, telegram_id: int, msg_id: Optional[int]) -> Optional[User]:
        """Update user's last bot message ID."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            user.last_bot_msg_id = msg_id
            await session.commit()
        return user

    @staticmethod
    async def update_phone(session: AsyncSession, telegram_id: int, phone: str) -> User:
        """Update user phone number."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            user.phone = phone
            await session.commit()
            await session.refresh(user)

        return user

    @staticmethod
    async def save_favorite_order(
        session: AsyncSession,
        telegram_id: int,
        drink_name: str,
        volume_ml: int,
        price: float,
        phone: str,
        notes: str,
    ) -> User | None:
        """Persist favorite order details for a user."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            return None

        user.favorite_drink_name = drink_name
        user.favorite_volume_ml = volume_ml
        user.favorite_price = price
        user.favorite_phone = phone
        user.favorite_notes = notes
        await session.commit()
        await session.refresh(user)
        return user

    @staticmethod
    async def get_favorite_order(session: AsyncSession, telegram_id: int) -> User | None:
        """Get user with favorite-order fields."""
        return await UserCRUD.get_by_telegram_id(session=session, telegram_id=telegram_id)


class OrderCRUD:
    """Order CRUD operations."""

    @staticmethod
    async def create(
        session: AsyncSession,
        order_number: str,
        telegram_id: int,
        customer_name: str,
        phone: str,
        drink_name: str,
        volume_ml: int,
        price: float,
        pickup_time: datetime,
        notes: Optional[str] = None,
    ) -> Order:
        """Create new order."""
        order = Order(
            order_number=order_number,
            telegram_id=telegram_id,
            customer_name=customer_name,
            phone=phone,
            drink_name=drink_name,
            volume_ml=volume_ml,
            price=price,
            pickup_time=pickup_time,
            status="New",
            notes=notes,
        )
        session.add(order)
        await session.commit()
        return order

    @staticmethod
    async def get_by_order_number(session: AsyncSession, order_number: str) -> Optional[Order]:
        """Get order by order number."""
        stmt = select(Order).where(Order.order_number == order_number)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        session: AsyncSession, order_number: str, status: str
    ) -> Optional[Order]:
        """Update order status."""
        stmt = select(Order).where(Order.order_number == order_number)
        result = await session.execute(stmt)
        order = result.scalar_one_or_none()

        if order:
            order.status = status
            order.updated_at = datetime.now(timezone.utc)
            await session.commit()

        return order

    @staticmethod
    async def get_by_telegram_id_recent(
        session: AsyncSession, telegram_id: int, limit: int = 10
    ) -> list[Order]:
        """Get recent orders by telegram_id."""
        stmt = (
            select(Order)
            .where(Order.telegram_id == telegram_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()


class SystemSettingCRUD:
    """CRUD operations for system settings."""

    @staticmethod
    async def is_orders_paused(session: AsyncSession) -> bool:
        """Check if orders are currently paused."""
        stmt = select(SystemSetting).where(SystemSetting.key == "orders_paused")
        result = await session.execute(stmt)
        setting = result.scalar_one_or_none()
        if setting is None:
            return False
        return setting.value.lower() == "true"

    @staticmethod
    async def set_orders_paused(session: AsyncSession, paused: bool) -> None:
        """Set whether orders are paused."""
        stmt = select(SystemSetting).where(SystemSetting.key == "orders_paused")
        result = await session.execute(stmt)
        setting = result.scalar_one_or_none()
        val_str = "true" if paused else "false"

        if setting is None:
            setting = SystemSetting(key="orders_paused", value=val_str)
            session.add(setting)
        else:
            setting.value = val_str
            setting.updated_at = datetime.now(timezone.utc)

        await session.commit()


class WaitlistCRUD:
    """CRUD operations for paused order waitlist."""

    @staticmethod
    async def add_to_waitlist(session: AsyncSession, telegram_id: int) -> None:
        """Add user to waitlist if not already present."""
        stmt = select(PausedWaitlist).where(PausedWaitlist.telegram_id == telegram_id)
        result = await session.execute(stmt)
        entry = result.scalar_one_or_none()

        if entry is None:
            entry = PausedWaitlist(telegram_id=telegram_id)
            session.add(entry)
            await session.commit()

    @staticmethod
    async def pop_waitlist_users(session: AsyncSession) -> list[int]:
        """Fetch all waiting telegram IDs and clear the waitlist."""
        stmt = select(PausedWaitlist)
        result = await session.execute(stmt)
        entries = result.scalars().all()

        telegram_ids = [e.telegram_id for e in entries]

        if entries:
            for entry in entries:
                await session.delete(entry)
            await session.commit()

        return telegram_ids


