from aiogram import F
from aiogram.types import InputMediaPhoto, CallbackQuery, Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
import aiosqlite
from datetime import date, timedelta, datetime
from forms.hw import AddHomework, EditHomework, AddTaskPhoto
from aiogram.fsm.context import FSMContext
from handlers.routes import ai_client, router, ADMIN1_ID, ADMIN2_ID, DB_NAME, WEEKDAYS_RU, get_main_reply_keyboard
import os
import base64


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Строим надежный путь: поднимаемся наверх из handlers и заходим в pdfs
pdf_path = os.path.join(BASE_DIR, "..", "pdfs", "algebra_10-11_kl_ja_alimov_.pdf")

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Отмена")]],
    resize_keyboard=True
)

async def get_all_task_images():
    """Получает список всех сохраненных фото заданий."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, subject, task_number FROM task_images ORDER BY id DESC")
        return await cursor.fetchall()

async def delete_task_image_by_id(image_id: int):
    """Удаляет конкретное фото задания по его ID."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM task_images WHERE id = ?", (image_id,))
        await db.commit()

async def clear_all_task_images():
    """Полностью очищает таблицу task_images."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM task_images")
        await db.commit()

async def get_task_image(subject: str, task_text: str):
    """Ищет сохраненное админом фото задания по совпадению номера в тексте задачи."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT subject, task_number, file_id FROM task_images WHERE ? LIKE '%' || task_number || '%'",
            (task_text,)
        )
        rows = await cursor.fetchall()
        
        for db_subject, task_number, file_id in rows:
            if db_subject.lower() in subject.lower():
                return file_id
                
    return None

async def get_textbook_for_subject(subject: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT subject, textbook FROM textbooks")
        rows = await cursor.fetchall()
        
        for db_subject, textbook in rows:
            if db_subject.lower() in subject.lower():
                return textbook
                
    return "Стандартный школьный учебник 10 класса"

def sanitize_html(text: str) -> str:
    return text.replace("<", "&lt;").replace(">", "&gt;").replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>").replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>").replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")

# Функция генерации ответа через DeepSeek API
async def solve_homework_with_ai(subject: str, task: str = "", textbook: str = None, photo_file_id: str = None, bot_instance=None):
    task_text = task if task else "Задание не указано"
    
    if not textbook:
        textbook = "Алгебра и начала математического анализа. 10-11 классы (Алимов Ш.А.)"
        
    prompt = (
        f"Ты — строгий эксперт по школьной программе РФ и преподаватель математики.\n"
        f"Ученик прислал конкретное задание из учебника: «{task_text}» (Предмет: {subject}, Учебник: {textbook}).\n\n"
        f"🚨 ЖЕСТКИЕ ПРАВИЛА ДЛЯ РЕШЕНИЯ:\n"
        f"1. Если приложено изображение с условием, опирайся в первую очередь на него!\n"
        f"2. НАЙДИ И ПОКАЖИ ТОЧНЫЕ ЧИСЛА И УСЛОВИЕ. Категорически запрещено выдумывать числа или знаки из головы!\n"
        f"3. В самом начале ответа выпиши точное условие задачи.\n"
        f"4. Распиши подробное пошаговое решение.\n"
        f"5. Математические формулы пиши через Unicode (², ³, √, и т.д.) или оборачивай в теги <code>...</code>.\n"
        f"6. Разрешенные HTML-теги для форматирования: строго только <b>, <i>, <code>. Никакого LaTeX.\n"
        f"7. В самом конце напиши жирным шрифтом: <b>Ответ: ...</b>"
    )

    content_payload = []
    
    # Если есть фото и передан экземпляр бота, скачиваем картинку и конвертируем в base64
    if photo_file_id and bot_instance:
        try:
            file_info = await bot_instance.get_file(photo_file_id)
            file_bytes = await bot_instance.download_file(file_info.file_path)
            encoded_image = base64.b64encode(file_bytes.read()).decode('utf-8')
            
            content_payload.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{encoded_image}"
                }
            })
        except Exception as e:
            print(f"⚠️ Не удалось скачать фото для ИИ: {e}")

    content_payload.append({
        "type": "text",
        "text": prompt
    })

    try:
        print(f"🔄 Отправка запроса в ИИ ({subject} | Задание: {task_text} | Фото: {'Да' if photo_file_id else 'Нет'})...")
        
        response = await ai_client.chat.completions.create(
            model="deepseek-flash", # или модель, поддерживающая vision (если дефолтная ругается на картинки)
            messages=[
                {
                    "role": "system", 
                    "content": "Ты академический помощник. Ты решаешь задачи строго по предоставленным условиям и изображениям."
                },
                {"role": "user", "content": content_payload if len(content_payload) > 1 else prompt}
            ],
            stream=False
        )
        
        print("✅ Ответ от ИИ успешно получен!")
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ ОШИБКА в solve_homework_with_ai: {e}")
        return f"⚠️ Не удалось сгенерировать решение. Ошибка: {e}"

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

