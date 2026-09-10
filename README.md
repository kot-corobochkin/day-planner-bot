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

For a database created before task-planning fields were added, apply each
migration once in numeric order:

```bash
psql "$DATABASE_URL" -f app/db/migrations/001_add_task_planning_metadata.sql
psql "$DATABASE_URL" -f app/db/migrations/002_add_task_start_time_and_expand_scales.sql
psql "$DATABASE_URL" -f app/db/migrations/003_add_task_priority_history.sql
psql "$DATABASE_URL" -f app/db/migrations/004_add_daily_plan_available_minutes.sql
psql "$DATABASE_URL" -f app/db/migrations/005_set_daily_plan_capacity_defaults.sql
psql "$DATABASE_URL" -f app/db/migrations/006_add_ideas_and_unscheduled_tasks.sql
psql "$DATABASE_URL" -f app/db/migrations/007_set_default_task_duration.sql
psql "$DATABASE_URL" -f app/db/migrations/008_add_task_value_sources.sql
psql "$DATABASE_URL" -f app/db/migrations/009_add_ai_estimate_drafts.sql
psql "$DATABASE_URL" -f app/db/migrations/010_add_ai_estimate_item_decisions.sql
psql "$DATABASE_URL" -f app/db/migrations/011_add_daily_schedule_runs.sql
psql "$DATABASE_URL" -f app/db/migrations/012_add_daily_state_profiles.sql
psql "$DATABASE_URL" -f app/db/migrations/013_add_ai_plan_reflections.sql
psql "$DATABASE_URL" -f app/db/migrations/014_add_evening_reflections.sql
psql "$DATABASE_URL" -f app/db/migrations/015_add_task_categories.sql
psql "$DATABASE_URL" -f app/db/migrations/016_add_planning_agent_runs.sql
psql "$DATABASE_URL" -f app/db/migrations/017_add_planning_agent_checkpoints.sql
psql "$DATABASE_URL" -f app/db/migrations/018_add_plan_feedback.sql
psql "$DATABASE_URL" -f app/db/migrations/019_ignore_url_scheme_categories.sql
psql "$DATABASE_URL" -f app/db/migrations/020_add_weekly_achievement_reports.sql
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
API_KEY=your-provider-api-key
MODEL_NAME=google/gemma-4-31b-it:free
# Optional comma-separated fallback models, tried from left to right:
MODEL_FALLBACKS=google/gemma-4-26b-a4b-it:free,nvidia/nemotron-3-super-120b-a12b:free,openai/gpt-oss-20b:free,nvidia/nemotron-nano-9b-v2:free
# Optional for OpenRouter-compatible providers:
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=4096
```

Optional check-in schedule values use standard five-field cron syntax:

```env
MORNING_CHECKIN_CRON=0 9 * * *
MIDDAY_CHECKIN_CRON=0 13 * * *
EVENING_REVIEW_CRON=0 20 * * *
SCHEDULER_MISFIRE_GRACE_SECONDS=7200
```

The misfire grace period allows a reminder to run late after a short computer
sleep or network outage. Telegram request timeouts can also be adjusted with
`TELEGRAM_CONNECT_TIMEOUT_SECONDS`, `TELEGRAM_READ_TIMEOUT_SECONDS`,
`TELEGRAM_WRITE_TIMEOUT_SECONDS`, and `TELEGRAM_POOL_TIMEOUT_SECONDS`.

## Run

```bash
uv run python -m app.main
```

## Commands

- `/start` registers the Telegram user and shows help.
- `/help` показывает полный список команд.
- `/plan` создаёт или дополняет план на сегодня, завтра или будущую дату.
  Параметры задачи пишутся в той же строке, например:
  `Подготовить отчёт -длительность:2 ч -время начала:10:00 -дедлайн:19:00 -важность:5 -сложность:8 -контекст:компьютер`.
  Все параметры необязательны; важность и сложность принимают значения от 1 до 10.
  Короткая форма добавляет одну задачу сразу: `/plan 2026-10-01 Сдать кредитную карту в Сбербанк`.
  Если плана на дату ещё нет, он создаётся с типом `Смешанный`.
