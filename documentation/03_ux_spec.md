# 03. UX/UI Специфікація — CoffeeRun Bot

Дата: 2026-06-17 | Версія: MVP 1.0

---

## 1. Conversation Flow Map

### 1.1 Happy Path (Успішне замовлення)

```
User                          Bot                           System
  │                            │                              │
  ├─ /start ────────────────→  │                              │
  │                            ├─ Load Menu from Sheets ──→  │
  │                            │                              │
  │  ← MSG-001 (Menu) + KB-001  │                              │
  │    [Cappuccino] [Americano] │                              │
  │    [Latte] [Espresso]       │                              │
  │                            │                              │
  ├─ Click [Cappuccino] ─────→ │ (MenuSelection state)        │
  │                            │                              │
  │  ← MSG-002 (Time prompt)    │                              │
  │    "Коли забраш замовлення?"│                              │
  │                            │                              │
  ├─ Text: "10 min" ─────────→ │ (TimeInput state)            │
  │                            ├─ Validate time ──→          │
  │                            │ (is future? 09-21? ≤12h?)   │
  │                            │                              │
  │  ← MSG-003 (Phone prompt)   │                              │
  │    "Номер телефону: +380..." │                              │
  │                            │                              │
  ├─ Text: "+380501234567" ──→ │ (PhoneInput state)           │
  │                            ├─ Validate phone ──→         │
  │                            │ (UA format?)                  │
  │                            │                              │
  │  ← MSG-004 (Confirmation)   │                              │
  │    Summary + [✓ Confirm]    │                              │
  │              [✗ Cancel]     │                              │
  │                            │                              │
  ├─ Click [✓ Confirm] ──────→ │ (Confirmation state)        │
  │                            ├─ Write to Sheets ────→      │
  │                            ├─ Send admin notif. ──→      │
  │                            │                              │
  │  ← MSG-005 (Success!)       │                              │
  │    "Замовлення підтверджено" │                              │
  │                            │                              │
  │                     (FSM cleared, idle)                    │
```

### 1.2 Error Path (Невалідні дані)

```
Time Input Error:
  User: "25:00" / "08:00" / "tomorrow" (not relative)
    ↓
  Bot: MSG-101 (Error: invalid time)
    "❌ Неправильний час. Введи як: '10 хв', '15 хв' або '15:30'."
    [Re-prompt: stay in TimeInput state]
  ↓
  User: "15 хв" (valid)
    ↓ → PhoneInput

Phone Input Error:
  User: "+1234567890" / "1234567890" / "+38050" (invalid format)
    ↓
  Bot: MSG-102 (Error: invalid phone)
    "❌ Неправильний формат. Введи номер: +380xxxxxxxxx або 0xxxxxxxxx"
    [Re-prompt: stay in PhoneInput state]
  ↓
  User: "+380501234567" (valid)
    ↓ → Confirmation
```

### 1.3 Cancel Path (Скасування)

```
From ANY state:
  User: /cancel  OR  Click [✗ Cancel] button
    ↓
  Bot: MSG-006 (Cancel confirm)
    "Замовлення скасовано."
  ↓
  FSM cleared → Idle
  (User can /start again)

If already confirmed (order in Sheets):
  User: /cancel
    ↓
  Bot: MSG-007 (Already submitted)
    "Замовлення вже відправлене. Зв'яжись з кав'ярнею, щоб скасувати."
  ↓
  No state change
```

### 1.4 Menu Refresh on Error (Empty Price)

```
Bot loads Menu from Sheets:
  ├─ Cappuccino: ₴95 ✓ (show)
  ├─ Americano: ₴85 ✓ (show)
  ├─ Special: (empty price) ✗ (hide)
  │   └─ Log warning: "Menu item 'Special' has no price"
  └─ Latte: ₴80 ✓ (show)

User sees: Cappuccino | Americano | Latte
  (Special hidden, no error message)
```

---

## 2. Message Templates Catalog

**Format:** HTML (parse_mode: HTML)  
**Limits:** ≤4096 symbols per message

### 2.1 Greeting & Menu Messages

