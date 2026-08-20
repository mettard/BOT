# CoffeeRun: Telegram Bot Requirements Document
**Project**: CoffeeRun MVP — Pre-ordering system for a local café  
**Created**: 2026-06-17  
**Version**: 1.0

---

## 1. Executive Summary

**CoffeeRun** is a Telegram-based pre-ordering bot for a local café designed to eliminate customer queues and streamline barista workflow. Customers select beverages from a dynamic menu, specify pickup time, verify phone, and receive real-time status updates. Cafe owner manages menu pricing directly in Google Sheets without code changes.

**Key Benefits**:
- Eliminate waiting lines during peak hours
- Real-time order visibility for staff
- Dynamic menu management via Google Sheets
- Customer phone verification for future loyalty programs

---

## 2. Actors & Roles

| Actor | Role | System Interaction |
|-------|------|-------------------|
| **End User (Customer)** | Orders coffee via Telegram | `/start` → browse menu → select drink → enter time → phone validation → confirm order |
| **Barista/Staff** | Receives orders in real-time | Admin chat notifications, Google Sheet row creation |
| **Café Owner** | Manages menu & pricing | Edits Google Sheet "Menu" tab; bot auto-reloads |
| **Bot System** | Orchestrates workflow | FSM controller, DB persistence, Sheets integration |
| **PostgreSQL** | Data persistence | Stores users, order history, phone validation logs |
| **Google Sheets API** | External data source | Menu (read), Orders log (write), Configuration (read) |

---

## 3. User Stories (MoSCoW Prioritization)

### MUST HAVE (MVP, Iteration 1)

**US-001** | **Customer Browses Menu**  
As a customer, I want to see a list of available coffees with sizes, descriptions, and prices when I open the bot, so I can quickly decide what to order.
- Acceptance: Menu loads from Google Sheet "Menu" tab on `/start`; displays name, volume, price per item.

**US-002** | **Customer Selects Drink**  
As a customer, I want to tap inline buttons to select a coffee and specify size, so I don't have to type.
- Acceptance: Inline keyboard shows drink options; selection stores in FSM state.

**US-003** | **Customer Specifies Pickup Time**  
As a customer, I want to enter how many minutes from now I'll pick up my order (e.g., "10", "20", "30"), so the barista knows when to prepare it.
- Acceptance: FSM state captures integer input; displays confirmation with precise pickup time.

**US-004** | **Customer Validates Phone (UA Format)**  
As a customer, I want to provide my phone number for verification, so the café can contact me if needed.
- Acceptance: FSM requests phone; validates against UA pattern `^(?:\+380|380|0)(?:39|50|63|66|67|68|73|91|92|93|94|95|96|97|98|99)\d{7}$`; rejects invalid input with retry message.

**US-005** | **Customer Confirms Order**  
As a customer, I want to review my order (drink, time, phone) and confirm before submission, so I can catch mistakes.
- Acceptance: Bot displays summary; customer taps "Confirm" or "Cancel" button.

**US-006** | **Barista Receives Order Alert**  
As a barista, I want to receive an immediate notification in the admin Telegram chat when a new order arrives, so I can prioritize preparation.
- Acceptance: Bot sends message to admin chat with order details (customer phone obfuscated, drink, time); linked to order ID.

**US-007** | **Orders Logged in Google Sheet**  
As a café owner, I want each order recorded in Google Sheet "Orders" tab automatically, so I have a historical log for analytics and follow-up.
- Acceptance: New row appended with: Timestamp, Customer Name, Phone, Drink, Size, Pickup Time, Status="Submitted", Order ID.

**US-008** | **Owner Updates Menu Pricing**  
As a café owner, I want to add/remove drinks or change prices directly in Google Sheet "Menu" tab without code changes, so I can react quickly to supplier costs.
- Acceptance: Google Sheet "Menu" tab has columns [Drink Name, Volume (ml), Price (UAH)]; bot reloads menu on each `/start` or admin request.

**US-009** | **Error Recovery — Invalid Phone**  
As a customer, I want clear feedback if I enter an invalid phone number and be able to retry within the same session, so I don't lose my order progress.
- Acceptance: On validation failure, bot displays error message (e.g., "❌ Invalid UA phone. Use +380XX..."), re-prompts within FSM without reset.

