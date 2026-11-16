from aiogram import F
from aiogram.types import InputMediaPhoto, CallbackQuery, Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
import aiosqlite
from datetime import date, timedelta, datetime
from forms.hw import AddHomework, EditHomework, AddTaskPhoto, AIChatState
from aiogram.fsm.context import FSMContext
from handlers.routes import router, ADMIN1_ID, ADMIN2_ID, DB_NAME, WEEKDAYS_RU, get_main_reply_keyboard
from handlers.deepseek import ai_client, sanitize_html
import os
import base64

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Отмена")]],
    resize_keyboard=True
)



async def add_homework_to_db(subject: str, task: str, due_date: str, file_id: str = None, textbook: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id FROM homework WHERE due_date = ? AND subject = ?",
            (due_date, subject)
        )
        existing = await cursor.fetchone()
        
        if existing:
            await db.execute(
                "UPDATE homework SET task = ?, file_id = ?, textbook = ? WHERE due_date = ? AND subject = ?",
                (task, file_id, textbook, due_date, subject)
            )
        else:
            await db.execute(
                "INSERT INTO homework (subject, task, due_date, file_id, textbook) VALUES (?, ?, ?, ?, ?)",
                (subject, task, due_date, file_id, textbook)
            )
        await db.commit()

async def get_homework_by_date(target_date: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, subject, task, file_id, textbook FROM homework WHERE due_date = ?",
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
            SELECT id, due_date, subject, task, file_id, textbook 
            FROM homework 
            WHERE due_date BETWEEN ? AND ? 
            ORDER BY due_date
            """,
            (next_monday.isoformat(), next_sunday.isoformat())
        )
        return await cursor.fetchall()

async def get_homework_current_week():
    today = date.today()
    # Считаем понедельник текущей недели (0 - понедельник, 6 - воскресенье)
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            SELECT id, due_date, subject, task, file_id, textbook 
            FROM homework 
            WHERE due_date BETWEEN ? AND ? 
            ORDER BY due_date
            """,
            (start_of_week.isoformat(), end_of_week.isoformat())
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

async def send_grouped_hw_by_days(message: Message, items, title: str):
    grouped_hw = {}
    
    # Группируем задания по датам
    for hw_id, due_date_str, subject, task, file_id, textbook in items:
        if due_date_str not in grouped_hw:
            grouped_hw[due_date_str] = []
        grouped_hw[due_date_str].append((hw_id, subject, task, file_id, textbook))

    await message.answer(title, parse_mode="HTML")

    # Для каждого дня формируем одно сводное сообщение
    for due_date_str, tasks_list in grouped_hw.items():
        date_obj = datetime.strptime(due_date_str, "%Y-%m-%d")
        day_name = WEEKDAYS_RU[date_obj.weekday()]
        pretty_date = date_obj.strftime("%d.%m")

        day_text = f"📅 <b>{day_name} ({pretty_date})</b>\n\n"
        inline_buttons = []

        for hw_id, subject, task, file_id, textbook in tasks_list:
            tb_mark = f" | 📖 <i>{textbook}</i>" if textbook else ""
            photo_mark = " 📎 <i>(есть фото)</i>" if file_id else ""
            
            # Очищаем текст и заворачиваем само задание в блок code
            safe_task = sanitize_html(task)
            
            day_text += f"📚 <b>{subject}</b>{tb_mark}{photo_mark}\n<code>{safe_task}</code>\n\n"
            
            # Добавляем кнопку «Решить» для этого предмета в общий список кнопок дня
            inline_buttons.append([
                InlineKeyboardButton(text=f"🧠 Решить ({subject})", callback_data=f"ai_solve_{hw_id}")
            ])

        kb = InlineKeyboardMarkup(inline_keyboard=inline_buttons)
        
        # Отправляем одно сообщение на весь день со всеми кнопками в конце
        await message.answer(day_text.strip(), parse_mode="HTML", reply_markup=kb)

@router.message(F.text == "Домашка")
async def show_hw_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="На завтра", callback_data="hw_tomorrow")],
        [InlineKeyboardButton(text="На следующую неделю", callback_data="hw_next_week")],
        [InlineKeyboardButton(text="На текущую неделю", callback_data="hw_current_week")]
    ])
    await message.answer("За какой период показать домашнее задание?", reply_markup=kb)