| ID | Назва | Текст | Змінні | parse_mode |
|----|-------|-------|---------|-----------|
| MSG-001 | Menu Display | `☕ <b>Меню CoffeeRun</b>\n\nОбери свій улюблений напій:\n\n{menu_items}` | `{menu_items}` = список кнопок | HTML |
| MSG-002 | Time Prompt | `⏰ <b>Коли ти забираш замовлення?</b>\n\nВведи час на зразок: <code>10 хв</code> або <code>15:30</code>` | — | HTML |
| MSG-003 | Phone Prompt | `📱 <b>Вкажи свій телефон</b>\n\nФормат: <code>+380xxxxxxxxx</code> або <code>0xxxxxxxxx</code>` | — | HTML |
| MSG-004 | Confirmation | `✅ <b>Підтвердження замовлення</b>\n\n☕ Напій: <b>{drink_name}</b> ({volume}ml)\n💰 Ціна: <b>₴{price}</b>\n⏰ Час забору: <b>{pickup_time}</b>\n\nСе правильно? Натисни <b>Підтвердити</b>` | `{drink_name}`, `{volume}`, `{price}`, `{pickup_time}` | HTML |
| MSG-005 | Success | `✅ <b>Замовлення підтверджено!</b>\n\nТвій номер замовлення: <b>{order_id}</b>\n⏰ Час забору: <b>{pickup_time}</b>\n\nДякуємо! 🎉` | `{order_id}`, `{pickup_time}` | HTML |
| MSG-006 | Cancelled | `❌ Замовлення скасовано.\n\nМожеш зробити нове замовлення, натисни /start` | — | HTML |
| MSG-007 | Already Submitted | `⚠️ Замовлення вже відправлене. Щоб скасувати, зв'яжись з кав'ярнею: +380501234567` | — | HTML |

### 2.2 Error Messages

| ID | Ситуація | Текст | parse_mode |
|----|----------|-------|-----------|
| MSG-101 | Invalid Time | `❌ <b>Неправильний час.</b>\n\nВведи як: <code>10 хв</code>, <code>20 хв</code> або <code>15:30</code>\n\n⏰ Кав'ярня працює: 09:00–21:00\nМакс. упередження: 12 годин` | HTML |
| MSG-102 | Invalid Phone | `❌ <b>Неправильний формат номера.</b>\n\nПриклади коректних номерів:\n• <code>+380501234567</code>\n• <code>380501234567</code>\n• <code>0501234567</code>` | HTML |
| MSG-103 | Time in Past | `❌ Цей час вже пройшов. Виберіть майбутній час.` | HTML |
| MSG-104 | Time Outside Hours | `❌ Кав'ярня працює лише 09:00–21:00. Виберіть час у межах роботи.` | HTML |
| MSG-105 | Time Too Far | `❌ Максимальне упередження — 12 годин. Виберіть раніший час.` | HTML |
| MSG-106 | Menu Empty | `⚠️ <b>Меню на даний момент недоступне.</b>\n\nСпробуй пізніше або зв'яжись з кав'ярнею.` | HTML |
| MSG-107 | Sheets Error | `⚠️ <b>Технічна помилка.</b>\n\nМе не можемо отримати меню. Спробуй ще раз за хвилину.` | HTML |

### 2.3 Help & Optional Messages

| ID | Назва | Текст | Команда | parse_mode |
|----|-------|-------|---------|-----------|
| MSG-201 | Help | `🤖 <b>Як користуватися CoffeeRun?</b>\n\n1. Натисни /start\n2. Обери напій\n3. Вкажи час забору\n4. Введи номер телефону\n5. Підтвердь замовлення\n\n💡 Команди:\n/start — новий заказ\n/cancel — скасувати\n/help — цей текст` | /help | HTML |

---

## 3. Keyboard Specifications

### 3.1 Reply Keyboards (Очні кнопки, які видаляються після натискання)

| ID | Назва | Кнопки | Умова показу | Приклад |
|----|-------|---------|-------------|---------|
| — | — | — | — | — |

*Note: MVP не використовує Reply Keyboards. Всі дії — через Inline Keyboards.*

### 3.2 Inline Keyboards (Вбудовані кнопки в повідомленні)

#### KB-001: Menu Buttons (Динамічна клавіатура)