**US-010** | **Cancel Order (Mid-Process)**  
As a customer, I want to cancel my order at any point before confirmation, so I don't accidentally submit unwanted orders.
- Acceptance: `/cancel` command or "Cancel" button available in all FSM states; clears session and returns to menu.

### SHOULD HAVE (Iteration 2+)

**US-011** | **Display Order Status**  
As a customer, I want to see my order status (e.g., "Preparing", "Ready", "Picked Up"), so I know when to come pick up.
- Acceptance: Bot sends follow-up messages or callback updates when owner updates Google Sheet "Orders" tab Status column.

**US-012** | **Customer Sees Next Pickup Window**  
As a customer, I want to see suggested pickup times based on current queue depth, so I choose an optimal time.
- Acceptance: Bot calculates estimated wait based on order count from Google Sheet; suggests +5min, +10min, +15min, +20min.

**US-013** | **Owner Marks Order as Ready**  
As a café owner, I want to mark orders "Ready for Pickup" in Google Sheet, triggering a bot notification to customer.
- Acceptance: Google Sheet "Orders" tab Status updated → bot detects change → sends notification to customer chat.

**US-014** | **Recurring Customer Recognition**  
As a returning customer, I want my phone number to be recognized on next visit, so I don't have to re-enter it.
- Acceptance: Bot queries PostgreSQL for existing phone; pre-fills or offers quick "Use Saved Number" button.

### COULD HAVE (Post-MVP)

**US-015** | **Loyalty / Promo Support**  
As a café owner, I want to offer discount codes or loyalty points for repeat customers, so I increase retention.
- *Note: Out of MVP scope; tentatively planned for v2.*

**US-016** | **Admin Panel (Web Dashboard)**  
As a café owner, I want a lightweight web dashboard to review orders without opening Google Sheets, so I have a dedicated interface.
- *Note: Out of MVP scope; Sheets is the admin hub for v1.*

### WON'T HAVE (Not in scope)

**US-017** | **Payment Processing**  
Café operates cash-only at this stage; no payment integration required.

**US-018** | **Multi-Location Support**  
Single café location; multi-branch support deferred to v2.

---

## 4. Business Rules & Validation

### Time Window Validation
- **Rule BR-001**: Pickup time must be in the future (not in the past).
  - *Validation*: `pickup_time > now(); else show error "⏰ Время забора в прошлом. Выберите позже."` (in Ukrainian).
- **Rule BR-002**: Pickup time must be within café operating hours.
  - *Assumption*: Café operates 09:00–21:00 UTC+3 (configurable in `.env`).
  - *Validation*: If customer selects 22:30, show error: "❌ Кав'ярня закрита після 21:00. Виберіть іншу годину."
- **Rule BR-003**: Maximum ahead pickup time is 12 hours.
  - *Rationale*: Prevent over-booking; coffee freshness assumed ~4–6 hours.
  - *Validation*: `if pickup_time > now + 12h: reject`.

### Phone Number Validation
- **Rule BR-004**: Ukrainian phone format mandatory.
  - *Pattern*: `^(?:\+380|380|0)(?:39|50|63|66|67|68|73|91|92|93|94|95|96|97|98|99)\d{7}$`
  - *Examples*: ✅ `+380501234567`, ✅ `0501234567`, ❌ `+1-555-1234` (US format rejected).
  - *Validation*: Regex check; on fail, show: "📱 Введіть коректний український номер (+38050...)."

### Menu Integrity
- **Rule BR-005**: If a drink in Google Sheet has empty price field, treat as "unavailable" in bot.
  - *Action*: Hide from menu display; log warning in bot logs; alert owner in admin chat.
  - *Error message to customer*: "☕ Меню тимчасово оновлюється. Спробуйте за хвилину."
- **Rule BR-006**: Menu must contain at least 1 drink; if all deleted, show fallback message.
  - *Fallback*: "⚠️ Меню порожне. Зв'яжіться з власником."

