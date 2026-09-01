"""Tests for CRUD operations."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from bot.database.crud import OrderCRUD, UserCRUD
from bot.database.models import Order, User


class TestUserCRUD:
    """Test User CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_user(self, async_session):
        """Test creating a new user."""
        user = await UserCRUD.get_or_create(
            session=async_session,
            telegram_id=111111111,
            first_name="John",
            last_name="Doe",
        )
        assert user.telegram_id == 111111111
        assert user.first_name == "John"
        assert user.last_name == "Doe"

    @pytest.mark.asyncio
    async def test_get_or_create_existing_user(self, async_session, sample_user: User):
        """Test get_or_create returns existing user."""
        user = await UserCRUD.get_or_create(
            session=async_session,
            telegram_id=sample_user.telegram_id,
            first_name="Different",
        )
        assert user.telegram_id == sample_user.telegram_id
        assert user.first_name == sample_user.first_name  # Original value

    @pytest.mark.asyncio
    async def test_get_by_telegram_id(self, async_session, sample_user: User):
        """Test retrieving user by telegram_id."""
        user = await UserCRUD.get_by_telegram_id(
            session=async_session,
            telegram_id=sample_user.telegram_id,
        )
        assert user is not None
        assert user.telegram_id == sample_user.telegram_id
        assert user.first_name == sample_user.first_name

    @pytest.mark.asyncio
    async def test_get_nonexistent_user(self, async_session):
        """Test retrieving non-existent user returns None."""
        user = await UserCRUD.get_by_telegram_id(
            session=async_session,
            telegram_id=999999999,
        )
        assert user is None

    @pytest.mark.asyncio
    async def test_update_user_phone(self, async_session, sample_user: User):
        """Test updating user phone."""
        new_phone = "+380991234567"
        user = await UserCRUD.update_phone(
            session=async_session,
            telegram_id=sample_user.telegram_id,
            phone=new_phone,
        )
        assert user.phone == new_phone

    @pytest.mark.asyncio
    async def test_update_phone_nonexistent_user(self, async_session):
        """Test updating phone for non-existent user returns None."""
        user = await UserCRUD.update_phone(
            session=async_session,
            telegram_id=999999999,
            phone="+380501234567",
        )
        assert user is None

    @pytest.mark.asyncio
    async def test_user_uniqueness_constraint(self, async_session, sample_user: User):
        """Test that telegram_id is unique."""
        duplicate_user = User(
            telegram_id=sample_user.telegram_id,
            first_name="Duplicate",
            last_name="User",
        )
        async_session.add(duplicate_user)
        with pytest.raises(Exception):  # SQLAlchemy will raise IntegrityError
            await async_session.commit()

    @pytest.mark.asyncio
    async def test_user_timestamps(self, async_session):
        """Test that created_at and updated_at are set."""
        user = await UserCRUD.get_or_create(
            session=async_session,
            telegram_id=222222222,
            first_name="Test",
        )
        assert user.created_at is not None
        assert user.updated_at is not None
        assert isinstance(user.created_at, datetime)
        assert isinstance(user.updated_at, datetime)