@router.callback_query(F.data == "hw_current_week")
async def send_current_week_hw(callback: CallbackQuery):
    items = await get_homework_current_week()
    await callback.answer()

    if not items:
        await callback.message.answer("На текущую неделю заданий не найдено.")
        return

    await send_grouped_hw_by_days(callback.message, items, "🗓 <b>Домашнее задание на текущую неделю:</b>")

@router.callback_query(F.data == "hw_tomorrow")
async def send_tomorrow_hw(callback: CallbackQuery):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    items = await get_homework_by_date(tomorrow)
    await callback.answer()

    if not items:
        await callback.message.answer("На завтра домашнего задания нет 🎉")
        return

    for hw_id, subject, task, file_id, textbook in items:
        tb_mark = f"\n📖 <i>Учебник: {textbook}</i>" if textbook else ""
        photo_mark = "\n📎 <i>(есть прикрепленное фото)</i>" if file_id else ""
        
        text = f"📚 <b>{subject}:</b>{tb_mark}\n{task}{photo_mark}"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧠 Решить с помощью ИИ", callback_data=f"ai_solve_{hw_id}")]
        ])
        
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
        if file_id:
            await callback.message.answer_photo(photo=file_id)

@router.callback_query(F.data == "hw_next_week")
async def send_next_week_hw(callback: CallbackQuery):
    items = await get_homework_next_week()
    await callback.answer()

    if not items:
        await callback.message.answer("На следующую неделю заданий пока не добавлено.")
        return

    await send_grouped_hw_by_days(callback.message, items, "🗓 <b>Домашнее задание на следующую неделю:</b>")

# Обработчик нажатия на кнопку ИИ-решения

@router.message(F.text == "Отмена")
async def cancel_add_hw(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Добавление отменено.",
        reply_markup=get_main_reply_keyboard(message.from_user.id)
    )