### Session Management
- **Rule BR-007**: If customer starts new `/start` mid-order, treat as new session (clear old FSM state).
  - *Behavior*: No data loss in backend; old order may stay "Submitted" if already sent; new menu reloads.
- **Rule BR-008**: If bot blocked by customer or connection drops, order is lost (no retry mechanism in v1).
  - *Assumption*: Acceptable for MVP; customers can re-order.

---

## 5. Google Sheets Integration Map

### Sheets Document Structure

**Spreadsheet**: `CoffeeRun_Menu_Orders` (example name; configured in `.env` as `GOOGLE_SHEET_ID`)

#### Sheet 1: "Menu" (Read by Bot on `/start` and cache refresh)
| Column | Type | Required | Example | Notes |
|--------|------|----------|---------|-------|
| A | Drink Name | ✅ Yes | "Американо" | Displayed as menu item |
| B | Volume (ml) | ✅ Yes | 250 | Shown in description |
| C | Price (UAH) | ✅ Yes | 45 | If empty → mark as unavailable |
| D | Available (bool) | ⭕ Optional | TRUE / FALSE | Allow quick on/off without deleting |
| E | Description | ⭕ Optional | "Крепкий и полный" | Shown in menu for context |

**Sample Data**:
```
Drink Name      Volume  Price   Available  Description
Американо       250     45      TRUE       Крепкий, без молока
Капучино        300     60      TRUE       С молочной пеной
Латте           350     65      TRUE       Мягкий, с молоком
Еспресо         50      30      TRUE       Черный кофе, концентрат
Гарячий шоколад 300     50      FALSE      (Не доступен до весны)
```

#### Sheet 2: "Orders" (Written by Bot; read by Owner for status updates)
| Column | Type | Writer | Example | Notes |
|--------|------|--------|---------|-------|
| A | Timestamp | Bot | `2026-06-17 14:30:45` | Order creation time |
| B | Order ID | Bot | `ORD-20260617-001` | Unique identifier |
| C | Customer Name | Bot | "Іван" | From phone lookup or captured separately |
| D | Phone | Bot | "+380501234567" | Stored for owner callback |
| E | Drink | Bot | "Капучино 300ml" | Concatenated name + volume |
| F | Price | Bot | 60 | For receipts |
| G | Requested Pickup Time | Bot | `2026-06-17 14:45:00` | When customer wants coffee |
| H | Status | Owner (manual) | "Submitted" / "Preparing" / "Ready" / "Picked Up" | Owner updates; bot monitors |
| I | Notes | Owner (optional) | "Extra hot" | Free text for special requests (v2 feature) |

**Sample Data**:
```
Timestamp           Order ID        Customer  Phone          Drink                 Price  Requested Pickup      Status      Notes
2026-06-17 14:30:45 ORD-20260617-1  Іван      +380501234567  Капучино 300ml        60     2026-06-17 14:45:00   Submitted   —
2026-06-17 14:31:12 ORD-20260617-2  Марія     +380661234567  Американо 250ml       45     2026-06-17 14:50:00   Preparing   —
```

#### Sheet 3: "Config" (Optional; for future extensibility)
| Setting | Value | Purpose |
|---------|-------|---------|
| CAFE_TIMEZONE | UTC+3 | Timezone for time calculations |
| WORKING_HOURS_START | 09:00 | Café opens at |
| WORKING_HOURS_END | 21:00 | Café closes at |
| MAX_AHEAD_HOURS | 12 | Max advance booking window |
| ADMIN_CHAT_ID | -1001234567890 | Telegram admin chat for alerts |

### Integration Flow Diagram
```
[Bot starts] 
  ↓
[Read "Menu" sheet via gspread] → Cache drinks in memory
  ↓
[Display inline menu to customer]
  ↓
[Customer selects drink → enters time → phone]
  ↓
[Validate all inputs]
  ↓
[Write new row to "Orders" sheet]
  ↓
[Send notification to admin chat]
  ↓
[Owner updates "Orders" Status column in Sheet]
  ↓
[Bot polls / monitors "Orders" sheet for Status changes (optional v2)]
  ↓
[Send customer notification: "Ваше замовлення готове!"]
```

