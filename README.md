# Telegram Day Agent

MVP Telegram bot for daily planning. It registers users, creates a daily plan, stores tasks in PostgreSQL, marks tasks as done through inline buttons, reports progress, and sends scheduled check-ins.

## Prerequisites

- Python 3.11+
- uv
- PostgreSQL
- Telegram bot token from BotFather

## Install

```bash
uv sync
```

If dependencies are already installed, `uv` will reuse the existing environment.

## PostgreSQL Setup

Create a database:

```bash
createdb day_agent
```

Apply the schema:

```bash
psql postgresql://postgres:password@localhost:5432/day_agent -f app/db/schema.sql
```

Adjust the connection URL for your local PostgreSQL user/password.

## Configuration

Create `.env` from the example:

```bash
cp .env.example .env
```

Set:

```env
BOT_TOKEN=your-telegram-bot-token
DATABASE_URL=postgresql://postgres:password@localhost:5432/day_agent
DEFAULT_TIMEZONE=Europe/Moscow
```

Optional check-in schedule values use standard five-field cron syntax:

```env
MORNING_CHECKIN_CRON=0 9 * * *
MIDDAY_CHECKIN_CRON=0 13 * * *
EVENING_REVIEW_CRON=0 20 * * *
```

## Run

```bash
uv run python -m app.main
```

## Commands

- `/start` registers the Telegram user and shows help.
- `/plan` создаёт или дополняет план на сегодня, завтра или будущую дату.
- `/today` показывает план на сегодня и статусы задач.
- `/done` выбирает дату и отмечает выбранную задачу выполненной.
- `/cancel_task` выбирает дату и отменяет выбранную задачу.
- `/move_task` выбирает исходную дату и номера задач, затем переносит их на другую дату.
- `/status` показывает число задач и процент выполнения.

## Architecture

The code follows:

```text
Telegram -> Handlers -> Services -> Repositories -> PostgreSQL
```

Handlers receive Telegram updates and send responses. Services contain business logic. Repositories contain all SQL and use psycopg3 directly. No ORM or SQLAlchemy is used.

Detailed product rules are in [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md).
