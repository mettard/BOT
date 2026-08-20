# 04. Implementation Notes — CoffeeRun Bot

**Date:** 2026-06-17 | **Version:** MVP 1.0

---

## 1. Architecture Overview

### Tech Stack
- **Framework:** aiogram 3.x (Router-based, FSM with StatesGroup)
- **Database:** PostgreSQL + SQLAlchemy 2.0 (async, Mapped[] declarative style)
- **Google Sheets:** gspread with asyncio.to_thread wrapper
- **Testing:** pytest + pytest-asyncio
- **Deployment:** Docker + docker-compose

### Directory Structure
```
bot/
├── __init__.py
├── config.py                    # pydantic-settings
├── main.py                      # Bot entry point
├── handlers/
│   ├── __init__.py
│   ├── order.py                 # Order FSM handlers
│   └── admin.py                 # Admin notification handlers
├── keyboards/
│   ├── __init__.py
│   └── inline.py                # Inline keyboards via InlineKeyboardBuilder
├── states/
│   ├── __init__.py
│   └── order.py                 # OrderFSM state definitions
├── database/
│   ├── __init__.py
│   ├── engine.py                # create_async_engine, AsyncSessionLocal
│   ├── models.py                # SQLAlchemy Mapped models (User, Order)
│   └── crud.py                  # Async CRUD operations
├── services/
│   ├── __init__.py
│   ├── validators.py            # Phone validation, time parsing, order_id generation
│   ├── google_sheets.py         # Async Google Sheets service with retry logic
│   └── notifications.py         # Admin notification service
└── middlewares/
    ├── __init__.py
    └── db_session.py            # DB session middleware for context injection

migrations/
├── env.py                       # Alembic environment config
├── versions/
│   ├── 001_initial.py           # Initial schema (users, orders tables)
│   └── ...
```

---

## 2. Key Implementation Decisions

### 2.1 FSM Design
**Decision:** Single OrderFSM with sequential states: menu_selection → time_input → phone_input → confirmation

**Rationale:**
- MVP simplicity: no branching logic
- Clear user flow: no back/forward navigation (FSM.clear() on cancel)
- All state data stored in FSMContext (session-safe)

**Flow:**
```
/start (MenuSelection)
  ↓ [drink selected]
TimeInput
  ↓ [valid time]
PhoneInput
  ↓ [valid phone]
Confirmation
  ↓ [confirm button]
Clear & Order Created
```

**Cancellation:** Available from ANY state via `/cancel` command or cancel button.

### 2.2 Database Session Injection via Middleware
**Decision:** `DbSessionMiddleware` injects session into `data["session"]` for every handler

**Rationale:**
- No manual `AsyncSessionLocal()` calls in handlers → centralized management
- Clean separation: handlers use CRUD, not raw SQLAlchemy
- Automatic cleanup via context manager

**Usage in handler:**
```python
async def handler(message: Message, session: AsyncSession):
    user = await UserCRUD.get_or_create(session, ...)
```

### 2.3 Google Sheets Async Wrapper
**Decision:** All gspread calls wrapped in `asyncio.to_thread()` with exponential backoff retry

**Rationale:**
- gspread is synchronous; we need non-blocking I/O in async handlers
- Retry logic: on 429 (rate limit), backoff = 2^attempt
- Single global `GoogleSheetsService` instance

**Retry Pattern:**
- 3 retries by default
- Backoff: 2s, 4s, 8s for rate limits
- Raise on other errors immediately (auth, network)

**Usage:**
```python
sheets_service = await get_sheets_service()
menu = await sheets_service.get_menu()  # Non-blocking
```

### 2.4 Validation & Error Handling
**Decision:** Validators return parsed/normalized data; errors stay in same FSM state for re-prompt

**Rationale:**
- Tight UX loop: invalid input → error message → re-prompt (no state change)
- Phone normalization: accept +380/380/0 formats → normalize to +380xxxxxxxxx
- Time parsing: relative (10 хв) and absolute (15:30) → datetime object

**Validators (services/validators.py):**
- `validate_phone()` → bool (regex-based)
- `normalize_phone()` → str (+380 format)
- `parse_time_input()` → datetime | None
- `validate_pickup_time()` → (is_valid: bool, error_key: str)
- `generate_order_number()` → str (ORD-YYYYMMDDhhmm)

