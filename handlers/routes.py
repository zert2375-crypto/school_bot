from aiogram import Router,F
from aiogram.filters import Command
from aiogram.types import InputMediaPhoto,CallbackQuery,Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
import aiosqlite
import dotenv
from os import getenv
from datetime import date,timedelta,datetime
from forms.hw import AddHomework
from aiogram.fsm.context import FSMContext

dotenv.load_dotenv(override=True)
ADMIN1_ID = int(getenv("ADMIN1_ID"))
ADMIN2_ID = int(getenv("ADMIN2_ID"))
router = Router()

DB_NAME = "Schedule.sql"
Days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]

WEEKDAYS_RU = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье"
}

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
                CREATE TABLE IF NOT EXISTS schedule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day_of_week TEXT NOT NULL,
                    lesson_number INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    classroom TEXT
                )
            """)

        await db.execute("""
                CREATE TABLE IF NOT EXISTS homework (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    task TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    file_id TEXT
                )
            """)

        await db.commit()

async def get_schedule_for_day(day: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            SELECT lesson_number, subject, classroom 
            FROM schedule 
            WHERE day_of_week = ? 
            ORDER BY lesson_number
            """,
            (day,),
        )
        return await cursor.fetchall()

async def add_homework_to_db(subject: str, task: str, due_date: str, file_id: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO homework (subject, task, due_date, file_id) VALUES (?, ?, ?, ?)",
            (subject, task, due_date, file_id)
        )
        await db.commit()

async def get_homework_by_date(target_date: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT subject, task, file_id FROM homework WHERE due_date = ?",
            (target_date,)
        )
        return await cursor.fetchall()

async def get_homework_next_week():
    today = date.today()
    days_until_monday = 7 - today.weekday()
    next_monday = today + timedelta(days=days_until_monday)
    next_sunday = next_monday + timedelta(days=6)

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            SELECT due_date, subject, task, file_id 
            FROM homework 
            WHERE due_date BETWEEN ? AND ? 
            ORDER BY due_date
            """,
            (next_monday.isoformat(), next_sunday.isoformat())
        )
        return await cursor.fetchall()

async def get_all_active_homework():
    today_str = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            SELECT id, due_date, subject, task 
            FROM homework 
            WHERE due_date >= ? 
            ORDER BY due_date
            """,
            (today_str,)
        )
        return await cursor.fetchall()

async def delete_homework_by_id(hw_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM homework WHERE id = ?", (hw_id,))
        await db.commit()

def get_main_reply_keyboard(user_id: str):
    if user_id != ADMIN1_ID or user_id != ADMIN2_ID:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Домашка")],
                [KeyboardButton(text="Расписание")]
            ],
            resize_keyboard=True
        )
    else:
        keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="Домашка")],
                    [KeyboardButton(text="Расписание")],
                    [KeyboardButton(text="Добавить дз")],
                    [KeyboardButton(text="Удалить дз")]
                ],
                resize_keyboard=True
            )
    return keyboard

def get_schedule_reply_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
        [KeyboardButton(text="Понедельник")],
        [KeyboardButton(text="Вторник")],
        [KeyboardButton(text="Среда")],
        [KeyboardButton(text="Четверг")],
        [KeyboardButton(text="Пятница")],
        [KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True
    )
    return keyboard

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Отмена")]],
    resize_keyboard=True
)

@router.message(Command("start"))
async def start(message: Message):
    await message.answer("Привет, я бот, созданный крутым типом для крутых типов из 10 \"В\" класса!",reply_markup=get_main_reply_keyboard(message.from_user.id))

@router.message(F.text=="Расписание")
async def show_schedule(message: Message):
    await message.answer("Выберите день недели",reply_markup=get_schedule_reply_keyboard())

@router.message(F.text == "Назад")
async def back_to_main_menu(message: Message):
    await message.answer(
        "Вы вернулись в главное меню",
        reply_markup=get_main_reply_keyboard(message.from_user.id)
    )

