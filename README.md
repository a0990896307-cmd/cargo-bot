# Cargo Bot — Telegram shipment booking

Booking, dispatch and tracking for a cargo/freight service. Customers create
shipments, drivers accept jobs and update status, admins see totals.

Python 3.13 · aiogram 3 · SQLAlchemy 2 · SQLite or PostgreSQL · 61 tests.

## What it does

**Customer**
- `/start` → main menu
- **New shipment** → guided form: pickup, dropoff, cargo type, weight, price
  (auto-priced at 3.0/kg, minimum 10)
- **My shipments** → list with current status
- **Track** → send a ticket code like `CRG-ABCD`, get a progress bar
- Push notification on every status change

**Driver**
- **Become a driver** → `Sam | +380501112233`
- **Available jobs** → open shipments broadcast on creation
- **My jobs** → assigned work with action buttons
- Status actions: picked up → in transit → delivered, or cancel

**Admin**
- `/admin_stats` → totals by status and delivered revenue
  (gated by `ADMIN_IDS`)

## Shipment lifecycle

```
new → assigned → picked_up → in_transit → delivered
 └────────────── cancel allowed from any non-terminal state ──────────────┘
```

Transitions are declared in `cargo_bot/models.py` (`ALLOWED_TRANSITIONS`) and
enforced in `cargo_bot/services.py`. Skipping a step raises
`InvalidTransition`; terminal states cannot move.

Every change writes an append-only row to `status_events` with the previous
status, the actor and a timestamp.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env      # then fill in BOT_TOKEN
set -a && source .env && set +a

python -m scripts.seed     # optional: 7 demo shipments in various states
python -m cargo_bot       # start polling
```

Demo ticket codes after seeding: `CRG-xxxx` (printed by the seed script).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `BOT_TOKEN` | — | Telegram token, required |
| `DATABASE_URL` | `sqlite+pysqlite:///cargo.db` | SQLite or PostgreSQL DSN |
| `ADMIN_IDS` | empty | Comma-separated IDs for `/admin_stats` |
| `CURRENCY` | `$` | Symbol shown to users |
| `MAX_WEIGHT_KG` | `10000` | Per-shipment weight ceiling |

PostgreSQL needs no code change — set `DATABASE_URL` and `pip install
psycopg[binary]`.

## Layout

```
cargo_bot/
  models.py      SQLAlchemy tables, status enum, transition table
  services.py    business rules; no Telegram import
  handlers.py    aiogram handlers, thin wrappers over services
  keyboards.py   reply and inline keyboards
  render.py      message formatting in one place
  main.py        entrypoint, per-update session middleware
scripts/seed.py  demo data
tests/           61 tests
```

## Tests

```bash
pytest
```

Covers validation rules, the full state machine, assignment permissions,
audit history, queries and stats, plus wiring checks that every user-facing
button and command resolves to a real handler and that ordinary chat text is
not swallowed by a keyboard filter.

Tests need no network and no Telegram token.

## Production notes

- Add authentication on `message.bot` calls; the notification helper
  currently swallows delivery errors so one dead customer cannot break a flow.
- FSM storage is in-memory. For restarts, pass a persistent storage to
  `Dispatcher(storage=...)`.
- Rate-limit customer/driver message handlers if the bot becomes public.
- Run behind a webhook for scale; polling is fine for a single process.