- `/plan_view YYYY-MM-DD` показывает нумерованный план выбранной даты.
- `/today` показывает план на сегодня и статусы задач. Если плана ещё нет,
  создаёт его с типом `Смешанный` и переносит незавершённые задачи из прошлых дней.
- `/done` выбирает дату и отмечает выбранную задачу выполненной.
- `/cancel_task` выбирает дату и отменяет выбранную задачу.
- `/move_task` выбирает исходную дату и номера задач, затем переносит их на другую дату.
  При третьем и последующих переносах бот отдельно попросит подтвердить перенос такой задачи.
- `/unschedule_task 1,2,3` убирает задачи из сегодняшнего плана в список без даты.
  Для другой даты: `/unschedule_task 2026-07-16 1,2,3`.
- `/task` выбирает дату и показывает карточку задачи, кроме отменённых. Быстрый формат: `/task today 6` или `/task 6` для сегодняшней задачи.
- `/task_edit` выбирает неотменённую задачу и изменяет её параметры, включая название через `-название:`.
- `/feasibility` предлагает норму времени по типу дня или позволяет указать своё значение, затем показывает, помещаются ли запланированные задачи в этот объём. При перегрузке можно перенести предложенные или выбранные по номерам задачи на завтра либо оставить план без изменений.
- `/plan_analysis_details [today|YYYY-MM-DD]` показывает подробный расчёт приоритетов.
- `/ai_estimate [today|YYYY-MM-DD]` получает AI-предложения важности, сложности и длительности; изменения применяются только после подтверждения.
- `/ai_plan [today|YYYY-MM-DD]` запускает ограниченного агента планирования: после опроса состояния он проверяет выполнимость, строит и проверяет порядок, но применяет расписание только после подтверждения. `/ai_plan_view [today|YYYY-MM-DD]` показывает применённое расписание.
- `/evening_reflection` задаёт 10 вечерних вопросов по задачам текущего дня и сохраняет ответы.
- `/category <категория>` показывает все запланированные задачи категории за сегодня, завтра и послезавтра. Категория — текст до первого `:` в названии, например `Бот: изменить название`.
- `/idea` сохраняет идеи по одной в строке, `/ideas` показывает идеи.
- `/inbox` сохраняет задачу без даты, `/backlog` показывает такие задачи.
- `/upcoming` показывает до 30 будущих задач, затем задачи без даты в оставшихся местах.
- `/schedule_task` назначает дату идее или задаче без даты.

Quick forms without dialogs: `/done 1,2,3`, `/task_edit 6 -важность:2`,
`/task_edit 6 -название:Новое название`,
`/move_task 1,5,6 tomorrow`. If the first argument is a task number or a list of
numbers, the source date is today. For another date use, for example,
`/done 2026-07-16 1,2,3`. Spaces after commas are optional: `1, 2, 3` works too.
Numbers match the visible `/today` order.
- `/status` показывает число задач и процент выполнения.
- `/stat week` показывает недельную статистику, выдаёт 1–2 ироничные AI-ачивки
  за результаты недели и назначает одну цель из одной или нескольких
  невыполненных задач. Одна обещанная ачивка разблокируется автоматически
  только после выполнения всех задач цели.

## Priorities

Every task starts with a neutral deterministic priority of `50/100`.
Importance changes it symmetrically around `5/10`, while deadlines and up to
three postponements can only raise it. Duration affects feasibility and move
recommendations, not priority. `/feasibility` groups tasks into critical,
high, elevated, normal, and low priority; `/plan_analysis_details` shows the
full calculation.

For today's feasibility analysis, available time is limited by the remaining
local `08:00-22:00` window. A 14-hour weekend capacity is therefore 14 hours
at 08:00 and reaches zero at 22:00; future plans retain their full capacity.

## Architecture

The code follows:

```text
Telegram -> Handlers -> Services -> Repositories -> PostgreSQL
```

Handlers receive Telegram updates and send responses. Services contain business logic. Repositories contain all SQL and use psycopg3 directly. No ORM or SQLAlchemy is used.

Detailed product rules are in [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md).