### 2.5 Admin Notifications
**Decision:** Inline buttons for acknowledgement/cancellation → edit original message

**Rationale:**
- No extra messages clutter
- Real-time status updates in admin chat
- Button callbacks update DB + Sheets + notification text in-place

**Flow:**
```
Original message: "Нове замовлення [✓ Прийняти] [✗ Скасувати]"
  ↓ Admin clicks ✓
Message updated: "✅ Замовлення прийнято. Готуємо!"
```

### 2.6 Google Sheets Architecture
**Sheets Expected:**
1. **Menu** tab: columns = [Drink Name, Volume (ml), Price (₴), Available, Description]
   - Bot reads on `/start` + background refresh (~5-10 min)
   - Empty/0 prices hidden from menu
   - Status column ignored for MVP
2. **Orders** tab: columns = [Timestamp, Order ID, Customer, Phone, Drink, Price, Pickup Time, Status, Notes]
   - Bot appends on order confirmation
   - Bot updates Status column on admin action (Acknowledged → Ready, Cancel → Canceled)
3. **Config** tab (optional): for future cafe hours, max advance, etc.

---

## 3. Critical Edge Cases & Handling

### 3.1 Time Validation
**Edge Case:** User enters past time or outside cafe hours

**Implementation:**
```python
def validate_pickup_time(pickup_time):
    # 1. Must be > now
    # 2. Must be 09:00 ≤ time < 21:00
    # 3. Must be ≤ (now + 12 hours)
```

**UX:** Re-prompt in same state with specific error message (MSG-103/104/105)

### 3.2 Empty Menu Item (Missing Price)
**Edge Case:** Owner deletes price in Sheets

**Implementation:**
```python
menu = [item for item in records if item.get("Price") > 0]
```

**UX:** Item hidden from menu silently. Log warning. Show MSG-106 if 0 items.

### 3.3 Session Interruption (User Blocks Bot)
**Edge Case:** User enters FSM, then blocks bot mid-flow

**Implementation:**
- Order lost (acceptable for MVP)
- DB stores nothing (order created only on confirmation)
- No recovery mechanism in v1
- Logged as WARNING for v2 analysis

**Decision:** Conservative MVP—defer session recovery to v2

### 3.4 Duplicate Order (Network Retry)
**Edge Case:** User clicks confirm, message doesn't arrive, clicks again

**Implementation:**
- Telegram callback_query deduplication (built-in)
- Order number collision: generate_order_number() uses timestamp + seconds
- DB unique constraint on order_number prevents duplicates
- Duplicate insert → DB error → logged, not shown to user

### 3.5 Google Sheets Rate Limit (429)
**Edge Case:** Too many requests to Sheets API

**Implementation:**
- Exponential backoff: 2s, 4s, 8s
- 3 retries total
- On final failure: show user MSG-107, log ERROR, order not written

---

## 4. Middleware & Context Injection

### DB Session Middleware
```python
class DbSessionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        async with AsyncSessionLocal() as session:
            data["session"] = session
            return await handler(event, data)
```

**Registered in main.py:**
```python
dp.message.middleware(DbSessionMiddleware())
dp.callback_query.middleware(DbSessionMiddleware())
```

**Handler receives:**
```python
async def handler(message: Message, session: AsyncSession):
    # session is injected and auto-committed/rolled back
```

---

## 5. Testing Strategy (Outline)

### Unit Tests (tests/test_validators.py)
```python
def test_validate_phone_valid():
    assert validate_phone("+380501234567") == True
    assert validate_phone("0501234567") == True
    
def test_validate_phone_invalid():
    assert validate_phone("+1234567890") == False

def test_validate_pickup_time_past():
    past = datetime.now() - timedelta(hours=1)
    valid, error = validate_pickup_time(past)
    assert valid == False
    assert error == "MSG_103"
```

### Integration Tests (tests/test_handlers.py - mock asyncpg/gspread)
```python
@pytest.mark.asyncio
async def test_order_flow():
    # Mock DB session, Sheets service
    # Simulate /start → drink selection → time input → phone → confirm
    # Assert order created in mock DB, Sheets called, admin notified
```

