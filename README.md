# reminderForManagers

<div align="center">
  <h1>Telegram Bot: Team Reminders & Task Dispatcher</h1>
  <p><strong>The owner creates tasks → the bot assigns them to managers → reminders keep pinging until “Done”.</strong></p>
  <p>
    <a href="#"><img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white"></a>
    <a href="#"><img alt="aiogram" src="https://img.shields.io/badge/aiogram-3.x-2C2D72"></a>
    <a href="#"><img alt="APScheduler" src="https://img.shields.io/badge/Scheduler-APScheduler-1E90FF"></a>
    <a href="#"><img alt="SQLite" src="https://img.shields.io/badge/Storage-SQLite-003B57?logo=sqlite&logoColor=white"></a>
  </p>
</div>

---

## 📚 Table of Contents

- [Overview](#about)
- [Why](#why)
- [Features](#features)
- [How It Works](#how)
- [User Flows](#flows)
- [Commands](#commands)
- [Technical Details](#tech)
- [Reliability & Logs](#reliability)
- [Data Schema](#schema)
- [Limitations](#limits)
- [Roadmap](#roadmap)
- [Author](#author)

## 🧭 Overview <a id="about"></a>

A production‑minded Telegram bot for day‑to‑day task management. The owner forwards content (text/photo/doc/video), assigns a manager, and the bot turns that message into a task with recurring reminders. The manager closes the task with a single button — the owner gets notified.

## 🎯 Why <a id="why"></a>

- Distribute tasks fast without extra chats and manual pings.
- Don’t lose anything: the bot keeps reminding until the task is closed.
- A single standard for recurring jobs (daily/weekly/monthly triggers).

## ✨ Features <a id="features"></a>

- **Owner task dispatching:** send text/photo/doc/video → pick a manager → the manager receives a task with a **“Done”** button.
- **Auto‑reminders:** repeat every **30 minutes** until **“Done”** is pressed.
- **/rem for managers:** personal reminders in formats `HH:MM` or `DD.MM HH:MM` (the bot interprets today/tomorrow automatically).
- **Scheduler presets:** ready‑to‑use cron‑like rules (Monday 10:00; Saturday 19:00/19:30; 1/5/15/20 and the last day of the month).
- **Content preservation:** text, photo, document, and video are supported; the task retains the essence of the original message.
- **Owner notifications:** when a task is closed, the owner receives a short report with a snippet of the content.
- **Task storage:** **SQLite** — survives restarts; active tasks and deadlines are restored on startup.
- **Timezone:** **Europe/Kyiv** — schedules run in local time.

## ⚙️ How It Works <a id="how"></a>

1. The owner sends a message and picks a manager.
2. The bot creates a task, sends it to the manager, and schedules reminders immediately.
3. Every 30 minutes the bot repeats the reminder until the manager presses **“Done”**.
4. Managers can set their own reminders with **/rem**.
5. Recurring tasks are created on schedule (daily/monthly presets).

## 🧭 User Flows <a id="flows"></a>

**Owner**

- Send content → pick a manager → the manager gets a task → on completion, receive a notification.

**Manager**

- Receive a task with a **“Done”** button → press it → the task is closed, the owner is notified.
- Set a personal reminder: `/rem Close report 18:30` or `/rem Invoices 05.09 10:00`.

## 💬 Commands <a id="commands"></a>

- **/start** — shows managers and a short guide; includes hints for preset schedules.
- **/rem** — create a personal reminder (time/date + description).

## 🧱 Technical Details <a id="tech"></a>

- **Stack:** Python 3.12, **aiogram 3.x** (FSM, filters), **APScheduler** (cron/interval), **SQLite**.
- **States:** FSM for the flow where the owner selects a manager.
- **Persistence:** tasks are stored in `tasks.db`; on startup the bot restores active tasks and reschedules reminders.
- **Content handling:** supports `text/photo/document/video` with captioning and summarization for the owner’s notification.
- **Time parsing:** human‑friendly parsers `HH:MM` and `DD.MM HH:MM` with validation.
- **Timezone:** Europe/Kyiv.

## 🛡️ Reliability & Logs <a id="reliability"></a>

- **Two logging channels:** to `bot.log` and to stdout.
- **Robust error handling:** graceful cleanup of outdated messages, protection from blocked/deactivated chats, proper task deactivation.
- **Idempotent startup:** active tasks are automatically restored and rescheduled.

## 🗃️ Data Schema <a id="schema"></a>

Table `tasks` (SQLite):

- `task_id` (PK), `chat_id`, `type` (`text|photo|document|video`), `file_id`, `text_`, `caption`,
- `next_reminder_delta` (minutes), `deadline` (ISO), `status`, `message_id`, `source` (`owner|manager_rem|...`), `manager_num`.

## 🚧 Limitations <a id="limits"></a>

- Reminders repeat every 30 minutes and require the manager to press **“Done”**.
- Manager and owner IDs are preconfigured (whitelist).

## 🗺️ Roadmap <a id="roadmap"></a>

- Admin panel (web/bot) with task feed and filters.
- Flexible repeat rules (15/30/60 minutes, quiet hours, SLA targets).
- Task templates by roles and projects.
- Export and reporting (CSV/Google Sheets).
- Channel/group notifications when SLAs are breached.

## 👤 Author <a id="author"></a>

**Vlad Khoroshylov** — Instagram: **@vlad.khoro**.

> Portfolio repository: showcases architecture, reliability, and practical automation of daily team processes.
