from os import getenv
from openai import AsyncOpenAI
import aiosqlite
from handlers.routes import DB_NAME, ADMIN1_ID, ADMIN2_ID, router, get_main_reply_keyboard
import base64
from aiogram.types import CallbackQuery,Message,InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram import F
from forms.hw import AIChatState
from aiogram.fsm.context import FSMContext

ai_client = AsyncOpenAI(
    api_key=getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

EXACT_SUBJECTS = ["алгебра", "геометрия", "физика", "химия", "вероятность и статистика"]

async def get_cached_solution(subject: str, task: str):
    """Проверяет, есть ли сохраненный ответ для точных наук в базе"""
    sub_lower = subject.lower()
    if not any(ex in sub_lower for ex in EXACT_SUBJECTS):
        return None  # Творческие предметы не кэшируем жестко

    async with aiosqlite.connect(DB_NAME) as db:
        # Убедимся, что таблица кэша существует
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ai_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                task TEXT UNIQUE,
                solution TEXT
            )
        """)
        cursor = await db.execute("SELECT solution FROM ai_cache WHERE subject = ? AND task = ?", (subject, task))
        row = await cursor.fetchone()
        return row[0] if row else None

async def save_cached_solution(subject: str, task: str, solution: str):
    """Сохраняет ответ в кэш, если предмет точный"""
    sub_lower = subject.lower()
    if not any(ex in sub_lower for ex in EXACT_SUBJECTS):
        return

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR IGNORE INTO ai_cache (subject, task, solution) VALUES (?, ?, ?)
        """, (subject, task, solution))
        await db.commit()

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

import re

async def get_cache_stats():
    """Возвращает количество записей в кэше ИИ"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ai_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                task TEXT UNIQUE,
                solution TEXT
            )
        """)
        cursor = await db.execute("SELECT COUNT(*) FROM ai_cache")
        row = await cursor.fetchone()
        return row[0] if row else 0


def sanitize_html(text: str) -> str:
    # 1. Автоматически превращаем **текст** в <b>текст</b>, если нейросеть ошибочно прислала маркдаун
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    
    # 2. Базовая очистка и сохранение разрешенных тегов
    return (
        text.replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("&lt;b&gt;", "<b>")
            .replace("&lt;/b&gt;", "</b>")
            .replace("&lt;i&gt;", "<i>")
            .replace("&lt;/i&gt;", "</i>")
            .replace("&lt;code&gt;", "<code>")
            .replace("&lt;/code&gt;", "</code>")
    )
# Функция генерации ответа через DeepSeek API
async def solve_homework_with_ai(subject: str, task: str = "", textbook: str = None, photo_file_id: str = None, bot_instance=None):
    task_text = task if task else "Задание не указано"
    
    if not textbook:
        textbook = "Школьный учебник"
        
    # Динамический промпт в зависимости от наличия картинки
    if photo_file_id and bot_instance:
        prompt = (
            f"Ты — академический помощник и эксперт по школьной программе РФ (предмет: {subject}).\n"
            f"Ученик прислал фотографию задания из учебника ({textbook}). Текст из базы: «{task_text}».\n\n"
            f"🚨 ЖЕСТКИЕ ПРАВИЛА ОФОРМЛЕНИЯ:\n"
            f"1. Внимательно изучи приложенное изображение с условием.\n"
            f"2. ❌ КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать LaTeX (никаких `\\(`, `\\)`, `\\begin`, `\\frac`, `\\sqrt`). Пиши все формулы обычным текстом и Unicode-символами (`√`, `²`, `³`, `⁴`, `≤`, `≥`, дроби через слэш вида `(a)/(b)` или в блоках `<code>`).\n"
            f"3. Не пиши слово 'ОДЗ'. Все ограничения оформляй через равносильные системы, записывая их строчками через фигурные скобки текстом (например: Система: {'{'} условие 1; условие 2 {'}'}).\n"
            f"4. Разрешенные HTML-теги для форматирования: строго только <b>, <i>, <code>. Никаких других тегов.\n"
            f"5. В самом конце напиши жирным шрифтом: <b>Ответ: ...</b>"
        )
    else:
        prompt = (
            f"Ты — академический помощник и эксперт по школьной программе РФ (предмет: {subject}).\n"
            f"Ученик дал задание/тему: «{task_text}» (Учебник/источник: {textbook}).\n\n"
            f"🚨 ЖЕСТКИЕ ПРАВИЛА ОФОРМЛЕНИЯ:\n"
            f"1. Выполни задание качественно и полно.\n"
            f"2. ❌ КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать LaTeX (никаких `\\(`, `\\)`, `\\begin`, `\\frac`, `\\sqrt`). Используй только текст и Unicode (`√`, `≤`, `≥`, `/`).\n"
            f"3. Разрешенные HTML-теги для форматирования: строго только <b>, <i>, <code>.\n"
            f"4. В самом конце напиши жирным шрифтом: <b>Ответ: ...</b>"
        )

    content_payload = []
    
    # Если есть фото, добавляем его в запрос к ИИ
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
            model="deepseek-chat", # Стандартная текстовая модель (или deepseek-vision, если поддерживается)
            messages=[
                {
                    "role": "system", 
                    "content": "Ты полезный школьный помощник. Всегда выполняй запрос ученика по существу."
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
@router.message(F.text == "Управление кэшем ИИ")
async def show_cache_management_menu(message: Message):
    if message.from_user.id != ADMIN1_ID and message.from_user.id != ADMIN2_ID:
        return

    count = await get_cache_stats()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить весь кэш ИИ", callback_data="clear_ai_cache_all")]
    ])
    
    await message.answer(
        f"🧠 <b>Управление кэшем нейросети:</b>\n\n"
        f"📊 Сохранено ответов в кэше: <b>{count}</b>\n\n"
        f"Если ИИ сохранил неверное решение для точных предметов, вы можете полностью очистить кэш, чтобы при следующем запросе он сгенерировал ответ заново.",
        parse_mode="HTML",
        reply_markup=kb
    )

