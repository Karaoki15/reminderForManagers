
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
import re
import random

from aiogram import Dispatcher, F, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

file_handler = logging.FileHandler("bot.log", encoding="utf-8")
file_handler.setLevel(logging.INFO)

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)

formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, stream_handler],
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)
logger.info("Логирование запущено. Все события пишем в bot.log")

API_TOKEN = "YOUR_API_TOKEN"  # TODO: Вставьте свой токен
OWNER_ID = 000000000  # TODO: Вставьте свой ID владельца

MANAGER_IDS = {
    1: 1111111111,  # TODO: Вставьте ID менеджера 1
    2: 2222222222,  # TODO: Вставьте ID менеджера 2
    3: 3333333333,  # TODO: Вставьте ID менеджера 3
}

MANAGER_NAMES = {
    1: "Manager1",  # TODO: Имя менеджера 1
    2: "Manager2",  # TODO: Имя менеджера 2
    3: "Manager3"   # TODO: Имя менеджера 3
}

KIEV_TZ = pytz.timezone("Europe/Kiev")
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class OwnerAssignTask(StatesGroup):
    choosing_manager = State()
    original_message_content_type = State()
    original_message_file_id = State()
    original_message_text = State()
    original_message_caption = State()

DB_PATH = "tasks.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        chat_id INTEGER,
        type TEXT,
        file_id TEXT,
        text_ TEXT,
        caption TEXT,
        next_reminder_delta INTEGER,
        deadline TEXT,
        status TEXT,
        message_id INTEGER,
        source TEXT,
        manager_num INTEGER
    )
    """)
    conn.commit()
    try:
        c.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in c.fetchall()]
        if "manager_num" not in columns:
            logger.info("Столбец 'manager_num' отсутствует. Добавляем...")
            c.execute("ALTER TABLE tasks ADD COLUMN manager_num INTEGER")
            conn.commit()
            logger.info("Столбец 'manager_num' успешно добавлен.")
        else:
            logger.debug("Столбец 'manager_num' уже существует в таблице 'tasks'.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при проверке/модификации таблицы 'tasks': {e}")
    conn.close()
    logger.info("База данных (tasks.db) инициализирована (структура проверена/обновлена).")


def save_task_to_db(task_id: str, data: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    deadline_str = data["deadline"].isoformat() if data["deadline"] else None
    c.execute("""
    INSERT OR REPLACE INTO tasks 
    (task_id, chat_id, type, file_id, text_, caption, next_reminder_delta, deadline, status, message_id, source, manager_num)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_id, data["chat_id"], data["type"], data["file_id"], data["text"],
        data["caption"], data["next_reminder_delta"], deadline_str, data["status"],
        data["message_id"], data["source"], data.get("manager_num")
    ))
    conn.commit()
    conn.close()
    logger.debug(f"Задача {task_id} сохранена/обновлена в БД.")

def load_tasks_from_db() -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT task_id, chat_id, type, file_id, text_, caption, next_reminder_delta, deadline, status, message_id, source, manager_num FROM tasks")
    rows = c.fetchall()
    conn.close()
    tasks = {}
    for row_data in rows:
        (task_id, chat_id, type_, file_id, text_, caption,
         next_reminder_delta, deadline_str, status, message_id, source, manager_num) = row_data
        deadline = datetime.fromisoformat(deadline_str) if deadline_str else None
        tasks[task_id] = {
            "chat_id": chat_id, "type": type_, "file_id": file_id, "text": text_,
            "caption": caption, "next_reminder_delta": next_reminder_delta,
            "deadline": deadline, "status": status, "message_id": message_id,
            "source": source, "manager_num": manager_num
        }
    logger.info(f"Загружено задач из БД: {len(tasks)}")
    return tasks

