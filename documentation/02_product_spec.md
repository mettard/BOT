# 02. Product Specification — CoffeeRun MVP

**Date:** 2026-06-17 | **Version:** MVP 1.0

---

## 1. MVP Scope & Backlog Split

### MVP (Must-haves) — v1.0
- US-001: Customer views menu dynamically from Google Sheets
- US-002: Customer selects drink via inline buttons
- US-003: Customer enters pickup time with validation (future, 09:00-21:00, ≤12h ahead)
- US-004: Customer provides Ukrainian phone number with format validation
- US-005: Order confirmation displayed to customer
- US-006: Order written to Google Sheets (Orders tab) with timestamp
- US-007: Admin receives order notification in dedicated chat
- US-008: Admin acknowledges receipt via inline button
- US-009: Owner updates menu prices/items in Google Sheets dynamically
- US-010: Canceled order removed from queue (customer clicks /cancel)

### Backlog (Should/Could) — v2+
- US-011: Customer views order status/history
- US-012: Follow-up notifications ("Ready for pickup")
- US-013: Rating system after order completion
- US-014: Promo codes/discounts
- US-015: Recurring orders (favorite drinks)
- US-016: Bot analytics dashboard
- US-017: Payment integration
- US-018: Multi-language support

---

## 2. Feature Descriptions

| Feature | Behavior |
|---------|----------|
| **Menu Display** | On `/start` or `/menu`, bot loads menu from Google Sheets "Menu" tab. Shows drink name, volume, price in inline buttons. Hides drinks with missing/empty price. |
| **Drink Selection** | User taps inline button (Drink name). Bot transitions to time input prompt. |
| **Time Input** | Bot asks "When will you pick up?" User enters relative time ("10 min", "20 min") or clock time ("15:30"). Validation: must be future time, within cafe hours (09:00-21:00), and ≤12 hours ahead. If invalid, show error + re-prompt same state. |
| **Phone Entry** | Bot asks "Enter your phone number for confirmation" (format: +380xxxxxxxxx, 380xxxxxxxxx, or 0xxxxxxxxx). Validation via UA_PHONE_PATTERN regex. On error, re-prompt. |
| **Confirmation** | Bot shows order summary: drink, volume, price, pickup time. Buttons: "Confirm" or "Cancel". |
| **Order Submit** | User clicks "Confirm". Bot writes order to Google Sheets Orders tab (Customer name auto-fetch from Telegram, phone, drink, price, pickup time, status="New"). Sends notification to admin chat. Shows customer "Order confirmed. See you soon!" |
| **Admin Notification** | Admin chat receives formatted message: Order ID, customer name, phone, drink, pickup time, status. Two inline buttons: "✓ Acknowledged" (status→Ready), "✗ Cancel" (deletes order). |
| **Order Cancellation** | User/Admin presses "/cancel" at any FSM state or "Cancel" button. Order removed from queue if not yet confirmed, or marked "Canceled" in Sheets if confirmed. User sees "Order canceled." |

---

## 3. FSM Diagrams

### OrderFSM (Main Customer Flow)
```
[START] 
  ↓ /start or existing order trigger
[MenuSelection] ← inline buttons: Drink-001, Drink-002, ...
  ↓ user clicks drink
[TimeInput] ← text input: "10 min" / "15:30"
  ↓ valid time entered
[PhoneInput] ← text input: "+380501234567"
  ↓ valid phone entered
[Confirmation] ← buttons: "Confirm" / "Cancel"
  ↓ user clicks "Confirm"
[OrderSubmitted] → write to Sheets, notify admin
  ↓
[Complete] (FSM cleared)

Cancellation from ANY state:
  Any state + /cancel or "Cancel" button → [Canceled] → [Complete]

On errors (invalid time/phone):
  [TimeInput] + bad input → stay in [TimeInput], show error
  [PhoneInput] + bad input → stay in [PhoneInput], show error
```