### Data Direction
- **Menu → Bot**: Read-only, on-demand (once per `/start` + periodic refresh every 5–10 min in background).
- **Bot → Orders**: Write-only, append new rows immediately after order confirmation.
- **Owner → Orders**: Manual edit of Status column; bot monitors (optional v2).
- **Config → Bot**: Read-only, at startup (optional v1; use hardcoded `.env` values).

---

## 6. Technical Constraints

### Language & Framework
- **Python 3.11+** (async/await mandatory)
- **aiogram 3.x** (Router-based FSM with StatesGroup)
- **PostgreSQL** (async engine via SQLAlchemy 2.0)
- **gspread** (Google Sheets API; wrapped in `asyncio.to_thread` for sync calls)
- **pydantic-settings** for configuration (.env file)

### API Rate Limits & Assumptions
- **Telegram Bot API**: ~30 messages/sec per bot; expect low volume (local café).
- **Google Sheets API**: ~300 requests/min (quota sufficient for orders + menu reads).
- **Concurrency**: Single async event loop; no special worker pool needed for MVP.

### Database Persistence
- **Users Table**: Store phone, first interaction timestamp, opt-in flag (for future newsletters).
- **Orders Table** (backup in DB): Redundant copy of orders; primary log in Google Sheets.
- **Session Timeouts**: FSM state cleared after 30 minutes of inactivity or explicit `/cancel`.

### Timezone Handling
- **Bot Server TZ**: Assume UTC+3 (Kyiv, Ukraine) for all timestamps.
- **Calculation Rule**: Use `datetime.now(timezone.utc).astimezone(pytz.timezone('Europe/Kyiv'))` in code.
- **Sheet Timestamps**: Store in ISO 8601 format: `2026-06-17T14:30:45+03:00`.

### Error Handling Requirements
- **Google Sheets Connection Lost**: Show customer "⚠️ Помилка синхронізації. Спробуйте пізніше."; retry in 5 sec.
- **PostgreSQL Down**: Bot continues but doesn't persist new users (non-critical for v1 MVP).
- **Invalid Menu Data**: Log warning; skip problematic rows; show fallback menu.

### Blocked/Interrupted Sessions
- **Customer blocks bot mid-order**: Order lost; acceptable for MVP.
- **Network timeout during submission**: Show "⏳ Замовлення обробляється..."; bot auto-resubmits once (idempotency via Order ID).
- **Barista manually deletes order from Sheet**: No automated cleanup; owner responsible (v1 assumption).

---

## 7. Open Questions

**OQ-001**: Should customers be able to request special instructions (e.g., "extra sugar", "oat milk") in v1, or is v2 feature?
- *Impact*: Affects FSM flow length and Google Sheet "Orders" columns.
- *Suggested Decision*: Defer to v2; v1 keeps orders simple.

**OQ-002**: If a customer orders the same coffee twice in one day, should they see a quick-reorder button, or start from menu fresh?
- *Impact*: UX polish; affects FSM state machine design.
- *Suggested Decision*: v1 = always start fresh; v2 = add quick-reorder button.

**OQ-003**: Who owns Google Sheet creation and sharing? Should bot code auto-create Sheet on first run, or manual setup by owner?
- *Impact*: DevOps/deployment workflow.
- *Suggested Decision*: Manual setup by owner (safer; reduces bot permissions); document in README.

**OQ-004**: What is the acceptable lag between customer confirming order and barista seeing it in admin chat?
- *Target*: <1 second; current async design supports this.

**OQ-005**: Should bot send customer follow-up messages when barista updates Status in Sheet (e.g., "Your coffee is ready!"), or is v1 "pull" only?
- *Impact*: Requires background polling/webhook; adds complexity.
- *Suggested Decision*: v1 = customer checks bot or receives via manual admin message; v2 = auto-notifications.

**OQ-006**: In case of duplicate orders (e.g., customer taps "Confirm" twice very quickly), how should bot handle?
- *Suggested Decision*: Use Telegram message ID + timestamp deduplication; show "Order already placed" if resubmit within 10 sec.