| callback_data | Текст | Дія |
|---------------|-------|-----|
| `drink_001` | ☕ Cappuccino 250ml — ₴95 | Set state: TimeInput; store drink_id = 001 |
| `drink_002` | ☕ Americano 300ml — ₴85 | Set state: TimeInput; store drink_id = 002 |
| `drink_003` | ☕ Latte 350ml — ₴90 | Set state: TimeInput; store drink_id = 003 |
| ... | ... | ... |

**Формат кнопки:** `{emoji} {drink_name} {volume}ml — {price}`  
**Кількість рядків:** 1 кнопка = 1 рядок  
**Умова:** Показати лише напої з доступною ціною (Available=True, Price>0)

#### KB-002: Confirmation Buttons

| callback_data | Текст | Дія | Умова |
|---------------|-------|-----|-------|
| `confirm_order` | ✅ Підтвердити | Write to Sheets, notify admin, show MSG-005 | Always available |
| `cancel_order` | ❌ Скасувати | Clear FSM state, show MSG-006 | Always available |

**Розташування:** 2 кнопки в ряд, side-by-side

#### KB-003: Cancel Inline Button (доступна з будь-якого стану)

| callback_data | Текст | Дія |
|---------------|-------|-----|
| `cancel_flow` | ⏸ Скасувати | Exit FSM, show MSG-006 |

**Розташування:** Окремий рядок під основним контентом

---

## 4. Admin Notification Templates

### 4.1 Order Notification Message (Адміну)

**Message ID:** ADM-001  
**parse_mode:** HTML

```
📋 <b>Нове замовлення</b>

<b>ID замовлення:</b> ORD-20240617001
<b>Час отримання:</b> 2024-06-17 15:30:00

👤 <b>Клієнт:</b> John Doe
📱 <b>Телефон:</b> <code>+380501234567</code>

☕ <b>Напій:</b> Cappuccino (250ml)
💰 <b>Ціна:</b> ₴95

🔔 <b>Статус:</b> 🆕 Нове

[✓ Прийняти]  [✗ Скасувати]
```

### 4.2 Admin Inline Buttons (Для замовлення)

| callback_data | Текст | Дія | Результат |
|---------------|-------|-----|-----------|
| `admin_ack_{order_id}` | ✓ Прийняти | Update Sheets: Status → "Ready" | Bot sends: ✅ Замовлення прийнято |
| `admin_cancel_{order_id}` | ✗ Скасувати | Update Sheets: Status → "Canceled" | Bot sends: ❌ Замовлення скасовано |

**Формат callback_data:** `admin_ack_ORD20240617001` (max 64 символи)

### 4.3 Admin Reaction Messages

| Дія | Повідомлення адміну | Час |
|-----|-------------------|-----|
| Прийняти замовлення | `✅ Замовлення ORD-20240617001 прийнято. Готуємо!` | <1 sec |
| Скасувати замовлення | `❌ Замовлення ORD-20240617001 скасовано.` | <1 sec |

---

## 5. Error & Validation Messages

### 5.1 Input Validation Rules

| Поле | Правило | Error Message | Re-prompt State |
|------|---------|---------------|-----------------|
| **Time** | Майбутній час | MSG-103 | TimeInput |
| **Time** | В межах 09:00–21:00 | MSG-104 | TimeInput |
| **Time** | ≤12 годин упередження | MSG-105 | TimeInput |
| **Phone** | +380 / 380 / 0 + 9 цифр | MSG-102 | PhoneInput |
| **Phone** | Префікс: 39,50,63,66,67,68,73,91–99 | MSG-102 | PhoneInput |
| **Menu** | ≥1 напій з ціною | MSG-106 (if 0 items) | MenuSelection |

### 5.2 System Error Handling

| Error | User Message | Admin Log | Recovery |
|-------|--------------|-----------|----------|
| Sheets read fails | MSG-107 | ERROR: gspread timeout | Retry in 60s |
| Sheets write fails | "Помилка при збереженні. Спробуй ще раз." | ERROR: Orders tab write | Retry 3x, then fail with contact info |
| Telegram API error | "Технічна помилка. Спробуй пізніше." | ERROR: telegram api | Queue message, retry async |
| Invalid Sheets format | (hide items) | WARNING: Menu column mismatch | Use fallback menu |

---

## 6. Empty State Messages