@router.message(F.text == "Добавить дз")
async def start_add_hw(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN1_ID and message.from_user.id != ADMIN2_ID:
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
        await state.update_data(task_g1=message.text)
        await state.set_state(AddHomework.task_group2)
        await message.answer("Введите задание для 2-й группы (или «-»):")
    else:
        await state.update_data(task=message.text)
        await state.set_state(AddHomework.textbook)
        await message.answer("Введите автора и учебник (например: <i>Алгебра 10 кл, Алимов Ш.А.</i>) или «-»:", parse_mode="HTML")

@router.message(AddHomework.task_group2)
async def process_task_group2(message: Message, state: FSMContext):
    data = await state.get_data()
    g1 = data["task_g1"]
    g2 = message.text
    
    combined_task = f"\n   ▫️ <i>1 группа:</i> {g1}\n   ▫️ <i>2 группа:</i> {g2}"
    await state.update_data(task=combined_task)
    await state.set_state(AddHomework.textbook)
    await message.answer("Введите автора и учебник (или «-»):")

@router.message(AddHomework.textbook)
async def process_textbook(message: Message, state: FSMContext):
    textbook = message.text.strip()
    if textbook == "-":
        textbook = None
    await state.update_data(textbook=textbook)
    
    await state.set_state(AddHomework.due_date)
    await message.answer("На какую дату задано? Введите в формате ДД.ММ.ГГГГ:")

@router.message(AddHomework.due_date)
async def process_date(message: Message, state: FSMContext):
    try:
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
        file_id = message.photo[-1].file_id
    elif message.text != "Без фото":
        await message.answer("Пожалуйста, отправьте фотографию или нажмите кнопку «Без фото».")
        return

    data = await state.get_data()
    await add_homework_to_db(
        subject=data["subject"],
        task=data["task"],
        due_date=data["due_date"],
        file_id=file_id,
        textbook=data.get("textbook")
    )
    await state.clear()
    await message.answer(
        f"✅ Домашнее задание по предмету <b>{data['subject']}</b> сохранено!",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(message.from_user.id)
    )

@router.message(F.text == "Удалить дз")
async def show_delete_hw_menu(message: Message):
    if message.from_user.id != ADMIN1_ID and message.from_user.id != ADMIN2_ID:
        return

    items = await get_all_active_homework()
    if not items:
        await message.answer("Актуальных домашних заданий в базе нет.")
        return
    
    buttons = []
    for hw_id, due_date_str, subject, task in items:
        pretty_date = datetime.strptime(due_date_str, "%Y-%m-%d").strftime("%d.%m")
        short_task = (task[:20] + "...") if len(task) > 20 else task
        btn_text = f"❌ {pretty_date} | {subject}: {short_task}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"del_hw_{hw_id}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Нажмите на задание, которое нужно удалить:", reply_markup=kb)

@router.callback_query(F.data.startswith("del_hw_"))
async def process_delete_hw(callback: CallbackQuery):
    if callback.from_user.id != ADMIN1_ID and callback.from_user.id != ADMIN2_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return

    hw_id = int(callback.data.split("_")[-1])
    await delete_homework_by_id(hw_id)

    await callback.answer("Задание удалено!", show_alert=True)
    await callback.message.edit_text("✅ Запись успешно удалена из базы данных.")

@router.message(F.text == "Изменить дз")
async def show_edit_hw_menu(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN1_ID and message.from_user.id != ADMIN2_ID:
        return

    items = await get_all_active_homework()
    if not items:
        await message.answer("Актуальных домашних заданий для изменения нет.")
        return
    
    buttons = []
    for hw_id, due_date_str, subject, task in items:
        pretty_date = datetime.strptime(due_date_str, "%Y-%m-%d").strftime("%d.%m")
        short_task = (task[:20] + "...") if len(task) > 20 else task
        btn_text = f"✏️ {pretty_date} | {subject}: {short_task}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"edit_hw_{hw_id}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выберите домашнее задание, которое хотите изменить:", reply_markup=kb)

@router.callback_query(F.data.startswith("edit_hw_"))
async def process_selected_hw_to_edit(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN1_ID and callback.from_user.id != ADMIN2_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return

    hw_id = int(callback.data.split("_")[-1])
    await state.update_data(editing_hw_id=hw_id)
    await callback.answer()

    await state.set_state(EditHomework.new_task)
    await callback.message.answer(
        "Введите **новое** текст-задание для этого урока (или отправьте «-», чтобы оставить без изменений):",
        reply_markup=cancel_kb,
        parse_mode="Markdown"
    )

@router.message(EditHomework.new_task)
async def process_edit_task(message: Message, state: FSMContext):
    await state.update_data(new_task=message.text)
    await state.set_state(EditHomework.new_textbook)
    await message.answer(
        "Введите **нового автора и учебник** (например: <i>Алгебра 10 кл, Алимов Ш.А.</i>) или «-», если не нужно менять:",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )

@router.message(EditHomework.new_textbook)
async def process_edit_textbook(message: Message, state: FSMContext):
    textbook = message.text.strip()
    if textbook == "-":
        textbook = None
    await state.update_data(new_textbook=textbook)

    skip_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Без изменений (оставить старое)")], [KeyboardButton(text="Отмена")]],
        resize_keyboard=True
    )
    await state.set_state(EditHomework.new_photo)
    await message.answer("Прикрепите **новое фото** (если нужно заменить) или нажмите кнопку ниже:", reply_markup=skip_kb)

@router.message(EditHomework.new_photo)
async def process_edit_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    hw_id = data["editing_hw_id"]
    new_task = data["new_task"]
    new_textbook = data["new_textbook"]
    
    file_id = None
    update_photo_sql = ""
    params = []

    if message.photo:
        file_id = message.photo[-1].file_id
        update_photo_sql = ", file_id = ?"
        params = [new_task, new_textbook, file_id, hw_id]
    elif message.text == "Без изменений (оставить старое)":
        params = [new_task, new_textbook, hw_id]
    else:
        await message.answer("Пожалуйста, отправьте фотографию или нажмите кнопку «Без изменений».")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        if update_photo_sql:
            await db.execute(
                f"UPDATE homework SET task = ?, textbook = ? {update_photo_sql} WHERE id = ?",
                params
            )
        else:
            await db.execute(
                "UPDATE homework SET task = ?, textbook = ? WHERE id = ?",
                params
            )
        await db.commit()

    await state.clear()
    await message.answer(
        "✅ Домашнее задание успешно обновлено!",
        reply_markup=get_main_reply_keyboard(message.from_user.id)
    )

# 1. Админ нажимает кнопку запуска загрузки фото
@router.message(F.text == "Загрузить фото задания")
async def start_upload_task_photo(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN1_ID and message.from_user.id != ADMIN2_ID:
        return
    
    # Достаем все домашние задания из базы, чтобы показать списком
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, due_date, subject, task FROM homework ORDER BY due_date DESC LIMIT 15")
        items = await cursor.fetchall()
        
    if not items:
        await message.answer("⚠️ В базе данных пока нет ни одного домашнего задания, к которому можно привязать фото.")
        return

    buttons = []
    for hw_id, due_date, subject, task in items:
        # Обрезаем текст задания для красоты на кнопке, если он длинный
        short_task = (task[:25] + '..') if len(task) > 25 else task
        btn_text = f"📌 [{subject}] {short_task} ({due_date})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"select_hw_for_photo_{hw_id}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(AddTaskPhoto.waiting_for_homework_choice)
    await message.answer("👇 Выберите задание из списка, к которому хотите прикрепить эталонное фото:", reply_markup=kb)

# 2. Админ кликнул на конкретное задание из списка
@router.callback_query(AddTaskPhoto.waiting_for_homework_choice, F.data.startswith("select_hw_for_photo_"))
async def process_homework_choice_for_photo(callback: CallbackQuery, state: FSMContext):
    hw_id = int(callback.data.split("_")[-1])
    await state.update_data(hw_id=hw_id)
    await callback.answer()
    
    await state.set_state(AddTaskPhoto.waiting_for_photo)
    await callback.message.edit_text(
        "📸 Задание выбрано!\nТеперь отправьте фотографию этого задания (скриншот или фото страницы учебника):"
    )

# 3. Админ присылает фото — привязываем его напрямую по ID домашнего задания
@router.message(AddTaskPhoto.waiting_for_photo, F.photo)
async def process_task_photo_save(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    data = await state.get_data()
    hw_id = data["hw_id"]
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Узнаем предмет и номер/текст задания для красивого отчета
        cursor = await db.execute("SELECT subject, task FROM homework WHERE id = ?", (hw_id,))
        row = await cursor.fetchone()
        
        if not row:
            await state.clear()
            await message.answer("⚠️ Ошибка: выбранное задание больше не существует в базе.")
            return
            
        subject, task_text = row
        
        # Сохраняем в таблицу task_images, привязывая прямо к тексту/номеру задачи
        # (Или можно добавить поле hw_id в таблицу task_images, но проще сохранять task_number = task_text)
        await db.execute(
            "INSERT INTO task_images (subject, task_number, file_id) VALUES (?, ?, ?)",
            (subject, task_text, file_id)
        )
        await db.commit()
        
    await state.clear()
    await message.answer(
        f"✅ <b>Фото успешно привязано!</b>\n"
        f"📚 Предмет: <b>{subject}</b>\n"
        f"📝 Задача: <code>{task_text}</code>\n\n"
        f"Теперь при решении этого задания ИИ будет использовать эту фотографию как эталон.",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(message.from_user.id)
    )