@router.message(F.text == "Управление фото заданий")
async def show_manage_photos_menu(message: Message):
    if message.from_user.id != ADMIN1_ID and message.from_user.id != ADMIN2_ID:
        return

    items = await get_all_task_images()
    if not items:
        await message.answer("📁 В базе данных нет сохраненных фотографий заданий.")
        return

    buttons = []
    for img_id, subject, task_number in items:
        btn_text = f"🗑 {subject} | №{task_number}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"del_img_{img_id}")])

    # Кнопка полной очистки таблицы
    buttons.append([InlineKeyboardButton(text="⚠️ Очистить все фото", callback_data="clear_all_imgs")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(
        "📂 <b>Управление фотографиями заданий:</b>\nНажмите на конкретное фото, чтобы удалить его, или выберите очистку всех данных.",
        parse_mode="HTML",
        reply_markup=kb
    )

@router.callback_query(F.data.startswith("del_img_"))
async def process_delete_single_image(callback: CallbackQuery):
    if callback.from_user.id != ADMIN1_ID and callback.from_user.id != ADMIN2_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return

    img_id = int(callback.data.split("_")[-1])
    await delete_task_image_by_id(img_id)

    await callback.answer("Фото задания успешно удалено!", show_alert=True)
    await callback.message.edit_text("✅ Выбранное фото удалено из базы данных.")

@router.callback_query(F.data == "clear_all_imgs")
async def process_clear_all_images(callback: CallbackQuery):
    if callback.from_user.id != ADMIN1_ID and callback.from_user.id != ADMIN2_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return

    await clear_all_task_images()
    await callback.answer("Все фотографии заданий удалены!", show_alert=True)
    await callback.message.edit_text("🗑 Таблица `task_images` полностью очищена.")

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

    grouped_hw = {}
    photos = []

    for hw_id, due_date_str, subject, task, file_id, textbook in items:
        if due_date_str not in grouped_hw:
            grouped_hw[due_date_str] = []
        grouped_hw[due_date_str].append((hw_id, subject, task, file_id, textbook))

        if file_id:
            date_obj = datetime.strptime(due_date_str, "%Y-%m-%d")
            day_name = WEEKDAYS_RU[date_obj.weekday()]
            photos.append(
                InputMediaPhoto(
                    media=file_id, 
                    caption=f"{day_name} ({date_obj.strftime('%d.%m')}) — {subject}"
                )
            )

    await callback.message.answer("🗓 <b>Домашнее задание на следующую неделю:</b>", parse_mode="HTML")

    for due_date_str, tasks_list in grouped_hw.items():
        date_obj = datetime.strptime(due_date_str, "%Y-%m-%d")
        day_name = WEEKDAYS_RU[date_obj.weekday()]
        pretty_date = date_obj.strftime("%d.%m")

        for hw_id, subject, task, file_id, textbook in tasks_list:
            tb_mark = f" | 📖 <i>{textbook}</i>" if textbook else ""
            photo_mark = " 📎 <i>(см. фото)</i>" if file_id else ""
            
            text = (
                f"📅 <b>{day_name} ({pretty_date})</b>\n"
                f"📚 <b>{subject}</b>{tb_mark}:\n"
                f"<blockquote>{task}{photo_mark}</blockquote>"
            )
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🧠 Решить ({subject})", callback_data=f"ai_solve_{hw_id}")]
            ])
            
            await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)

    if len(photos) == 1:
        await callback.message.answer_photo(photo=photos[0].media, caption=photos[0].caption)
    elif len(photos) > 1:
        await callback.message.answer_media_group(media=photos)