@router.callback_query(F.data == "clear_ai_cache_all")
async def process_clear_ai_cache(callback: CallbackQuery):
    if callback.from_user.id != ADMIN1_ID and callback.from_user.id != ADMIN2_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM ai_cache")
        await db.commit()

    await callback.answer("Кэш нейросети успешно очищен!", show_alert=True)
    await callback.message.edit_text("✅ <b>Таблица кэша `ai_cache` полностью очищена.</b>\nТеперь все точные задачи будут запрашиваться у ИИ заново.", parse_mode="HTML")

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

@router.callback_query(F.data.startswith("ai_solve_"))
async def process_ai_solve(callback: CallbackQuery, state: FSMContext):
    try:
        hw_id = int(callback.data.split("_")[-1])
        await callback.answer("🤖 Анализирую задание...")
    
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
        
        # 1. Проверяем кэш (для точных наук)
        cached = await get_cached_solution(subject, task)
        if cached:
            solution = cached
            source_info = "⚡ <i>(Взято из кэша / экономия лимитов)</i>"
        else:
            wait_msg = await callback.message.answer("⏳ Нейронка думает над решением...")
            
            # Проверяем фото из базы, если загружено админом
            # Проверяем фото из базы, если загружено админом
            task_file_id = await get_task_image(subject, task)
            
            if task_file_id:
                # Передаем параметры четко по именам, чтобы исключить путаницу
                solution = await solve_homework_with_ai(
                    subject=subject, 
                    task=task, 
                    textbook=textbook, 
                    photo_file_id=task_file_id, 
                    bot_instance=callback.bot
                )
            else:
                solution = await solve_homework_with_ai(subject=subject, task=task, textbook=textbook)
            
            await wait_msg.delete()
            
            # Сохраняем в кэш, если это точный предмет
            await save_cached_solution(subject, task, solution)
            source_info = "🤖 <i>(Сгенерировано ИИ)</i>"

        if len(solution) > 4000:
            solution = solution[:4000] + "\n\n...(текст сокращен)"
            
        safe_solution = sanitize_html(solution)

        # 2. Сохраняем контекст сессии в FSM, чтобы пользователь мог писать уточнения
        history = [
            {"role": "system", "content": f"Ты репетитор по предмету {subject}. Помогай ученику."},
            {"role": "user", "content": f"Задание: {task}. Учебник: {textbook}"},
            {"role": "assistant", "content": solution}
        ]
        await state.update_data(chat_history=history, subject=subject, task=task)
        await state.set_state(AIChatState.chatting)

        # Клавиатура выхода из режима чата с ИИ
        exit_kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Завершить диалог с ИИ")]],
            resize_keyboard=True
        )

        await callback.message.answer(
            f"<b>Решение ({subject}):</b> {source_info}\n\n{safe_solution}\n\n"
            f"💬 <i>Ты можешь написать ответным сообщением свой вопрос или правку к этому решению (например: 'Объясни подробнее 3 шаг'), и нейросеть ответит!</i>",
            parse_mode="HTML",
            reply_markup=exit_kb
        )

    except Exception as e:
        print(f"❌ ОШИБКА в ai_solve: {e}")
        try:
            await callback.message.answer(f"⚠️ Произошла ошибка: {e}")
        except:
            pass

# Обработка сообщений в режиме диалога (FSM)
@router.message(AIChatState.chatting, F.text != "Завершить диалог с ИИ")
async def process_ai_chat_message(message: Message, state: FSMContext):
    user_text = message.text.strip()
    data = await state.get_data()
    history = data.get("chat_history", [])
    subject = data.get("subject", "Предмет")

    # Добавляем сообщение пользователя в историю диалога
    history.append({"role": "user", "content": user_text})

    wait_msg = await message.answer("💬 Нейросеть думает над уточнением...")

    try:
        # Отправляем весь диалог в DeepSeek/OpenAI, чтобы модель помнила контекст задачи
        response = await ai_client.chat.completions.create(
            model="deepseek-chat", # или твоя основная модель
            messages=history,
            stream=False
        )
        answer = response.choices[0].message.content
        
        # Добавляем ответ модели в историю
        history.append({"role": "assistant", "content": answer})
        await state.update_data(chat_history=history)

        await wait_msg.delete()
        
        if len(answer) > 4000:
            answer = answer[:4000] + "\n\n...(сокращено)"

        safe_answer = sanitize_html(answer)
        await message.answer(f"🤖 <b>Ответ на уточнение ({subject}):</b>\n\n{safe_answer}", parse_mode="HTML")

    except Exception as e:
        await wait_msg.delete()
        await message.answer(f"⚠️ Ошибка при обращении к ИИ: {e}")

# Выход из режима диалога
@router.message(AIChatState.chatting, F.text == "Завершить диалог с ИИ")
async def exit_ai_chat(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "✅ Диалог с нейросетью завершен. Вы вернулись в обычное меню.",
        reply_markup=get_main_reply_keyboard(message.from_user.id)
    )