**OQ-007**: Should non-Ukrainian phone numbers be rejected hard, or allow with warning?
- *Suggested Decision*: Hard reject (per BR-004); assume all customers are Ukrainian.

**OQ-008**: Is there a maximum number of concurrent orders the café can handle per day? Should bot warn or queue if exceeded?
- *Suggested Decision*: No limit in v1; monitor; v2 = queue management.

---

## 8. Glossary

| Term | Definition | Example / Notes |
|------|-----------|-----------------|
| **FSM** | Finite State Machine; dialogue flow with defined states and transitions. | States: MenuSelection → TimeInput → PhoneInput → Confirmation → Submitted |
| **StatesGroup** | aiogram class grouping FSM states for a workflow. | `class OrderFSM(StatesGroup): menu_state = State()` |
| **Router** | aiogram handler container; one per feature module. | `order_router = Router()` |
| **Inline Keyboard** | Telegram buttons embedded in message body; callback-based. | Drink selection: buttons ["Американо", "Капучино", "Латте"] |
| **Admin Chat** | Private Telegram group/channel where barista receives order alerts. | Configured via `ADMIN_CHAT_ID` in .env |
| **Order ID** | Unique identifier per order; format `ORD-YYYYMMDD-###`. | `ORD-20260617-001` |
| **Pickup Time** | Requested time when customer will collect their order. | "14:45" (absolute) or "+10 min" (relative) |
| **Status** | Order lifecycle flag in Google Sheet. | "Submitted" → "Preparing" → "Ready" → "Picked Up" |
| **Obfuscation** | Hiding sensitive data (e.g., showing last 2 digits of phone in admin chat). | "+380501234567" → "+38050***567" |
| **Idempotency** | Repeated identical requests produce same result; no duplicates. | Resubmit same order within 10s → shows "Already placed" |
| **Edge Case** | Unusual or boundary condition requiring special handling. | Time in past, empty price cell, blocked bot. |
| **Callback Data** | Metadata attached to inline buttons; identifies button action. | Button "Капучино" → callback `"drink_cappuccino_300"` |
| **Gspread** | Python library for Google Sheets API (sync wrapper around Google API). | Wrapped in `asyncio.to_thread()` in async code. |

---

## 9. Dependencies & Assumptions

### Assumptions
1. Café owner has a Google account and can create/share a Google Sheet.
2. Café has a stable internet connection.
3. All customers use Telegram (mobile-first audience).
4. Café operates single location with fixed hours (09:00–21:00 UTC+3).
5. No payment processing; cash-only transactions.
6. Barista manually updates Status column in Google Sheet (no automated workflow v1).
7. Customer phone numbers are trusted for contact purposes (no opt-out initially).

### External Dependencies
- **PostgreSQL 13+** (for user/order redundancy)
- **Google Cloud Project** with Sheets API enabled
- **Telegram Bot API** (via aiogram)
- **Python 3.11+** runtime

---

## 10. Success Criteria (MVP Definition of Done)

✅ Customer can browse dynamic menu from Google Sheet  
✅ Customer can select drink, specify time, validate phone, confirm order  
✅ Order written to Google Sheet "Orders" tab within <1 second  
✅ Barista receives admin chat notification immediately  
✅ All required validations pass (time, phone, menu integrity)  
✅ Customer can cancel at any FSM step  
✅ Invalid inputs trigger helpful retry prompts (not errors)  
✅ Code deploys to production environment without manual config changes (all via .env)  
✅ No hardcoded chat IDs, phone regex, or price data (all configurable or dynamic)

---

## 11. Next Steps (for Agents 2–5)

1. **Agent 2** (Architect): Design FSM flow diagram; define database schema; plan Google Sheets integration architecture.
2. **Agent 3** (Backend): Implement CRUD operations, FSM handlers, Google Sheets integration, validation logic.
3. **Agent 4** (QA/Testing): Write pytest tests for validators, FSM transitions, edge cases (OQ-001–008).
4. **Agent 5** (DevOps/Deployment): Set up PostgreSQL, Google Sheets auth, environment variables, CI/CD pipeline.

---

**Document Version History**
| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-06-17 | Business Analyst | Initial requirements document |