def delete_task_from_db(task_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
    conn.commit()
    conn.close()
    logger.debug(f"Задача {task_id} удалена из БД.")

scheduler = AsyncIOScheduler(timezone=KIEV_TZ)
tasks_dict = {}

def generate_task_id() -> str:
    return f"task_{datetime.now(KIEV_TZ).timestamp()}_{random.randint(1000,9999)}"

def make_done_keyboard(task_id: str) -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(text="Выполнено", callback_data=f"done:{task_id}")
    return InlineKeyboardMarkup(inline_keyboard=[[button]])

async def schedule_reminder(task_id: str, reminder_minutes: int = None):
    task = tasks_dict.get(task_id)
    if not task or task["status"] != "active":
        logger.debug(f"Задача {task_id} не активна или не найдена, напоминание не запланировано.")
        return

    if reminder_minutes is None:
        reminder_minutes = task["next_reminder_delta"]
    
    if reminder_minutes == 0 and task["source"] not in ["manager_rem", "owner"]:
         reminder_minutes = task["next_reminder_delta"]

    when = datetime.now(tz=KIEV_TZ) + timedelta(minutes=reminder_minutes)
    tasks_dict[task_id]["deadline"] = when
    save_task_to_db(task_id, tasks_dict[task_id])
    logger.info(f"Следующее напоминание для задачи {task_id} запланировано на {when.strftime('%Y-%m-%d %H:%M:%S %Z')}")

async def check_tasks():
    now = datetime.now(tz=KIEV_TZ)
    for task_id, data in list(tasks_dict.items()):
        if data["status"] == "active" and data["deadline"] and data["deadline"] <= now:
            logger.info(f"Задача {task_id} для чата {data['chat_id']} просрочена. Дедлайн: {data['deadline'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
            try:
                if data.get("message_id"):
                    await bot.delete_message(data["chat_id"], data["message_id"])
                    logger.debug(f"Старое сообщение {data['message_id']} для задачи {task_id} удалено.")
            except Exception as e:
                logger.error(f"Ошибка удаления сообщения {data.get('message_id')} для задачи {task_id}: {e}")

            try:
                msg = await send_task_message(task_id, reminder=True)
                if msg:
                    data["message_id"] = msg.message_id
                    save_task_to_db(task_id, data)
                else:
                    logger.warning(f"send_task_message для {task_id} не вернуло сообщение.")
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания для задачи {task_id}: {e}")
                continue 
            
            current_task_data = tasks_dict.get(task_id)
            if current_task_data and current_task_data["status"] == "active":
                 await schedule_reminder(task_id)
            else:
                logger.info(f"Задача {task_id} больше не активна после попытки отправки напоминания, следующее не планируем.")

async def send_task_message(task_id: str, reminder=False):
    task = tasks_dict.get(task_id)
    if not task:
        logger.warning(f"Задача {task_id} не найдена в tasks_dict при попытке отправки.")
        return None
    if task["status"] != "active":
        logger.debug(f"Задача {task_id} не активна ({task['status']}), не отправляем.")
        return None

    chat_id = task["chat_id"]
    msg_type = task["type"]
    file_id = task["file_id"]
    kb = make_done_keyboard(task_id)
    
    prefix_text = "‼️ Напоминание ‼️\n" if reminder else ""

    if task["source"] == "owner" and task.get("manager_num"):
        manager_num = task.get("manager_num")
        manager_name = MANAGER_NAMES.get(manager_num, f"Менеджер {manager_num}")
        prefix_text = f"🔔 Новая Задача для {manager_name} 🔔\n{prefix_text}"
    elif task["source"] != "owner" and not reminder :
         prefix_text = "🔔 Новая задача 🔔\n"
    
    text_to_send = prefix_text

    try:
        if msg_type == "text":
            text_to_send += task["text"]
            msg = await bot.send_message(chat_id, text_to_send, reply_markup=kb)
        else:
            caption_to_send = text_to_send + (task["caption"] or "")
            if msg_type == "photo":
                msg = await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption_to_send, reply_markup=kb)
            elif msg_type == "document":
                msg = await bot.send_document(chat_id=chat_id, document=file_id, caption=caption_to_send, reply_markup=kb)
            elif msg_type == "video":
                msg = await bot.send_video(chat_id=chat_id, video=file_id, caption=caption_to_send, reply_markup=kb)
            else:
                text_to_send += f"\n[Тип {msg_type} не обрабатывается подробно]\n" + (task["text"] or "")
                msg = await bot.send_message(chat_id=chat_id, text=text_to_send, reply_markup=kb)
        
        logger.info(f"Отправлено {'напоминание' if reminder else 'сообщение'} для задачи {task_id} в чат {chat_id}. Тип: {msg_type}.")
        return msg
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения для задачи {task_id} в чат {chat_id}: {e}")
        if "bot was blocked by the user" in str(e) or "user is deactivated" in str(e) or "chat not found" in str(e):
            logger.warning(f"Менеджер {chat_id} заблокировал бота или чат не найден. Деактивирую задачу {task_id}.")
            if task_id in tasks_dict:
                tasks_dict[task_id]["status"] = "error_user_blocked"
                save_task_to_db(task_id, tasks_dict[task_id])
        return None

def extract_message_data(message: Message):
    prefix = ""
    if message.content_type == ContentType.TEXT:
        return {"type": "text", "file_id": None, "text": prefix + message.text, "caption": None}
    elif message.content_type == ContentType.PHOTO:
        return {"type": "photo", "file_id": message.photo[-1].file_id, "text": None, "caption": prefix + (message.caption or "")}
    elif message.content_type == ContentType.DOCUMENT:
        return {"type": "document", "file_id": message.document.file_id, "text": None, "caption": prefix + (message.caption or "")}
    elif message.content_type == ContentType.VIDEO:
        return {"type": "video", "file_id": message.video.file_id, "text": None, "caption": prefix + (message.caption or "")}
    else:
        return {"type": "text", "file_id": None, "text": prefix + f"Получен контент типа {message.content_type} (не обрабатывается)", "caption": None}

@dp.message(CommandStart())
async def cmd_start(message: Message):
    manager_list_str_parts = []
    for num in sorted(MANAGER_IDS.keys()): 
        name = MANAGER_NAMES.get(num, f"Менеджер {num}")
        manager_list_str_parts.append(f"  - {name}") 
    manager_list_for_start = "\n".join(manager_list_str_parts)
    if not manager_list_for_start:
        manager_list_for_start = "  (Менеджеры не настроены)"

    text = (
        "Привет! Я бот-напоминалка.\n"
        f"Доступные менеджеры:\n{manager_list_for_start}\n\n"
        "Команды:\n"
        "1) Если вы владелец, отправьте боту сообщение (текст, фото, документ). "
        "Затем выберите, какому менеджеру его адресовать. "
        "Менеджеру придёт задача с напоминанием.\n\n"
        "2) Менеджеры могут поставить себе напоминание:\n"
        "   <code>/rem [описание] [HH:MM]</code> (сегодня или завтра, если время прошло)\n"
        "   <code>/rem [описание] [DD.MM] [HH:MM]</code> (конкретная дата и время)\n"
        "В указанное время придёт напоминание, потом каждые 30 минут, пока не нажать «Выполнено».\n\n"
    )

    manager_1_name = MANAGER_NAMES.get(1, "Менеджер 1")
    if 1 in MANAGER_IDS: # Показываем блок только если менеджер 1 настроен
        text += (
            f"<b>Для {manager_1_name}:</b>\n"
            " - 15 число и последний день месяца\n"
            " - Понедельник 10:00\n"
            " - Суббота 19:00 и 19:30\n\n"
        )

    m2_name = MANAGER_NAMES.get(2)
    m3_name = MANAGER_NAMES.get(3)
    m2_m3_names_list = []
    
    if 2 in MANAGER_IDS and m2_name: m2_m3_names_list.append(m2_name)
    if 3 in MANAGER_IDS and m3_name: m2_m3_names_list.append(m3_name)
    
    if m2_m3_names_list:
        m2_m3_display_name = " и ".join(m2_m3_names_list)
        text += (
            f"<b>Для {m2_m3_display_name} (ежемесячно):</b>\n"
            " - 1 число: Запушить клиентов на оплаты, выставить счета.\n"
            " - 5 число: Проверить оплаты, допушить неоплативших.\n"
            " - 15 число: Запушить клиентов на оплату 50%.\n"
            " - 20 число: Проверить оплаты 50%, допушить неоплативших.\n"
            " - Последний день месяца (28.02 или 30 число): Напомнить дизайнерам о таблицах.\n"
        )
    
    text += "Все напоминания повторяются каждые 30 минут, пока не 'Выполнено'."
    
    await message.answer(text)
    logger.info(f"/start от пользователя {message.from_user.id}")

@dp.message(F.chat.id == OWNER_ID, ~CommandStart())
async def from_owner_handler(message: Message, state: FSMContext):
    extracted_data = extract_message_data(message)
    await state.update_data(
        original_message_content_type=extracted_data["type"],
        original_message_file_id=extracted_data["file_id"],
        original_message_text=extracted_data["text"],
        original_message_caption=extracted_data["caption"]
    )
    
    buttons = []
    for num in sorted(MANAGER_IDS.keys()): 
        name = MANAGER_NAMES.get(num, f"Менеджер {num}") 
        buttons.append(InlineKeyboardButton(text=f"{name}", callback_data=f"assign_to_manager:{num}"))
        
    keyboard_rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    await message.reply("Какому менеджеру отправить эту задачу?", reply_markup=keyboard)
    await state.set_state(OwnerAssignTask.choosing_manager)
    logger.info(f"Владелец ({message.from_user.id}) отправил сообщение, ожидает выбора менеджера.")

@dp.callback_query(OwnerAssignTask.choosing_manager, F.data.startswith("assign_to_manager:"))
async def owner_assigns_to_manager_callback(callback: CallbackQuery, state: FSMContext):
    manager_num = int(callback.data.split(":")[1])
    target_manager_chat_id = MANAGER_IDS.get(manager_num)
    manager_name = MANAGER_NAMES.get(manager_num, f"Менеджер {manager_num}")

    if not target_manager_chat_id:
        await callback.answer("Ошибка: менеджер не найден.", show_alert=True)
        logger.error(f"Ошибка выбора менеджера: Номер {manager_num} не найден в MANAGER_IDS.")
        await state.clear()
        return

    user_data = await state.get_data()
    await state.clear()

    task_id = generate_task_id()
    tasks_dict[task_id] = {
        "chat_id": target_manager_chat_id, "type": user_data["original_message_content_type"],
        "file_id": user_data["original_message_file_id"], "text": user_data["original_message_text"],
        "caption": user_data["original_message_caption"], "next_reminder_delta": 30,
        "deadline": None, "status": "active", "message_id": None, "source": "owner",
        "manager_num": manager_num
    }
    save_task_to_db(task_id, tasks_dict[task_id])
    msg = await send_task_message(task_id, reminder=False) 
    if msg:
        tasks_dict[task_id]["message_id"] = msg.message_id
        save_task_to_db(task_id, tasks_dict[task_id])
    await schedule_reminder(task_id, 30) 
    
    await callback.message.edit_text(f"✅ Отправлено {manager_name}.")
    await callback.answer()
    logger.info(f"Владелец назначил задачу {task_id} менеджеру {manager_name} (№{manager_num}, ID: {target_manager_chat_id}).")

@dp.message(Command("rem"), F.chat.id.in_(MANAGER_IDS.values()))
async def manager_reminder_handler(message: Message):
    full_text = message.text.replace('/rem', '', 1).strip()
    time_match = re.search(r'(\d{1,2}:\d{2})$', full_text) 
    date_match = None
    if time_match:
        date_candidate_str = full_text[:time_match.start()].strip()
        date_match_candidate = re.search(r'(\d{1,2}\.\d{1,2})$', date_candidate_str)
        if date_match_candidate:
            date_match = date_match_candidate

    time_str = None
    date_str = None
    desc = ""
    
    if time_match:
        time_str = time_match.group(1)
        temp_text = full_text[:time_match.start()].strip()
        if date_match:
            date_str = date_match.group(1)
            desc = temp_text[:date_match.start()].strip()
        else:
            desc = temp_text
    else:
        return await message.answer("❌ Не указано время в формате HH:MM в конце сообщения.")

    if not desc:
        return await message.answer("❌ Описание задачи не может быть пустым.")

    try:
        now = datetime.now(KIEV_TZ)
        year = now.year
        hours, minutes = map(int, time_str.split(':'))
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            raise ValueError("Неверный формат времени")

        if date_str:
            day, month = map(int, date_str.split('.'))
            if not (1 <= month <= 12 and 1 <= day <= 31):
                 raise ValueError("Неверный формат даты (день/месяц вне диапазона)")
            target_time = KIEV_TZ.localize(datetime(year=year, month=month, day=day, hour=hours, minute=minutes))
        else:
            target_time = KIEV_TZ.localize(datetime(year=now.year, month=now.month, day=now.day, hour=hours, minute=minutes))
            if target_time < now:
                target_time += timedelta(days=1)
        
        if target_time < now:
             return await message.answer(f"❌ Указанное время уже прошло! ({target_time.strftime('%d.%m.%Y %H:%M')})")

    except ValueError as e:
        logger.warning(f"Ошибка парсинга даты/времени для /rem: {e}. Строка: '{full_text}'")
        return await message.answer(f"❌ Неверный формат даты или времени. Используйте DD.MM HH:MM или HH:MM. (Ошибка: {e})")

    task_id = generate_task_id()
    current_manager_num = next((num for num, mid in MANAGER_IDS.items() if mid == message.chat.id), None)
    
    tasks_dict[task_id] = {
        "chat_id": message.chat.id, "type": "text", "file_id": None,
        "text": f"🗓️ Ваше напоминание: {desc}", "caption": "",
        "next_reminder_delta": 30, "deadline": target_time, "status": "active",
        "message_id": None, "source": "manager_rem", "manager_num": current_manager_num
    }
    save_task_to_db(task_id, tasks_dict[task_id])
    manager_name_for_log = MANAGER_NAMES.get(current_manager_num, f"Менеджер {current_manager_num}")
    await message.answer(f"✅ Напоминание установлено на {target_time.strftime('%d.%m.%Y %H:%M %Z')}")
    logger.info(f"Менеджер {manager_name_for_log} (ID: {message.chat.id}, №{current_manager_num}) создал задачу {task_id} на {target_time.strftime('%d.%m.%Y %H:%M')}")

async def _create_scheduled_task_for_manager(manager_chat_id: int, manager_num: int, reminder_text: str, source: str):
    task_id = generate_task_id()
    manager_name = MANAGER_NAMES.get(manager_num, f"Менеджер {manager_num}")
    tasks_dict[task_id] = {
        "chat_id": manager_chat_id, "type": "text", "file_id": None,
        "text": reminder_text, "caption": "", "next_reminder_delta": 30,
        "deadline": None, "status": "active", "message_id": None,
        "source": source, "manager_num": manager_num
    }
    save_task_to_db(task_id, tasks_dict[task_id])
    logger.info(f"Создана scheduled задача {task_id} для менеджера {manager_name} (№{manager_num}, ID: {manager_chat_id}), текст: {reminder_text}")
    msg = await send_task_message(task_id, reminder=False)
    if msg:
        tasks_dict[task_id]["message_id"] = msg.message_id
        save_task_to_db(task_id, tasks_dict[task_id])
    await schedule_reminder(task_id, tasks_dict[task_id]["next_reminder_delta"])

@dp.callback_query(F.data.startswith("done:"))
async def done_task_handler(callback: CallbackQuery):
    task_id = callback.data.split(":")[1]
    task = tasks_dict.get(task_id)

    if not task:
        await callback.answer("Задача не найдена или уже выполнена.", show_alert=True)
        logger.warning(f"Попытка выполнить несуществующую/удаленную задачу {task_id} пользователем {callback.from_user.id}")
        try: await callback.message.delete()
        except Exception: pass
        return

    if task["status"] != "active":
        await callback.answer("Задача уже не активна.", show_alert=True)
        logger.info(f"Задача {task_id} уже не активна (статус: {task['status']}), проигнорировано.")
        return

    if task.get("message_id"):
        try:
            await bot.delete_message(task["chat_id"], task["message_id"])
            logger.debug(f"Сообщение {task['message_id']} задачи {task_id} удалено.")
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение {task.get('message_id')} задачи {task_id}: {e}")

    task_status_before_del = task["status"]
    task_source_before_del = task["source"]
    task_manager_num_before_del = task.get("manager_num")

    delete_task_from_db(task_id) 
    if task_id in tasks_dict:
        del tasks_dict[task_id] 

    await callback.answer("Задача выполнена!")
    
    manager_name_for_log = MANAGER_NAMES.get(task_manager_num_before_del, f"Менеджер {task_manager_num_before_del}") \
        if task_manager_num_before_del is not None else f"ID {callback.from_user.id}"
    logger.info(f"Задача {task_id} завершена менеджером {manager_name_for_log}.")

    if task_source_before_del == "owner":
        original_text = task.get("text", "") 
        original_caption = task.get("caption", "")
        
        content_summary = original_text if task.get("type") == "text" else original_caption
        if not content_summary and task.get("type") != "text": content_summary = f"({task.get('type')})"
        elif not content_summary: content_summary = "(пустое сообщение)"
        
        if task_manager_num_before_del is not None:
            manager_name_for_prefix = MANAGER_NAMES.get(task_manager_num_before_del, f"Менеджер {task_manager_num_before_del}")
            owner_task_prefix = f"🔔 Задача от Владельца для {manager_name_for_prefix} 🔔\n"
            if content_summary.startswith(owner_task_prefix):
                content_summary = content_summary.replace(owner_task_prefix, "", 1)
            # Также удалим префикс напоминания, если он есть
            reminder_prefix = "‼️ Напоминание ‼️\n"
            if content_summary.startswith(reminder_prefix):
                content_summary = content_summary.replace(reminder_prefix, "", 1).strip()


        max_len = 200
        if len(content_summary) > max_len: content_summary = content_summary[:max_len-3] + "..."
        
        completed_by_manager_name = MANAGER_NAMES.get(task_manager_num_before_del, f"Менеджер {task_manager_num_before_del}") \
            if task_manager_num_before_del is not None else "Неизвестный менеджер"

        try:
            await bot.send_message(OWNER_ID, f"✅ {completed_by_manager_name} выполнила задачу:\n{content_summary}")
            logger.info(f"Уведомили владельца ({OWNER_ID}) о выполнении задачи {task_id} менеджером {completed_by_manager_name}.")
        except Exception as e:
            logger.error(f"Не удалось уведомить владельца ({OWNER_ID}): {e}")


 # Дополнительные напоминания
async def send_saturday_morning_reminder():
    manager_num_target = 1
    manager_chat_id = MANAGER_IDS.get(manager_num_target)
    manager_name = MANAGER_NAMES.get(manager_num_target, f"Менеджер {manager_num_target}")
    if manager_chat_id:
        logger.info(f"Запуск субботнего утреннего напоминания (19:00) для {manager_name}.")
        text = "📂 Напоминаю сохранить все завершённые работы за неделю, чтобы ничего не потерялось."
        await _create_scheduled_task_for_manager(manager_chat_id, manager_num_target, text, "saturday_save_work_m1")
    else:
        logger.warning(f"{manager_name} не найден в MANAGER_IDS для субботнего напоминания.")

async def send_saturday_second_reminder():
    manager_num_target = 1
    manager_chat_id = MANAGER_IDS.get(manager_num_target)
    manager_name = MANAGER_NAMES.get(manager_num_target, f"Менеджер {manager_num_target}")
    if manager_chat_id:
        logger.info(f"Запуск субботнего второго напоминания (19:30) для {manager_name}.")
        text = "📊 Дать отчет Никите за неделю по: дизайнерам, клиентам, и в общем как идет все. Какие то свои наблюдения."
        await _create_scheduled_task_for_manager(manager_chat_id, manager_num_target, text, "saturday_report_m1")
    else:
        logger.warning(f"{manager_name} не найден в MANAGER_IDS для субботнего отчета.")

async def send_monday_morning_reminder():
    manager_num_target = 1
    manager_chat_id = MANAGER_IDS.get(manager_num_target)
    manager_name = MANAGER_NAMES.get(manager_num_target, f"Менеджер {manager_num_target}")
    if manager_chat_id:
        logger.info(f"Запуск понедельничного утреннего напоминания (10:00) для {manager_name}.")
        text = "🚀 Запушь клиентов, с которыми не дошло дело до оплаты, и закрой их."
        await _create_scheduled_task_for_manager(manager_chat_id, manager_num_target, text, "monday_push_clients_m1")
    else:
        logger.warning(f"{manager_name} не найден в MANAGER_IDS для понедельничного напоминания.")

async def check_monthly_dates():
    now = datetime.now(KIEV_TZ)
    day = now.day
    month = now.month
    year = now.year
    logger.info(f"Ежедневная проверка месячных дат: {day}.{month}.{year}")

    manager_1_id = MANAGER_IDS.get(1)
    manager_1_name = MANAGER_NAMES.get(1, "Менеджер 1")
    if manager_1_id:
        text_msg_m1 = None
        if day == 15:
            text_msg_m1 = ("🔔 Проверь, у кого из клиентов ещё не завершена оплата, и напомни им об этом. "
                        "Также посчитай выплаты для дизайнеров за 1-15 числа.")
        else:
            is_last_day_m1 = False
            if month == 2:
                is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
                if (is_leap and day == 29) or (not is_leap and day == 28): is_last_day_m1 = True
            elif month in [4, 6, 9, 11]: 
                if day == 30: is_last_day_m1 = True
            else: 
                if day == 31: is_last_day_m1 = True
            if is_last_day_m1:
                text_msg_m1 = (f"🔔 Проверь, у кого из клиентов ещё не завершена оплата, и напомни им об этом. "
                            f"Также посчитай выплаты для дизайнеров за 16-{day} числа.")
        if text_msg_m1:
            logger.info(f"Создание ежемесячной задачи для {manager_1_name}: {text_msg_m1}")
            await _create_scheduled_task_for_manager(manager_1_id, 1, text_msg_m1, "monthly_billing_m1")
    else:
        logger.warning(f"{manager_1_name} не найден в MANAGER_IDS для ежемесячных напоминаний.")

    managers_2_3_data = {}
    if 2 in MANAGER_IDS and 2 in MANAGER_NAMES: managers_2_3_data[2] = {"id": MANAGER_IDS[2], "name": MANAGER_NAMES[2]}
    if 3 in MANAGER_IDS and 3 in MANAGER_NAMES: managers_2_3_data[3] = {"id": MANAGER_IDS[3], "name": MANAGER_NAMES[3]}
    
    if not managers_2_3_data:
        logger.info("Менеджеры 2 и 3 (или их имена) не найдены, пропускаем их ежемесячные напоминания.")
    else:
        text_msg_m23 = None
        source_m23 = "monthly_m23"
        if day == 1:
            text_msg_m23 = "1️⃣ число: Запушить клиентов на оплаты и выставить счет на оплату."
            source_m23 += "_d1"
        elif day == 5:
            text_msg_m23 = "5️⃣ число: Просмотреть оплаты и запушить тех, кто не оплатил."
            source_m23 += "_d5"
        elif day == 15:
            text_msg_m23 = "1️⃣5️⃣ число: Запушить клиентов на оплату 50%."
            source_m23 += "_d15"
        elif day == 20:
            text_msg_m23 = "2️⃣0️⃣ число: Просмотреть оплаты и запушить тех, кто не оплатил (по 50%)."
            source_m23 += "_d20"
        else:
            is_last_day_m23 = False
            if month == 2:
                is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
                if (is_leap and day == 29) or (not is_leap and day == 28): is_last_day_m23 = True
            elif day == 30: is_last_day_m23 = True
            if is_last_day_m23:
                text_msg_m23 = ("‼️ Запушить своих дизайнеров, чтобы вписали все креативы "
                               "в нужные таблицы и проекты уже сегодня, т.к. завтра подбиваем все итоги месяца.")
                source_m23 += "_lastday"
        if text_msg_m23:
            for num, data in managers_2_3_data.items():
                logger.info(f"Создание ежемесячной задачи для {data['name']}: {text_msg_m23}")
                await _create_scheduled_task_for_manager(data['id'], num, text_msg_m23, source_m23)

 # Настройка планировщика задач
def setup_scheduler():
    scheduler.add_job(send_monday_morning_reminder, CronTrigger(day_of_week="mon", hour=10, minute=0, timezone=KIEV_TZ))
    scheduler.add_job(send_saturday_morning_reminder, CronTrigger(day_of_week="sat", hour=19, minute=0, timezone=KIEV_TZ))
    scheduler.add_job(send_saturday_second_reminder, CronTrigger(day_of_week="sat", hour=19, minute=30, timezone=KIEV_TZ))
    scheduler.add_job(check_tasks, 'interval', seconds=30, timezone=KIEV_TZ, id="check_tasks_job")
    scheduler.add_job(check_monthly_dates, CronTrigger(hour=10, minute=1, timezone=KIEV_TZ))
    logger.info("Задачи APScheduler настроены.")

 # Старт бота
async def on_startup():
    logger.info("Запуск бота...")
    global tasks_dict
    init_db()
    loaded_tasks = load_tasks_from_db()
    tasks_dict.update(loaded_tasks)
    logger.info(f"Загружено {len(tasks_dict)} задач из БД.")

    now = datetime.now(KIEV_TZ)
    active_tasks_to_reschedule_count = 0
    for task_id, task_data in list(tasks_dict.items()):
        if task_data["status"] == "active":
            active_tasks_to_reschedule_count +=1
            if not task_data.get("deadline") or task_data["deadline"] < now:
                logger.info(f"Задача {task_id} активна и требует немедленного внимания.")
                await schedule_reminder(task_id, 0)
        elif task_data["status"] == "error_user_blocked":
            logger.warning(f"Задача {task_id} имеет статус 'error_user_blocked'. Не активируется.")
    logger.info(f"{active_tasks_to_reschedule_count} активных задач обработано при запуске.")

    setup_scheduler()
    scheduler.start()
    logger.info("APScheduler запущен.")
    try:
        manager_names_str = ", ".join(MANAGER_NAMES.values()) if MANAGER_NAMES else "менеджеры не настроены"
        await bot.send_message(OWNER_ID, f"Бот успешно запущен! Активны менеджеры: {manager_names_str}.")
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение о запуске владельцу: {e}")

async def main():
    dp.startup.register(on_startup)
    await dp.start_polling(bot)

if __name__ == "__main__":
    if API_TOKEN == "YOUR_API_TOKEN" or OWNER_ID == 000000000:
        logger.critical("!!! НЕОБХОДИМО ЗАМЕНИТЬ API_TOKEN и OWNER_ID в коде !!!")
        exit(1)
    
    
    if set(MANAGER_IDS.keys()) != set(MANAGER_NAMES.keys()):
        logger.critical(f"!!! Ключи в MANAGER_IDS ({set(MANAGER_IDS.keys())}) и MANAGER_NAMES ({set(MANAGER_NAMES.keys())}) должны совпадать!!!")
        exit(1)
    
    if any(not isinstance(val, int) for val in MANAGER_IDS.values()):
        logger.critical(f"!!! ID Менеджеров в MANAGER_IDS должны быть корректными целыми числами. Текущие: {MANAGER_IDS} !!!")
        exit(1)
    
    if any(not isinstance(val, str) or not val for val in MANAGER_NAMES.values()):
        logger.critical(f"!!! Имена Менеджеров в MANAGER_NAMES должны быть непустыми строками. Текущие: {MANAGER_NAMES} !!!")
        exit(1)

    asyncio.run(main())
