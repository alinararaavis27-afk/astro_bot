import asyncio
import logging
import os
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup
from aiogram.types import InlineKeyboardButton
from aiogram.types import LabeledPrice
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from openai import AsyncOpenAI
import aiosqlite

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not TOKEN or not OPENAI_KEY:
    raise RuntimeError("Нет TOKEN или OPENAI_KEY в .env")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
client = AsyncOpenAI(api_key=OPENAI_KEY)

PRICE_STARS = 99
PRICE_AMOUNT = PRICE_STARS

class Form(StatesGroup):
    waiting_birthdata = State()

async def init_db():
    async with aiosqlite.connect("users.db") as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users ("
        "user_id INTEGER PRIMARY KEY, birth_data TEXT, "
        "paid INTEGER DEFAULT 0)")
        await db.commit()

def parse_birthdata(text: str):
    pattern = (
        r"(\d{1,2})\.(\d{1,2})\.(\d{4})"
        r"(?:,\s*(\d{1,2}:\d{2}))?"
    )
    m = re.search(pattern, text)
    if not m:
        return None
    day = m.group(1)
    month = m.group(2)
    year = m.group(3)
    if m.group(4):
        time_part = m.group(4)
    else:
        time_part = "12:00"
    try:
        datetime.strptime(
            f"{day}.{month}.{year}",
            "%d.%m.%Y"
        )
    except ValueError:
        return None
    return (
        f"{day.zfill(2)}."
        f"{month.zfill(2)}."
        f"{year} {time_part}"
    )

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    btn = InlineKeyboardButton(text="🔮 Получить прогноз",
    callback_data="get_forecast")
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn]])
    txt = "Привет! Я астролог TONKO.\n\n"
    txt += "Я расскажу тебе инсайт о тебе, возможно то, "
    txt += "чего не знаешь и ты о себе.\n"
    txt += "Расскажу о сильных сторонах, о твоей слабой "
    txt += "точке и дам совет на ближайший месяц!\n\n"
    txt += "Отправь дату рождения ДД.ММ.ГГГГ."
    await message.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "get_forecast")
async def ask_birthdata(callback: types.CallbackQuery,
state: FSMContext):
    txt = "Напиши дату рождения в формате:\nДД.ММ.ГГГГ\n"
    txt += "например: 15.03.1990\n\n"
    txt += "Можешь добавить время и город, если хочешь:\n"
    txt += "15.03.1990 14:30, Москва"
    await callback.message.answer(txt)
    await state.set_state(Form.waiting_birthdata)
    await bot.answer_callback_query(callback.id)

@dp.message(Form.waiting_birthdata)
async def handle_birthdata(message: types.Message,
state: FSMContext):
    birth_data = parse_birthdata(message.text)
    if not birth_data:
        await message.answer("❌ Формат: 15.03.1990 "
        "или 15.03.1990 14:30")
        return

    async with aiosqlite.connect("users.db") as db:
        await db.execute("INSERT OR REPLACE INTO users "
        "(user_id, birth_data, paid) VALUES (?, ?, 0)",
        (message.from_user.id, birth_data))
        await db.commit()

    await state.clear()

    sys_prompt = (
    "Ты астролог с 20-летним опытом. Тон: дерзкий, "
    "ироничный, но эмпатичный. Ты говоришь на ты. "
    "Без эзотерического мусора, без воды.\n\n"
    "ВАЖНО:\n-- Объем ответа до 1000 символов.\n"
    "-- Не упоминай, что данные неполные.\n"
    "-- Не оправдывайся. Пиши уверенно.\n\n"
    "Ты обязан правильно определить знак по дате.\n\n"
    "СПИСОК ЗНАКОВ:\nОвен 21.03-19.04\nТелец 20.04-20.05\n"
    "Близнецы 21.05-20.06\nРак 21.06-22.07\n"
    "Лев 23.07-22.08\nДева 23.08-22.09\n"
    "Весы 23.09-22.10\nСкорпион 23.10-21.11\n"
    "Стрелец 22.11-21.12\nКозерог 22.12-19.01\n"
    "Водолей 20.01-18.02\nРыбы 19.02-20.03\n\n"
    "СТРУКТУРА ТЕКСТА:\n1. Резкий инсайт о личности.\n"
    "2. Две сильные стороны.\n3. Одно слабое место.\n"
    "4. Совет на ближайший месяц.\n"
    "5. Намёк, что дальше будет интереснее.")

    short = await client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "system", "content": sys_prompt},
    {"role": "user", "content": f"Дата: {birth_data}. "
    "Определи знак и дай текст по структуре."}],
    max_tokens=400, temperature=0.9)

    text = short.choices[0].message.content
    msg = f"✅ Дата: {birth_data}\n\n{text}"
    await message.answer(msg)
    asyncio.create_task(send_upsell(message.chat.id))