class TestOrderCRUD:
    """Test Order CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_order(self, async_session, sample_user: User):
        """Test creating a new order."""
        future_time = datetime.now() + timedelta(hours=1)
        order = await OrderCRUD.create(
            session=async_session,
            order_number="ORD-202406171530",
            telegram_id=sample_user.telegram_id,
            customer_name="John Doe",
            phone="+380501234567",
            drink_name="Cappuccino",
            volume_ml=250,
            price=45.00,
            pickup_time=future_time,
            notes="Extra hot",
        )
        assert order.order_number == "ORD-202406171530"
        assert order.customer_name == "John Doe"
        assert order.drink_name == "Cappuccino"
        assert order.price == 45.00
        assert order.status == "New"
        assert order.notes == "Extra hot"

    @pytest.mark.asyncio
    async def test_get_order_by_number(self, async_session, sample_order: Order):
        """Test retrieving order by order number."""
        order = await OrderCRUD.get_by_order_number(
            session=async_session,
            order_number=sample_order.order_number,
        )
        assert order is not None
        assert order.order_number == sample_order.order_number
        assert order.customer_name == sample_order.customer_name

    @pytest.mark.asyncio
    async def test_get_nonexistent_order(self, async_session):
        """Test retrieving non-existent order returns None."""
        order = await OrderCRUD.get_by_order_number(
            session=async_session,
            order_number="ORD-NONEXISTENT",
        )
        assert order is None

    @pytest.mark.asyncio
    async def test_update_order_status(self, async_session, sample_order: Order):
        """Test updating order status."""
        updated_order = await OrderCRUD.update_status(
            session=async_session,
            order_number=sample_order.order_number,
            status="Completed",
        )
        assert updated_order.status == "Completed"
        assert updated_order.updated_at >= sample_order.updated_at

    @pytest.mark.asyncio
    async def test_update_status_nonexistent_order(self, async_session):
        """Test updating status for non-existent order returns None."""
        order = await OrderCRUD.update_status(
            session=async_session,
            order_number="ORD-NONEXISTENT",
            status="Completed",
        )
        assert order is None

    @pytest.mark.asyncio
    async def test_order_number_uniqueness(self, async_session, sample_user: User):
        """Test that order_number is unique."""
        future_time = datetime.now() + timedelta(hours=1)
        order1 = await OrderCRUD.create(
            session=async_session,
            order_number="ORD-UNIQUE",
            telegram_id=sample_user.telegram_id,
            customer_name="Customer 1",
            phone="+380501234567",
            drink_name="Cappuccino",
            volume_ml=250,
            price=45.00,
            pickup_time=future_time,
        )
        assert order1 is not None

        # Try to create duplicate
        duplicate = Order(
            order_number="ORD-UNIQUE",
            telegram_id=sample_user.telegram_id,
            customer_name="Customer 2",
            phone="+380501234567",
            drink_name="Latte",
            volume_ml=300,
            price=50.00,
            pickup_time=future_time,
        )
        async_session.add(duplicate)
        with pytest.raises(Exception):  # IntegrityError
            await async_session.commit()

    @pytest.mark.asyncio
    async def test_get_recent_orders_by_user(self, async_session, sample_user: User):
        """Test retrieving recent orders for a user."""
        future_time = datetime.now() + timedelta(hours=1)

        # Create 3 orders
        for i in range(3):
            await OrderCRUD.create(
                session=async_session,
                order_number=f"ORD-{i}",
                telegram_id=sample_user.telegram_id,
                customer_name=f"Customer {i}",
                phone="+380501234567",
                drink_name="Coffee",
                volume_ml=250,
                price=45.00,
                pickup_time=future_time,
            )

        orders = await OrderCRUD.get_by_telegram_id_recent(
            session=async_session,
            telegram_id=sample_user.telegram_id,
            limit=10,
        )
        assert len(orders) >= 3

    @pytest.mark.asyncio
    async def test_get_recent_orders_limit(self, async_session, sample_user: User):
        """Test that limit is respected in get_by_telegram_id_recent."""
        future_time = datetime.now() + timedelta(hours=1)

        # Create 5 orders
        for i in range(5):
            await OrderCRUD.create(
                session=async_session,
                order_number=f"ORD-LIMIT-{i}",
                telegram_id=sample_user.telegram_id,
                customer_name=f"Customer {i}",
                phone="+380501234567",
                drink_name="Coffee",
                volume_ml=250,
                price=45.00,
                pickup_time=future_time,
            )

        orders = await OrderCRUD.get_by_telegram_id_recent(
            session=async_session,
            telegram_id=sample_user.telegram_id,
            limit=2,
        )
        assert len(orders) == 2

    @pytest.mark.asyncio
    async def test_get_recent_orders_ordering(self, async_session, sample_user: User):
        """Test that recent orders are ordered by creation time (newest first)."""
        future_time = datetime.now() + timedelta(hours=1)

        for i in range(3):
            await OrderCRUD.create(
                session=async_session,
                order_number=f"ORD-ORDER-{i}",
                telegram_id=sample_user.telegram_id,
                customer_name=f"Customer {i}",
                phone="+380501234567",
                drink_name="Coffee",
                volume_ml=250,
                price=45.00,
                pickup_time=future_time,
            )

        orders = await OrderCRUD.get_by_telegram_id_recent(
            session=async_session,
            telegram_id=sample_user.telegram_id,
        )

        # Check that orders are in descending creation order
        for i in range(len(orders) - 1):
            assert orders[i].created_at >= orders[i + 1].created_at

    @pytest.mark.asyncio
    async def test_order_timestamps(self, async_session, sample_user: User):
        """Test that created_at and updated_at are set."""
        future_time = datetime.now() + timedelta(hours=1)
        order = await OrderCRUD.create(
            session=async_session,
            order_number="ORD-TIMESTAMPS",
            telegram_id=sample_user.telegram_id,
            customer_name="Customer",
            phone="+380501234567",
            drink_name="Coffee",
            volume_ml=250,
            price=45.00,
            pickup_time=future_time,
        )
        assert order.created_at is not None
        assert order.updated_at is not None
        assert isinstance(order.created_at, datetime)
        assert isinstance(order.updated_at, datetime)

    @pytest.mark.asyncio
    async def test_order_without_notes(self, async_session, sample_user: User):
        """Test creating order without notes (nullable field)."""
        future_time = datetime.now() + timedelta(hours=1)
        order = await OrderCRUD.create(
            session=async_session,
            order_number="ORD-NO-NOTES",
            telegram_id=sample_user.telegram_id,
            customer_name="Customer",
            phone="+380501234567",
            drink_name="Coffee",
            volume_ml=250,
            price=45.00,
            pickup_time=future_time,
        )
        assert order.notes is None