@router.message(F.text.in_(Days))
async def send_day_schedule(message: Message):
    day = message.text
    lessons = await get_schedule_for_day(day)

    if not lessons:
        await message.answer(
            f"На <b>{day}</b> уроков в расписании не найдено.",
            parse_mode="HTML"
        )
        return

    text = f"📚 <b>Расписание на {day} (10 «В»):</b>\n\n"
    for number, subject, classroom in lessons:
        # Добавляем номер кабинета в скобках, если он указан в базе
        cab_text = f" <i>(каб. {classroom})</i>" if classroom else ""
        text += f"<b>{number}.</b> {subject}{cab_text}\n"

    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "Домашка")
async def show_hw_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="На завтра", callback_data="hw_tomorrow")],
        [InlineKeyboardButton(text="На следующую неделю", callback_data="hw_next_week")]
    ])
    await message.answer("За какой период показать домашнее задание?", reply_markup=kb)

@router.callback_query(F.data == "hw_tomorrow")
async def send_tomorrow_hw(callback: CallbackQuery):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    items = await get_homework_by_date(tomorrow)
    await callback.answer()

    if not items:
        await callback.message.answer("На завтра домашнего задания нет 🎉")
        return

    lines = []
    photos = []

    for subject, task, file_id in items:
        photo_mark = " 📎 <i>(см. фото ниже)</i>" if file_id else ""
        lines.append(f"📚 <b>{subject}:</b> {task}{photo_mark}")
        if file_id:
            photos.append(InputMediaPhoto(media=file_id, caption=f"Фото к предмету: {subject}"))

    # Оборачиваем весь список в тег <blockquote>, чтобы появилась полоса слева
    quote_body = "\n".join(lines)
    text = f"📝 <b>Домашнее задание на завтра:</b>\n<blockquote>{quote_body}</blockquote>"

    await callback.message.answer(text, parse_mode="HTML")

    # Если были прикреплены фото, отправляем их пачкой (медиагруппой)
    if photos:
        await callback.message.answer_media_group(media=photos)

@router.callback_query(F.data == "hw_next_week")
async def send_next_week_hw(callback: CallbackQuery):
    items = await get_homework_next_week()
    await callback.answer()

    if not items:
        await callback.message.answer("На следующую неделю заданий пока не добавлено.")
        return

    grouped_hw = {}
    photos = []

    for due_date_str, subject, task, file_id in items:
        if due_date_str not in grouped_hw:
            grouped_hw[due_date_str] = []
        grouped_hw[due_date_str].append((subject, task, file_id))

        if file_id:
            date_obj = datetime.strptime(due_date_str, "%Y-%m-%d")
            day_name = WEEKDAYS_RU[date_obj.weekday()]
            photos.append(
                InputMediaPhoto(
                    media=file_id, 
                    caption=f"{day_name} ({date_obj.strftime('%d.%m')}) — {subject}"
                )
            )

    # Объявляем переменную blocks, на которую ругался редактор
    blocks = ["🗓 <b>Домашнее задание на следующую неделю:</b>\n"]

    for due_date_str, tasks_list in grouped_hw.items():
        date_obj = datetime.strptime(due_date_str, "%Y-%m-%d")
        day_name = WEEKDAYS_RU[date_obj.weekday()]
        pretty_date = date_obj.strftime("%d.%m")

        day_lines = [f"📅 <b>{day_name} ({pretty_date})</b>"]
        for subject, task, file_id in tasks_list:
            photo_mark = " 📎 <i>(см. фото)</i>" if file_id else ""
            day_lines.append(f"• <b>{subject}:</b> {task}{photo_mark}")

        blocks.append(f"<blockquote>{chr(10).join(day_lines)}</blockquote>")

    await callback.message.answer("\n".join(blocks), parse_mode="HTML")

    # Отправляем прикрепленные фотографии (если есть)
    if len(photos) == 1:
        await callback.message.answer_photo(
            photo=photos[0].media, 
            caption=photos[0].caption
        )
    elif len(photos) > 1:
        await callback.message.answer_media_group(media=photos)

    

@router.message(F.text == "Отмена")
async def cancel_add_hw(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Добавление отменено.",
        reply_markup=get_main_reply_keyboard(message.from_user.id)
    )