### AdminFSM (Admin Acknowledgment)
```
[OrderNotification] ← sent to admin chat with inline buttons
  ↓ admin clicks "✓ Acknowledged"
[OrderReady] → status in Sheets = "Ready"
  ↓ customer can pick up
  
OR
  ↓ admin clicks "✗ Cancel"
[OrderCanceled] → status in Sheets = "Canceled"
```

---

## 4. Bot Commands Reference

| Command | Trigger | Behavior |
|---------|---------|----------|
| `/start` | User enters chat or taps START button | Load menu, show drink list, enter MenuSelection state |
| `/cancel` | User types at any FSM state | Exit FSM, clear state, show "Canceled" message, return to idle |
| `/menu` | User types (optional shortcut) | Reload menu, return to MenuSelection state |
| `/help` | User types (optional) | Show bot usage guide (one-time, no FSM transition) |

---

## 5. Admin Panel Specification

**Admin Chat Notification Format:**
```
📋 New Order — ID: ORD-202406170001
👤 Customer: John Doe
📱 Phone: +380501234567
☕ Drink: Cappuccino (250ml) — ₴95
⏰ Pickup: Today 15:30
🔔 Status: New

[✓ Acknowledged] [✗ Cancel Order]
```

**Admin Actions via Inline Buttons:**
- **✓ Acknowledged**: Sets status to "Ready" in Sheets; sends message to customer (optional v2 feature)
- **✗ Cancel**: Marks status "Canceled" in Sheets; optionally notifies customer

**Admin Configuration (future v2):**
- Set cafe hours (default: 09:00-21:00)
- Set max advance booking (default: 12h)
- Enable/disable notifications

---

## 6. Google Sheets Data Contract

### Sheet 1: "Menu" (Read-only by bot, managed by Owner)
| Column | Type | Required | Notes |
|--------|------|----------|-------|
| Drink Name | String | Yes | e.g., "Cappuccino", "Americano" |
| Volume (ml) | Integer | Yes | e.g., 250, 300 |
| Price (₴) | Float | No | If empty/0, hide from menu + log warning |
| Available | Boolean | Yes | If False, hide from inline buttons |
| Description | String | No | "Rich foam, smooth espresso" |

**Read Frequency:** Every `/start` + background sync every 5-10 min (detects price changes)

### Sheet 2: "Orders" (Write by bot, read by Owner)
| Column | Type | Notes |
|--------|------|-------|
| Timestamp | DateTime | ISO 8601, e.g., "2024-06-17T15:30:00+03:00" |
| Order ID | String | Format: ORD-YYYYMMDDnnnn (auto-increment) |
| Customer Name | String | From Telegram profile |
| Phone | String | Ukrainian format, validated |
| Drink | String | Menu item name |
| Price | Float | Cached at order time (in case menu changes) |
| Pickup Time | DateTime | ISO 8601 |
| Status | String | "New" → "Ready" → "Completed" OR "Canceled" |
| Notes | String | Optional customer notes (future) |

**Write Pattern:** On order confirmation, bot appends row. On admin action, bot updates Status column.

### Sheet 3: "Config" (Read-only, manual setup)
| Key | Value | Notes |
|-----|-------|-------|
| cafe_open | "09:00" | Cafe opening time |
| cafe_close | "21:00" | Cafe closing time |
| max_advance_minutes | 720 | Max 12 hours ahead = 720 min |
| admin_chat_id | "-100123456789" | Telegram admin group chat ID |

---

## 7. Acceptance Criteria

### Feature: Menu Display
- [ ] Menu loads in <2 sec on `/start`
- [ ] All items with valid prices show as inline buttons
- [ ] Items with missing/empty price are hidden (no error shown to user)
- [ ] Menu updates reflect Google Sheets changes within 10 min