async def send_upsell(chat_id: int):
    await asyncio.sleep(20)
    txt = "Это только 20%.\n\n"
    txt += "В 2026 у тебя будут месяцы, которые решают "
    txt += "всё: деньги, отношения, резкие повороты.\n\n"
    txt += "Хочешь полный прогноз:\n"
    txt += "• деньги,\n"
    txt += "• любовь и кризисы,\n"
    txt += "• твои сильные периоды.\n\n"
    txt += f"{PRICE_STARS} ⭐ — меньше чашки кофе."
    btn = InlineKeyboardButton(text=f"Полный разбор 2026 "
    f"за {PRICE_STARS} ⭐", callback_data="buy_astro2026")
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn]])
    await bot.send_message(chat_id, txt, reply_markup=kb)

@dp.callback_query(F.data == "buy_astro2026")
async def send_invoice(callback: types.CallbackQuery):
    price = LabeledPrice(label="XTR", amount=PRICE_AMOUNT)
    await bot.send_invoice(
    chat_id=callback.from_user.id,
    title="Твоя карта на 2026 год",
    description="Деньги • Отношения • Судьбоносные месяцы.",
    payload="astro2026", provider_token="",
    currency="XTR", prices=[price],
    start_parameter="astro-2026")
    await bot.answer_callback_query(callback.id,
    "Счёт на оплату отправлен.")

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_q: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(
    pre_checkout_q.id, ok=True)

@dp.message(F.successful_payment)
async def on_successful_payment(message: types.Message):
    user_id = message.from_user.id
    async with aiosqlite.connect("users.db") as db:
        async with db.execute("SELECT birth_data FROM users "
        "WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await message.answer("Не найдены данные. "
                "Начни с /start.")
                return
            birth_data = row[0]

    paid_prompt = (
    "Ты профессиональный астролог. Ты точно знаешь "
    "астрологические даты знаков и не ошибаешься.\n\n"
    "Если дата попадает в пограничный период, уверенно "
    "определяешь знак.\n\n"
    "Составь персональный прогноз на 2026 год.\n\n"
    "Определи знак только по дате, используя западную "
    "астрологию:\nОвен 21.03-19.04\n"
    "Телец 20.04-20.05\nБлизнецы 21.05-20.06\n"
    "Рак 21.06-22.07\nЛев 23.07-22.08\n"
    "Дева 23.08-22.09\nВесы 23.09-22.10\n"
    "Скорпион 23.10-21.11\nСтрелец 22.11-21.12\n"
    "Козерог 22.12-19.01\nВодолей 20.01-18.02\n"
    "Рыбы 19.02-20.03\n\n"
    "⚠️ Не перепутай знак. Определи один раз, используй "
    "последовательно.\n\n"
    "Формат:\n--- цельный текст\n--- 900-1100 символов\n"
    "--- без списков, без эмодзи\n"
    "--- уверенный, интимный, точный тон\n"
    "--- без слов возможно, вероятно, может быть\n\n"
    "Структура:\n1. Ключевая тема 2026.\n"
    "2. Деньги: рост, ограничения, периоды.\n"
    "3. Отношения: динамика, напряжения, сближения.\n"
    "4. Самый сильный период 2026 (месяцы).\n"
    "5. Вывод: как прожить год точно.\n\n"
    "Стиль:\nПривет, на связи TONKO и я твой астролог.\n"
    "Я знаю многое о тебе, ведь звёзды редко ошибаются.")

    full = await client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "system", "content": paid_prompt},
    {"role": "user", "content": f"Дата рождения: "
    f"{birth_data}"}],
    max_tokens=1200, temperature=0.8)

    text = full.choices[0].message.content
    await message.answer(text)

async def main():
    await init_db()
    logging.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

