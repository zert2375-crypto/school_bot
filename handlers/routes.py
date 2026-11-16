from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
import aiosqlite
import dotenv
from os import getenv

dotenv.load_dotenv(override=True)
ADMIN1_ID = int(getenv("ADMIN1_ID"))
ADMIN2_ID = int(getenv("ADMIN2_ID"))
router = Router()

DB_NAME = "data/Schedule.sql"
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
                    file_id TEXT,
                    textbook TEXT
                )
            """)

        await db.commit()

def get_main_reply_keyboard(user_id: int):
    if (user_id != ADMIN1_ID) and (user_id != ADMIN2_ID):
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
                    [KeyboardButton(text="Изменить дз")],
                    [KeyboardButton(text="Удалить дз")],
                    [KeyboardButton(text="Загрузить фото задания")],
                    [KeyboardButton(text="Управление фото заданий")],
                    [KeyboardButton(text="Управление кэшем ИИ")]
                ],
                resize_keyboard=True
            )
    return keyboard

@router.message(Command("start"))
async def start(message: Message):
    await message.answer("Привет, я бот, созданный крутым типом для крутых типов из 10 \"В\" класса!",reply_markup=get_main_reply_keyboard(message.from_user.id))