@router.message(F.text == "Добавить дз")
async def start_add_hw(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN1_ID or message.from_user.id != ADMIN2_ID:
        return

    await state.set_state(AddHomework.subject)
    await message.answer("Введите название предмета:", reply_markup=cancel_kb)

@router.message(AddHomework.subject)
async def process_subject(message: Message, state: FSMContext):
    subj = message.text.strip()
    await state.update_data(subject=message.text)
    await state.set_state(AddHomework.task)
    if subj.lower().startswith("английск"):
        await message.answer("Введите задание для 1-й группы:")
    else:
        await message.answer("Теперь напишите само задание:")

@router.message(AddHomework.task)
async def process_task(message: Message, state: FSMContext):
    data = await state.get_data()
    subj = data["subject"]
    
    if subj.lower().startswith("английск"):
        # Сохраняем задание 1-й группы и переходим к вопросу про 2-ю группу
        await state.update_data(task_g1=message.text)
        await state.set_state(AddHomework.task_group2)
        await message.answer("Теперь введите задание для 2-й группы (или напишите «-», если не задано):")
    else:
        await state.update_data(task=message.text)
        await state.set_state(AddHomework.due_date)
        await message.answer("На какую дату задано? Введите в формате ДД.ММ.ГГГГ:")

@router.message(AddHomework.task_group2)
async def process_task_group2(message: Message, state: FSMContext):
    data = await state.get_data()
    g1 = data["task_g1"]
    g2 = message.text
    
    combined_task = f"\n   ▫️ <i>1 группа:</i> {g1}\n   ▫️ <i>2 группа:</i> {g2}"
    await state.update_data(task=combined_task)
    await state.set_state(AddHomework.due_date)
    await message.answer("На какую дату задано? Введите в формате ДД.ММ.ГГГГ:")

@router.message(AddHomework.due_date)
async def process_date(message: Message, state: FSMContext):
    try:
        # Превращаем '16.11.2026' в '2026-11-16' для правильного поиска в SQLite
        parsed_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
        await state.update_data(due_date=parsed_date.isoformat())
    except ValueError:
        await message.answer("Неверный формат даты. Напишите строго как в примере: 16.11.2026")
        return

    skip_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Без фото")], [KeyboardButton(text="Отмена")]],
        resize_keyboard=True
    )
    await state.set_state(AddHomework.photo)
    await message.answer("Прикрепите фото (если есть) или нажмите «Без фото»:", reply_markup=skip_kb)

@router.message(AddHomework.photo)
async def process_photo(message: Message, state: FSMContext):
    file_id = None
    if message.photo:
        # Берем самое высокое разрешение прикрепленной картинки
        file_id = message.photo[-1].file_id
    elif message.text != "Без фото":
        await message.answer("Пожалуйста, отправьте фотографию или нажмите кнопку «Без фото».")
        return

    data = await state.get_data()
    await add_homework_to_db(
        subject=data["subject"],
        task=data["task"],
        due_date=data["due_date"],
        file_id=file_id
    )
    await state.clear()
    await message.answer(
        f"✅ Домашнее задание по предмету <b>{data['subject']}</b> сохранено!",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(message.from_user.id)
    )

@router.message(F.text == "Удалить дз")
async def show_delete_hw_menu(message: Message):
    if message.from_user.id != ADMIN1_ID or message.from_user.id != ADMIN2_ID:
        return

    items = await get_all_active_homework()
    if not items:
        await message.answer("Актуальных домашних заданий в базе нет.")
        return
    
    buttons = []
    for hw_id, due_date_str, subject, task in items:
        pretty_date = datetime.strptime(due_date_str, "%Y-%m-%d").strftime("%d.%m")
        # Обрезаем длинный текст задания, чтобы кнопка выглядела аккуратно
        short_task = (task[:20] + "...") if len(task) > 20 else task
        btn_text = f"❌ {pretty_date} | {subject}: {short_task}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"del_hw_{hw_id}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Нажмите на задание, которое нужно удалить:", reply_markup=kb)

@router.callback_query(F.data.startswith("del_hw_"))
async def process_delete_hw(callback: CallbackQuery):
    if callback.from_user.id != ADMIN1_ID or callback.from_user.id != ADMIN2_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return

    # Достаем числовой ID записи из callback_data ("del_hw_5" -> 5)
    hw_id = int(callback.data.split("_")[-1])
    await delete_homework_by_id(hw_id)

    await callback.answer("Задание удалено!", show_alert=True)
    await callback.message.edit_text("✅ Запись успешно удалена из базы данных.")