### Mock Fixtures
- Mock `AsyncSessionLocal()` → in-memory SQLite
- Mock `get_sheets_service()` → return static menu
- Mock `Bot.send_message()` → capture calls

---

## 6. Deployment & Configuration

### Environment Variables (.env)
```
BOT_TOKEN=<your-token>
ADMIN_CHAT_ID=-100123456789
DATABASE_URL=postgresql+asyncpg://...
GOOGLE_SHEETS_KEY_FILE=./service_account.json
GOOGLE_SHEETS_SPREADSHEET_ID=<spreadsheet_id>
CAFE_OPEN_TIME=09:00
CAFE_CLOSE_TIME=21:00
MAX_ADVANCE_MINUTES=720
LOG_LEVEL=INFO
ENVIRONMENT=production
```

### Docker Setup
1. Build: `docker-compose build`
2. Run: `docker-compose up -d`
3. Logs: `docker-compose logs -f bot`

**Database initialization:**
- On first run, bot.main.py creates tables via `Base.metadata.create_all()`
- Alembic migrations available in `migrations/` for future schema changes

---

## 7. TODO for v2 (Backlog)

### Must-Have Improvements
- [ ] User phone caching (avoid re-entry on repeat orders)
- [ ] Follow-up notifications (bot → user: "Ready for pickup!")
- [ ] Order history endpoint (user requests recent orders)
- [ ] Admin API (REST for external integrations)

### Nice-to-Have
- [ ] Promo codes / discounts
- [ ] Recurring favorite orders
- [ ] Payment integration (Stripe, Mono)
- [ ] Multi-language support (EN/UA)
- [ ] Rating system after completion
- [ ] Analytics dashboard

### Potential Issues (Known Limitations)
1. **In-memory FSM storage:** If bot restarts mid-order, user's state lost. Consider Redis for production.
2. **No explicit order history:** Orders only in Sheets. Consider dedicated history endpoint in v2.
3. **Sheets rate limiting:** If multiple concurrent users, API quota may hit. Caching menu in-memory + refresh every 5-10 min could help.
4. **No payment:** Free MVP. Orders assumed pre-paid or cash at pickup.
5. **Single admin chat:** Hardcoded ADMIN_CHAT_ID. Multi-cafe support deferred to v2.

---

## 8. Logging & Monitoring

### Log Levels
- **INFO:** FSM transitions, order creation, Sheets operations
- **WARNING:** Menu empty, Sheets API errors (transient), duplicate order attempts
- **ERROR:** Validation failures (log, don't expose to user), DB errors, auth failures

### Example Logs
```
INFO: User 123456 started bot
INFO: Menu loaded: 5 items from Sheets
INFO: User 123456 selected drink_002 (Cappuccino)
INFO: User 123456 entered pickup time: +15 min (parsed as 15:30)
WARNING: User 123456 entered invalid time: "25:00" - re-prompted
INFO: Order ORD-202406170001 created (user 123456, cappuccino)
INFO: Order sent to Sheets
INFO: Admin notification sent (message_id: 98765)
INFO: Admin 999888 acknowledged order ORD-202406170001
```

---

## 9. Type Safety & Code Quality

### Mypy Strict Mode
All modules type-hinted for `mypy --strict` compatibility:
- No untyped functions
- No `Any` without explicit docstring
- Return types on all callables

**Run:** `mypy bot/ --strict`

### Code Formatting
- **Black:** `black bot/ tests/`
- **isort:** `isort bot/ tests/`

### Pre-commit Hook (optional)
```bash
#!/bin/bash
black bot/ tests/
isort bot/ tests/
mypy bot/ --strict
```

---

## 10. Performance Considerations

### Bottlenecks & Optimizations
1. **Google Sheets read:** Caching menu for 5-10 min to reduce API calls
2. **Database queries:** Indexed on telegram_id, order_number, status
3. **Admin notifications:** Edited in-place (no new messages)
4. **Phone validation:** Regex (O(1)), not API call

### Scalability (Beyond MVP)
- MemoryStorage → Redis (for multi-instance deployments)
- DB connection pooling (asyncpg handles this)
- Sheets caching → Redis or in-memory with TTL
- Admin chat scaling: multi-cafe support (separate admin groups per cafe)

---

**Status:** ✅ **Implementation COMPLETE**

Ready for testing, Alembic migrations, and deployment.