### Feature: Time Input Validation
- [ ] Rejects times in the past (e.g., "10:00" if current time is 10:15) → show error in <1 sec
- [ ] Rejects times outside 09:00-21:00 → show error
- [ ] Rejects times >12 hours ahead → show error
- [ ] Accepts valid times and transitions to PhoneInput

### Feature: Phone Validation
- [ ] Accepts "+380501234567" format ✓
- [ ] Accepts "380501234567" format ✓
- [ ] Accepts "0501234567" format ✓
- [ ] Rejects non-Ukrainian formats (e.g., "+1234567890") → show error
- [ ] Validation completes in <1 sec

### Feature: Order Submission
- [ ] Order written to Google Sheets within 1 sec of confirmation
- [ ] Order contains: customer name, phone, drink, price, pickup time, status="New"
- [ ] Order ID auto-generated (ORD-YYYYMMDDnnnn format)
- [ ] Notification sent to admin chat within 2 sec
- [ ] Customer receives "Order confirmed" message

### Feature: Admin Acknowledgment
- [ ] Admin clicks "✓ Acknowledged" → Sheets status updates to "Ready" within 1 sec
- [ ] Admin clicks "✗ Cancel" → Sheets status updates to "Canceled" within 1 sec
- [ ] Admin receives confirmation of action (e.g., checkmark emoji)

### Feature: Cancellation
- [ ] `/cancel` at any FSM state clears order and returns to menu
- [ ] Confirmed orders marked "Canceled" in Sheets, not deleted
- [ ] User sees "Order canceled" confirmation

---

## 8. Implementation Milestones

### Phase 1: FSM Foundation & Core Menu (Week 1)
- [ ] Database setup: users, orders tables
- [ ] FSM states implemented (MenuSelection, TimeInput, PhoneInput, Confirmation)
- [ ] Google Sheets Menu tab read (async gspread integration)
- [ ] Inline button rendering for drinks
- **Deliverable:** User can select drink, see time/phone prompts (no validation yet)

### Phase 2: Validation & Order Entry (Week 1-2)
- [ ] Time validation logic (past, hours, 12h limit)
- [ ] Phone regex validation (Ukrainian format)
- [ ] Google Sheets Orders tab write
- [ ] Order ID generation
- [ ] FSM state guards (conditional transitions)
- **Deliverable:** Orders written to Sheets with valid data

### Phase 3: Admin Notifications & Inline Buttons (Week 2)
- [ ] Admin chat integration (send formatted order messages)
- [ ] Inline buttons: "Acknowledged", "Cancel Order"
- [ ] Button callbacks update Sheets status
- [ ] Error handling: invalid credentials, API rate limits
- **Deliverable:** Admin receives and acts on orders in real-time

### Phase 4: Testing, Error Handling & Deployment (Week 2-3)
- [ ] Unit tests: validators, CRUD operations
- [ ] Integration tests: Sheets sync, Telegram API mocks
- [ ] Edge case testing: menu gaps, time edge cases, session interruptions
- [ ] Production environment setup (PostgreSQL, env vars)
- [ ] Deployment to server
- **Deliverable:** MVP v1.0 live, stable, monitored

---

## MVP Assumptions (from Open Questions)

- **OQ-001 (Special instructions):** Deferred to v2. MVP does not support customer notes/special requests.
- **OQ-005 (Follow-up notifications):** MVP v1 = pull-based only (customer checks order status manually). v2 will add auto push notifications.
- **OQ-006 (Duplicate prevention):** Implement via message_id + timestamp deduplication in backend to prevent accidental double-submits.
- **OQ-003 (Blocked bot):** Acceptable for MVP—order lost if user blocks bot mid-FSM. Log event, document for v2 recovery.
- **OQ-004 (Menu gaps):** If price is empty/None, hide drink from menu. Log warning. Show fallback: "Menu unavailable, please contact cafe."

---

**Status:** ✅ **MVP Product Specification COMPLETE**

This spec is ready for handoff to **Developer** for implementation.
