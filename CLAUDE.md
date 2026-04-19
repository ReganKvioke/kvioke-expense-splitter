# CLAUDE.md — Telegram Expense Splitting Bot

## Project Overview

Build a **Telegram bot** that allows a group of friends to log shared expenses, track who owes whom, and view spending breakdowns. All amounts are consolidated into **SGD** using live exchange rates.

---

## Tech Stack

- **Language:** Python 3.11+
- **Telegram SDK:** `python-telegram-bot` v20+ (async, feature-rich, well-documented)
- **Database:** SQLite via built-in `sqlite3` module (single-file, zero-config, perfect for small group use)
- **Exchange Rates:** Free API — `https://open.er-api.com/v6/latest/SGD` (no key required)
- **HTTP Client:** `httpx` (async HTTP for exchange rate calls)
- **Environment:** `python-dotenv` for `.env` loading
- **Package Manager:** pip with `requirements.txt`

---

## Project Structure

```
KviokeExpenseSplitter/
├── bot/
│   ├── __init__.py
│   ├── main.py               # Bot entry point, application builder, command registration
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── add.py            # /add command — multi-step ConversationHandler for logging expenses
│   │   ├── balances.py       # /balances command — show net balances & who owes most
│   │   ├── summary.py        # /summary command — expenses by day or category
│   │   ├── settle.py         # /settle command — record a payment between two people
│   │   └── help.py           # /help command — usage instructions
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── auth.py           # Mandatory: password-based access control decorator
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.py         # Table creation & migrations
│   │   ├── queries.py        # All DB read/write functions
│   │   └── database.py       # DB connection singleton
│   ├── services/
│   │   ├── __init__.py
│   │   ├── currency.py       # Fetch & cache exchange rates, convert to SGD
│   │   ├── splitting.py      # Splitting logic (equal, discrete/custom amounts)
│   │   └── balances.py       # Net balance calculation between all participants
│   └── utils/
│       ├── __init__.py
│       ├── format.py         # Number/currency formatting helpers
│       └── constants.py      # Supported currencies, category list
├── .env                      # BOT_TOKEN, BOT_PASSWORD, ADMIN_USER_IDS
├── requirements.txt
└── README.md
```

---

## Database Schema (SQLite)

### Table: `users`
| Column      | Type    | Notes                          |
|-------------|---------|--------------------------------|
| id          | INTEGER | Primary key, auto-increment    |
| telegram_id | TEXT    | Unique, the Telegram user ID   |
| display_name| TEXT    | Friendly name for display      |

### Table: `expenses`
| Column          | Type    | Notes                                      |
|-----------------|---------|--------------------------------------------|
| id              | INTEGER | Primary key, auto-increment                |
| paid_by_user_id | INTEGER | FK → users.id (who paid)                   |
| amount          | REAL    | Original amount in original currency       |
| currency        | TEXT    | ISO 4217 code (e.g. SGD, USD, JPY, EUR)   |
| amount_sgd      | REAL    | Converted amount in SGD at time of entry   |
| exchange_rate   | REAL    | Rate used for conversion (1 SGD = X foreign) |
| category        | TEXT    | e.g. food, transport, accommodation, misc  |
| description     | TEXT    | Free-text description                      |
| split_method    | TEXT    | "equal" or "discrete"                      |
| created_at      | TEXT    | ISO 8601 timestamp                         |
| group_chat_id   | TEXT    | Telegram group chat ID for scoping         |

### Table: `expense_splits`
| Column      | Type    | Notes                                 |
|-------------|---------|---------------------------------------|
| id          | INTEGER | Primary key, auto-increment           |
| expense_id  | INTEGER | FK → expenses.id                      |
| user_id     | INTEGER | FK → users.id (who owes this portion) |
| amount_sgd  | REAL    | This person's share in SGD            |

### Table: `settlements`
| Column        | Type    | Notes                              |
|---------------|---------|------------------------------------|
| id            | INTEGER | Primary key, auto-increment        |
| from_user_id  | INTEGER | FK → users.id (person paying back) |
| to_user_id    | INTEGER | FK → users.id (person receiving)   |
| amount_sgd    | REAL    | Amount settled in SGD              |
| created_at    | TEXT    | ISO 8601 timestamp                 |
| group_chat_id | TEXT    | Telegram group chat ID             |

---

## Bot Commands & Behavior

### `/add` — Log an Expense
Starts a **multi-step conversation** (use `python-telegram-bot` `ConversationHandler` with states):

1. **Amount & currency:** "How much? (e.g. `50 USD`, `30 SGD`, `5000 JPY`)"
   - Parse number + optional currency code; default to SGD if omitted
2. **Category:** Show inline keyboard with options: `food`, `transport`, `accommodation`, `sightseeing`, `activities`, `groceries`, `flight`, `others`
3. **Description:** "Short description? (e.g. `dinner at hawker centre`)"
4. **Split method:** Inline keyboard → `Equal` or `Custom`
   - **Equal:** Splits among all group members equally
   - **Custom:** Ask "Enter each person's share" — e.g. `@alice 10, @bob 20, @charlie 20`
5. **Confirm:** Show a summary and ask for confirmation before saving

On save:
- Fetch current exchange rate, convert to SGD, store both original and SGD amounts
- Create `expense_splits` rows for each participant

### `/balances` — Who Owes Whom
- Calculate **net balances** across all expenses and settlements within the group
- Display a sorted list showing each person's net position (positive = is owed, negative = owes)
- **Highlight who owes the most** at the top
- Show simplified suggested transfers to settle debts (minimize number of transactions)
- Format example:
  ```
  💰 Current Balances:
  
  🔴 Alice owes SGD 45.20 (owes the most)
  🟡 Bob owes SGD 12.00
  🟢 Charlie is owed SGD 57.20
  
  Suggested settlements:
  • Alice → Charlie: SGD 45.20
  • Bob → Charlie: SGD 12.00
  ```

