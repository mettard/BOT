# ☕ CoffeeRun Bot

**CoffeeRun Bot** is a Telegram bot designed for convenient ordering of coffee and other beverages. The bot allows users to view an up-to-date menu (dynamically loaded from Google Sheets), select a pickup time, place orders, and send them to administrators.

This project is an MVP (Minimum Viable Product) that includes integration with a PostgreSQL database for storing history and Google Sheets for easy menu management and order monitoring by the barista.

---

## 🌟 Key Features

### 🧑‍💻 For Customers:
* **Dynamic Menu:** The list of beverages and prices is loaded directly from a Google Sheet.
* **Flexible Time Selection:** Ability to specify pickup time in a relative format (e.g., "in 10 min") or absolute format (e.g., "15:30").
* **Data Validation:** Checks for cafe working hours, maximum advance order time limit, and correct phone number formatting (Ukrainian format).
* **Order Management:** Ability to cancel an order at any stage of the process.
* **History:** View the history of previous orders.

### 👨‍🍳 For Administrators (Baristas):
* **Instant Notifications:** Receive new orders in a dedicated group or via personal messages.
* **Status Management:** Convenient "Accept" and "Cancel" inline buttons that instantly update the order status in the database and Google Sheets.

---

## 🛠 Tech Stack

* **Language:** Python 3.11+
* **Framework:** [Aiogram 3](https://docs.aiogram.dev/en/latest/) (async Telegram API wrapper)
* **Database:** PostgreSQL (with `asyncpg` driver)
* **ORM & Migrations:** SQLAlchemy 2.0 (async) + Alembic
* **Configuration:** Pydantic Settings
* **Integration:** Google Sheets API (`gspread` + `google-auth`)
* **Containerization:** Docker and Docker Compose
* **Formatting & Linters:** Black, isort, Mypy

---

## 🏗 Project Architecture

```text
bot/
├── config.py           # Configuration (Pydantic Settings)
├── main.py             # Entry point, bot initialization
├── database/           # PostgreSQL interaction (SQLAlchemy)
│   ├── engine.py       # Connection setup
│   ├── models.py       # Table models (Users, Orders)
│   └── crud.py         # CRUD operations
├── handlers/           # Message handlers (Routers)
│   ├── order.py        # Customer ordering flow
│   ├── admin.py        # Admin panel
│   └── history.py      # Order history
├── keyboards/          # Inline and Reply keyboards
├── middlewares/        # Middlewares (DB session, Throttle)
├── services/           # Business logic and integrations
│   ├── google_sheets.py # Google API interaction
│   ├── validators.py   # Time and phone validation
│   └── notifications.py # Admin notifications
└── states/             # State machines (FSM)
```

---

## 📄 Documentation

Detailed information about requirements, UI/UX, and technical decisions can be found in the following files:
* `01_requirements.md` — Business requirements.
* `02_product_spec.md` — MVP scope, acceptance criteria.
* `03_ux_spec.md` — UI specification, message templates.
* `04_implementation_notes.md` — Architectural decisions.
* `IMPLEMENTATION_SUMMARY.md` — Implementation status and MVP summary.