| Стан | Сценарій | Повідомлення |
|------|----------|--------------|
| **Menu Empty** | 0 напоїв з ціною в Sheets | MSG-106: "Меню на даний момент недоступне." |
| **Invalid Price** | Ціна = empty/0 для напою | (Напій приховується, без помилки) |
| **No Orders Today** | Admin chat, 0 замовлень | (No auto-message; admin sees nothing) |
| **Sheets Unreachable** | gspread auth/network error | MSG-107: "Технічна помилка." + contact info |

---

## 7. UX Guidelines

### 7.1 Design Principles

- **Простота:** Максимум 3 кроки до замовлення (Menu → Time → Phone → Confirm)
- **Скоростейність:** Кожна операція <2 сек
- **Ясність:** Кожне повідомлення має 1 дію + наслідок
- **Безпека:** Валідація на кожному кроці, без спуму
- **Мова:** Українська для клієнтів, англійська в коді/логах

### 7.2 Message Length Limits

| Тип | Ліміт | Приклад |
|-----|-------|---------|
| Message body | ≤4096 символів | OK для MSG-001 |
| Inline button text | ≤20 символів | "✓ Прийняти" |
| callback_data | ≤64 символи | `admin_ack_ORD20240617001` |

### 7.3 Button Layout Rules

- **1 лінія:** До 2 кнопок side-by-side (e.g., [✓] [✗])
- **2+ лінії:** 1 кнопка per line (e.g., меню напоїв)
- **Max width:** 2 кнопки на рядок, інакше переносити на новий рядок

### 7.4 Emoji Usage

| Emoji | Сенс | Use Case |
|-------|------|----------|
| ☕ | Напій | Меню, замовлення |
| ⏰ | Час | Time input, pickup time |
| 📱 | Телефон | Phone input |
| ✅ | Success | Confirmation, acknowledgment |
| ❌ | Error/Cancel | Cancellation, rejection |
| 📋 | Замовлення | Admin notifications |
| 🆕 | Новий | Status: New |
| ⚠️ | Внимание | Warnings |

### 7.5 State Transition Rules

- **Timeout:** Якщо користувач неактивний >30 хв → FSM expired (clean up)
- **Cancel anytime:** /cancel доступна з БУДЬ-ЯКОГО стану
- **No backtracking:** Користувач не може повернутися на крок назад (лише скасувати весь флоу)
- **Re-prompt on error:** На помилку валідації — залишити в тому ж стані, показати MSG-1xx, дозволити повтор

### 7.6 Accessibility & Localization

- **Шрифт:** Монофонт для кодів (e.g., `+380501234567`)
- **Контраст:** HTML-теги (<b>, <code>) для підкреслення
- **Мобільність:** Кнопки — ≥44px для дотику (Telegram default)
- **Доступність:** Емодзі + текст в кожній кнопці

### 7.7 Feedback & Confirmation

- **Позитивна дія:** ✅ + дружелюбний текст (e.g., "Дякуємо! 🎉")
- **Помилка:** ❌ + пояснення + підказка (e.g., "Введи як: 10 хв")
- **Дія адміна:** Реакція <1 сек (e.g., "✅ Замовлення прийнято")

---

## 8. Flow Summary Table

| Сценарій | MSG | KB | Час | Результат |
|----------|-----|----|----|-----------|
| User /start | MSG-001 | KB-001 | <2s | Menu shown |
| User selects drink | — | — | — | TimeInput state |
| User enters time (valid) | MSG-002 | — | <1s | PhoneInput state |
| User enters time (invalid) | MSG-101 | — | <1s | Re-prompt TimeInput |
| User enters phone (valid) | MSG-003 | — | <1s | Confirmation state |
| User enters phone (invalid) | MSG-102 | — | <1s | Re-prompt PhoneInput |
| User confirms order | MSG-004 | KB-002 | — | Review order |
| User clicks ✓ Confirm | MSG-005 | — | <2s | Order → Sheets, Admin notified |
| User clicks ✗ Cancel | MSG-006 | — | <1s | FSM cleared |
| Admin clicks ✓ Acknowledge | ADM-001 | — | <1s | Status: Ready in Sheets |
| Admin clicks ✗ Cancel | — | — | <1s | Status: Canceled in Sheets |

---

**Status:** ✅ **UX/UI Специфікація COMPLETE**

Готово для передачі розробникам та тестерам.
