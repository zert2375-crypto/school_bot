from aiogram import F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
import aiosqlite
from routes import router, ADMIN1_ID, ADMIN2_ID, Days, DB_NAME, WEEKDAYS_RU, get_main_reply_keyboard

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


