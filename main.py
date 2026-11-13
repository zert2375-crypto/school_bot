from os import getenv
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
import asyncio
from handlers.routes import router,init_db

load_dotenv()
TOKEN = getenv("BOT_TOKEN")

# session = AiohttpSession(proxy="socks5://127.0.0.1:1443")
bot = Bot(token=TOKEN)
dp = Dispatcher()
load_dotenv()
TOKEN = getenv("BOT_TOKEN")

dp = Dispatcher()


dp.include_router(router)



async def main():
    bot = Bot(TOKEN)
    print("Started")
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