# Обработчик нажатия на кнопку ИИ-решения
@router.callback_query(F.data.startswith("ai_solve_"))
async def process_ai_solve(callback: CallbackQuery):
    try:
        hw_id = int(callback.data.split("_")[-1])
        await callback.answer("🤖 Секунду, генерирую решение...")
    
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT subject, task, textbook FROM homework WHERE id = ?",
                (hw_id,)
            )
            row = await cursor.fetchone()
            
        if not row:
            await callback.message.answer("Задание не найдено в базе данных.")
            return
            
        subject, task, textbook = row
        
        # 🔍 Ищем прикрепленное админом фото для этого задания
        admin_photo_id = await get_task_image(subject, task)

        wait_msg = await callback.message.answer("⏳ Нейронка думает над решением...")
        
        # Передаем bot_instance=callback.bot, чтобы функция могла скачать картинку
        solution = await solve_homework_with_ai(
            subject=subject, 
            task=task, 
            textbook=textbook, 
            photo_file_id=admin_photo_id, 
            bot_instance=callback.bot
        )
        
        await wait_msg.delete()
        
        if len(solution) > 4000:
            solution = solution[:4000] + "\n\n...(текст сокращен из-за лимита Telegram)"
            
        safe_solution = sanitize_html(solution)
            
        await callback.message.answer(
            f"🤖 <b>Решение от ИИ ({subject}):</b>\n\n{safe_solution}",
            parse_mode="HTML"
        )

    except Exception as e:
        print(f"❌ ОШИБКА в ai_solve: {e}")
        try:
            await callback.message.answer(f"⚠️ Произошла ошибка: {e}")
        except:
            pass

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

@router.message(F.text == "Загрузить фото задания")
async def start_upload_task_photo(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN1_ID and message.from_user.id != ADMIN2_ID:
        return
    
    await state.set_state(AddTaskPhoto.waiting_for_photo)
    await message.answer("📸 Отправьте фотографию задания из учебника:", reply_markup=cancel_kb)

# 2. Получаем фото от админа
@router.message(AddTaskPhoto.waiting_for_photo, F.photo)
async def process_task_photo(message: Message, state: FSMContext):
    # Берем фото в самом высоком разрешении
    file_id = message.photo[-1].file_id
    await state.update_data(file_id=file_id)
    
    await state.set_state(AddTaskPhoto.waiting_for_subject)
    await message.answer("📚 К какому предмету относится это задание? (например: <i>Алгебра</i>, <i>Геометрия</i>, <i>Физика</i>):", parse_mode="HTML")

# 3. Получаем предмет
@router.message(AddTaskPhoto.waiting_for_subject)
async def process_task_subject(message: Message, state: FSMContext):
    subject = message.text.strip()
    await state.update_data(subject=subject)
    
    await state.set_state(AddTaskPhoto.waiting_for_task_number)
    await message.answer("🔢 Введите точный номер задания (например: <i>165</i> или <i>165(2)</i>):", parse_mode="HTML")

# 4. Получаем номер задания и сохраняем в базу task_images
@router.message(AddTaskPhoto.waiting_for_task_number)
async def process_task_number(message: Message, state: FSMContext):
    task_number = message.text.strip()
    data = await state.get_data()
    
    file_id = data["file_id"]
    subject = data["subject"]
    
    # Записываем в таблицу task_images базы данных Schedule.sql
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO task_images (subject, task_number, file_id) VALUES (?, ?, ?)",
            (subject, task_number, file_id)
        )
        await db.commit()
        
    await state.clear()
    await message.answer(
        f"✅ Фото успешно сохранено!\n📚 Предмет: <b>{subject}</b>\n🔢 Номер: <b>{task_number}</b>",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard(message.from_user.id)
    )