### `/summary` — View Spending Breakdown
Accepts optional arguments:
- `/summary today` — expenses logged today
- `/summary week` — last 7 days
- `/summary month` — last 30 days
- `/summary category` — totals grouped by category
- Default (no args): last 7 days

Format output as a clean text table or list showing date, description, amount (SGD), paid by, and category.

### `/settle` — Record a Settlement
- `/settle @username 25` — records that you paid @username SGD 25
- Updates the balances accordingly

### `/help` — Show All Commands
- List every command with a short description and example usage

---

## Currency Handling

### Supported Currencies (minimum)
SGD, USD, EUR, GBP, JPY, KRW, MYR, THB, IDR, AUD, CNY, TWD, HKD, PHP, VND

### Exchange Rate Service
- Use `https://open.er-api.com/v6/latest/SGD` (free, no API key)
- **Cache rates for 1 hour** in memory to avoid excessive API calls
- Store the rate used at time of expense creation in the `expenses` table for audit trail
- Handle API failures gracefully — show error message and ask user to try again

---

## Splitting Logic

### Equal Split
- `amount_sgd / number_of_participants` for each person
- The payer is included as a participant (they paid, so others owe them)
- Handle rounding: assign remainder cents to the payer's share

### Discrete/Custom Split
- User specifies exact SGD amount per person
- Validate that individual amounts sum to the total
- If amounts are provided in original currency, convert each to SGD

---

## Balance Calculation Algorithm

For each group chat, to compute net balances:

```
For each user:
  net = (total SGD they paid for group expenses)
      - (total SGD they owe from expense_splits)
      - (total SGD they've sent via settlements)
      + (total SGD they've received via settlements)

Positive net = others owe them money
Negative net = they owe others money
```

For suggested settlements, use a **greedy simplification**: repeatedly match the person who owes the most with the person who is owed the most.

---

## Implementation Notes

- **Auto-register users:** When a user first interacts with the bot in a group, auto-create their `users` row using their Telegram ID and display name
- **Group scoping:** All data is scoped by `group_chat_id` so the bot works in multiple groups independently
- **Error handling:** Wrap all handlers in try/except. Show user-friendly error messages. Log errors with Python `logging` module
- **Input validation:** Validate all numeric inputs. Reject negative amounts. Reject unknown currencies
- **Timestamps:** Store all timestamps in UTC ISO 8601
- **Conversation timeout:** Use `ConversationHandler.TIMEOUT` — if a user doesn't respond within 5 minutes during the /add flow, cancel and inform them
- **Async throughout:** All handlers, DB calls, and HTTP requests should use `async`/`await`

---

## Access Control (Mandatory)

The bot uses a **dual-layer authentication** system. Every user must be authorized before they can use any command.

### Database Table: `authorized_users`
| Column      | Type    | Notes                                    |
|-------------|---------|------------------------------------------|
| id          | INTEGER | Primary key, auto-increment              |
| telegram_id | TEXT    | Unique, the Telegram user ID             |
| authorized_at | TEXT  | ISO 8601 timestamp of when access granted|
| authorized_by | TEXT  | "admin" or "password"                    |

### How It Works

1. **Admin whitelist:** The bot owner sets `ADMIN_USER_IDS` in `.env`. These users are always authorized and can manage access.
2. **Password gate:** All other users must run `/start <password>` with the correct password (set via `BOT_PASSWORD` in `.env`) to gain access. Once authenticated, their Telegram ID is saved to `authorized_users` and they never need the password again.

### Commands

- **`/start <password>`** — Authenticate with the bot. If password is correct, user is added to `authorized_users`. If already authorized, just greet them.
- **`/revoke @username`** — (Admin only) Remove a user's access.
- **`/users`** — (Admin only) List all authorized users.

### Auth Middleware

- Runs **before every command handler** (except `/start`)
- Checks if `ctx.from.id` exists in `authorized_users` or `ADMIN_USER_IDS`
- If not authorized → reply with "⛔ You don't have access. Use `/start <password>` to authenticate." and halt
- All unauthorized command attempts should be **logged to console** with the user's Telegram ID and username for monitoring

### Security Notes

- The password is a simple shared secret — suitable for a friend group, not enterprise security
- Store `BOT_PASSWORD` in `.env`, never hardcode
- Rate-limit `/start` attempts: max 3 incorrect passwords per user per hour, then temporarily block with a message "Too many attempts. Try again later."
- The password should **not** be echoed back in any bot response

---

## Environment Variables (.env)

```
BOT_TOKEN=<telegram-bot-token-from-botfather>
BOT_PASSWORD=<shared-password-for-friend-access>
ADMIN_USER_IDS=<comma-separated-telegram-user-ids>
```

---

## Development Commands

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Run the bot
python -m bot.main
```

---

## Dependencies (requirements.txt)

```
python-telegram-bot[ext]>=20.7
httpx>=0.27.0
python-dotenv>=1.0.0
```

---

## Testing Approach

- Test currency conversion with known rates
- Test equal splitting with odd amounts (rounding)
- Test balance calculation with multiple expenses and settlements
- Test edge cases: single person expense, expense with 0 amount (should reject), unknown currency

---

## Out of Scope (for now)

- Inline mode
- Receipt photo OCR
- Recurring expenses
- Multi-currency display (everything consolidates to SGD)
- Web dashboard