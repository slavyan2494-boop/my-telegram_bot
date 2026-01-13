# -*- coding: utf-8 -*-
from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
from datetime import datetime
from calendar import monthrange
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, FSInputFile
from fastapi import FastAPI
from uvicorn import Server, Config
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramForbiddenError
import aiosqlite

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003310607267"))  # default as str

PRICE = 100
ORIGINAL_PRICE = 1990
PDF_PATH = "guide.pdf"
MAX_QUESTIONS_PER_DAY = 3
DB_PATH = "bot.db"

# Проверка файла
print("🔧 Текущая папка:", os.getcwd())
print("📄 Файлы в папке:", os.listdir('.'))
if not os.path.exists(PDF_PATH):
    print("❌ ФАЙЛ НЕ НАЙДЕН: guide.pdf")
    exit()
else:
    print("✅ Файл guide.pdf найден — бот запускается")

# ================= ИНИЦИАЛИЗАЦИЯ =================
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ================= ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =================
awaiting_question = set()      # Кто вводит вопрос
user_states = {}               # Тип вопроса (urgent/normal)
active_tasks = {}              # Активные фоновые задачи

# ================= БАЗА ДАННЫХ (SQLite) =================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                is_paid INTEGER DEFAULT 0,
                first_seen TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                user_id INTEGER,
                date TEXT,
                count INTEGER,
                PRIMARY KEY (user_id, date)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER
            )
        """)
        await db.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('sales_count', 15)")
        await db.commit()

async def is_user_paid(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_paid FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return bool(row[0]) if row else False

async def mark_user_as_paid(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, is_paid, first_seen) VALUES (?, 1, datetime('now')) "
            "ON CONFLICT(user_id) DO UPDATE SET is_paid = 1",
            (user_id,)
        )
        await db.commit()

async def get_sales_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM stats WHERE key = 'sales_count'") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def increment_sales_count():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE stats SET value = value + 1 WHERE key = 'sales_count'")
        await db.commit()

async def save_question_count(user_id: int, count: int):
    now = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO questions (user_id, date, count) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, date) DO UPDATE SET count = ?",
            (user_id, now, count, count)
        )
        await db.commit()

async def get_question_count(user_id: int) -> int:
    now = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT count FROM questions WHERE user_id = ? AND date = ?", (user_id, now)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

# ================= КНОПКИ =================
subscribe_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/+Kl_YyVIMrXNkMDMy")],
    [InlineKeyboardButton(text="✅ Я подписан(а)", callback_data="check_sub")]
])

ask_question_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Обычный вопрос 🟡", callback_data="ask_normal")],
    [InlineKeyboardButton(text="Срочно ❗️", callback_data="ask_urgent")],
    [InlineKeyboardButton(text="Назад ◀️", callback_data="back_to_menu")]
])

main_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Купить гайд 🔥", callback_data="buy")],
    [InlineKeyboardButton(text="О гайде ℹ️", callback_data="about")],
    [InlineKeyboardButton(text="Частые вопросы ❓", callback_data="faq")],
    [InlineKeyboardButton(text="Задать вопрос 📩", callback_data="ask_question")]
])

buy_button_with_back = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=f"Оплатить {PRICE} ₽ 💳", callback_data="pay")],
    [InlineKeyboardButton(text="Назад ◀️", callback_data="back_to_menu")]
])

about_back_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Назад ◀️", callback_data="back_to_menu")]
])

back_to_menu_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Назад ◀️", callback_data="back_to_menu")]
])

# ================= /start =================
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "🚀 Хочешь выбраться из найма и запустить доход через Telegram?\n\n"
        "Я покажу путь — без аудитории и бюджета.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👉 Начать", callback_data="show_subscribe")]
        ])
    )

# ================= /whoami =================
@dp.message(Command("whoami"))
async def cmd_whoami(message: types.Message):
    try:
        await message.answer(f"Ваш ID: <code>{message.from_user.id}</code>", parse_mode="HTML")
    except (TelegramBadRequest, TelegramNetworkError):
        pass  # Игнорируем ошибки отправки

# ================= ПОДПИСКА =================
@dp.callback_query(F.data == "check_sub")
async def check_sub(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status not in ("member", "administrator", "creator"):
            await callback.answer("❌ Нет подписки", show_alert=True)
            return
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError):
        await callback.answer("⚠️ Ошибка проверки", show_alert=True)
        return

    now = datetime.now()
    last_day = monthrange(now.year, now.month)[1]
    end_date = f"{last_day} {['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'][now.month-1]}"

    text = (
        f"✅ <b>Привет, ты в деле! Подписка подтверждена 🎉</b>\n\n"
        f"⏳ Скидка действует до {end_date} — <u>успей купить по минимальной цене</u>\n\n"
        f"⚠️ Если ты ничего не изменишь — через год будешь в той же точке.\n\n"
        f"📘 Этот гайд — не мотивация.\n"
        f"Это пошаговая инструкция как сделать и запустить\n"
        f"Ты просто следуешь — и получаешь результат."
    )
    await callback.message.edit_text(text, reply_markup=main_menu, parse_mode="HTML")

    if user_id not in active_tasks:
        task = asyncio.create_task(funnel_reminder(user_id))
        active_tasks[user_id] = task

    await callback.answer()

# ================= О ГАЙДЕ =================
@dp.callback_query(F.data == "about")
async def about_guide(callback: types.CallbackQuery):
    text = (
        "📘 <b>О гайде: «Цифровой продукт с нуля»</b>\n\n"
        "Этот гайд — пошаговая инструкция для запуска первого цифрового продукта в Telegram.\n\n"
        "📌 <b>Что внутри:</b>\n\n"
        "• — План и упаковка идеи\n"
        "• — Как это продавать\n"
        "• — Создание контента\n"
        "• — Дизайн и финальный PDF\n"
        "• — Магазин и платежи\n"
        "• — Настройка автоматизации\n"
        "• — Цена и первые клиенты\n"
        "• — Презентация и отзывы\n"
        "• — Работа с покупателями\n"
        "• — Итоги и планы на месяц\n\n"
        "🚀 <b>Подходит для новичков. Никакой воды — только действия.</b>"
    )
    await callback.message.edit_text(text, reply_markup=about_back_button, parse_mode="HTML")
    await callback.answer()

# ================= FAQ =================
@dp.callback_query(F.data == "faq")
async def show_faq(callback: types.CallbackQuery):
    faq_text = (
        "📘 <b>Частые вопросы</b>\n\n"
        "🔸 <b>Что входит в гайд?</b>\n"
        "Полная инструкция: как найти идею, упаковать продукт, запустить продажи и автоматизировать процесс — без аудитории и бюджета.\n\n"
        "🔸 <b>Как получить гайд после оплаты?</b>\n"
        "После оплаты бот пришлёт файл автоматически.\n\n"
        "🔸 <b>Что, если я не разберусь?</b>\n"
        "Ты можешь задать мне любой вопрос — я отвечу в течение 24 часов.\n\n"
        "🔸 <b>Можно ли вернуть деньги?</b>\n"
        "К сожалению, возврат невозможен, так как это цифровой продукт.\n\n"
        "🔸 <b>Сколько в среднем нужно времени на первый результат?</b>\n"
        "Кто приобрел и следует гайду, получают первые заявки или продажи в течение 1-2 недель. Скорость зависит от твоего вовлечения. Главное — начать по четкому плану."
    )
    await callback.message.edit_text(faq_text, reply_markup=back_to_menu_button, parse_mode="HTML")
    await callback.answer()

# ================= ПОКУПКА =================
@dp.callback_query(F.data == "buy")
async def buy(callback: types.CallbackQuery):
    offer_url = "https://example.com/public-offer"
    now = datetime.now()
    last_day = monthrange(now.year, now.month)[1]
    end_date = f"{last_day} {['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'][now.month-1]}"
    sales_count = await get_sales_count()

    text = (
        "📘 <b>Гайд: Цифровой продукт с нуля</b>\n\n"
        "— Без аудитории\n"
        "— Без бюджета\n"
        "— Без опыта\n\n"
        f"🔥 Купили: <b>{sales_count} раз</b>\n\n"
        f"💸 Цена до {end_date}: <b>{PRICE} ₽</b>\n"
        f"❌ Обычная: <s><b>{ORIGINAL_PRICE} ₽</b></s>\n\n"
        f"Оплачивая, вы соглашаетесь с публичной <a href='{offer_url}'>офертой</a>."
    )
    await callback.message.edit_text(text, reply_markup=buy_button_with_back, parse_mode="HTML")
    await callback.answer()

# ================= ОПЛАТА =================
@dp.callback_query(F.data == "pay")
async def pay(callback: types.CallbackQuery):
    prices = [LabeledPrice(label="PDF-гайд", amount=PRICE * 100)]
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Гайд",
        description="Цифровой продукт с нуля",
        payload="guide",
        provider_token=PROVIDER_TOKEN,
        currency="RUB",
        prices=prices
    )
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout(pre: types.PreCheckoutQuery):
    await pre.answer(ok=True)

@dp.message(F.successful_payment)
async def success(message: types.Message):
    user_id = message.from_user.id

    if not await is_user_paid(user_id):
        await mark_user_as_paid(user_id)
        await increment_sales_count()
        new_count = await get_sales_count()

        try:
            await bot.send_message(
                ADMIN_ID,
                f"🎉 <b>Новая продажа!</b>\n\n"
                f"🔢 Номер: <b>#{new_count}</b>\n"
                f"👤 Пользователь: <code>{user_id}</code>\n"
                f"🕒 Время: {datetime.now().strftime('%H:%M %d.%m')}",
                parse_mode="HTML"
            )
        except (TelegramBadRequest, TelegramNetworkError, TelegramForbiddenError):
            print(f"[ALERT] Не удалось отправить отчёт админу о продаже #{new_count}")

    await message.answer("🎉 Оплата прошла успешно!")
    await message.answer_document(document=FSInputFile(PDF_PATH))
    await asyncio.sleep(2)
    await message.answer(
        "🎉 Поздравляю — ты в деле!\n\n"
        "📌 Как получить результат:\n\n"
        "1️⃣ Прочитай гайд целиком\n"
        "2️⃣ Выбери одну идею\n"
        "3️⃣ Сделай первый шаг — уже сегодня",
        parse_mode="HTML"
    )

# ================= ЗАДАТЬ ВОПРОС =================
@dp.callback_query(F.data == "ask_question")
async def ask_question(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    used = await get_question_count(user_id)
    remaining = MAX_QUESTIONS_PER_DAY - used

    if remaining <= 0:
        await callback.message.edit_text(
            "⏳ Ты уже использовал все 3 вопроса сегодня.\n"
            "Новые появятся завтра.",
            reply_markup=about_back_button
        )
        await callback.answer()
        return

    text = (
        f"✍️ <b>Задай свой вопрос</b>\n\n"
        f"🟡 <b>Обычный</b> — отвечу в течение 24 часов\n"
        f"❗️ <b>Срочно</b> — постараюсь быстрее\n\n"
        f"📌 Осталось вопросов сегодня: <b>{remaining}</b>"
    )
    await callback.message.edit_text(text, reply_markup=ask_question_keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "ask_normal")
async def ask_normal(callback: types.CallbackQuery):
    await set_awaiting_question(callback, urgent=False)

@dp.callback_query(F.data == "ask_urgent")
async def ask_urgent(callback: types.CallbackQuery):
    await set_awaiting_question(callback, urgent=True)

async def set_awaiting_question(callback: types.CallbackQuery, urgent: bool):
    user_id = callback.from_user.id
    used = await get_question_count(user_id)

    if used >= MAX_QUESTIONS_PER_DAY:
        await callback.message.edit_text(
            "⏳ Ты уже задал 3 вопроса сегодня.\nМожно снова завтра.",
            reply_markup=about_back_button
        )
        await callback.answer()
        return

    awaiting_question.add(user_id)
    user_states[user_id] = "urgent" if urgent else "normal"
    await save_question_count(user_id, used + 1)

    await callback.message.edit_text(
        "💬 Напиши свой вопрос текстом.\n"
        "Я его получил и отвечу в ближайшее время.",
        reply_markup=None
    )
    await callback.answer()

# ================= ОБРАБОТКА СООБЩЕНИЙ =================
@dp.message(F.text)
async def handle_all_text(message: types.Message):
    text = message.text.strip()
    user_id = message.from_user.id

    if user_id == ADMIN_ID and text.startswith("/reply"):
        await handle_admin_reply(message)
        return

    if user_id in awaiting_question:
        await handle_user_question(message)
        return

# === Ответ от админа ===
async def handle_admin_reply(message: types.Message):
    text = message.text.strip()
    try:
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("❌ Формат: /reply ID Текст")
            return

        target_id = int(parts[1])
        reply_text = parts[2]

        await bot.send_message(
            chat_id=target_id,
            text=f"<b>📬 Ответ от автора:</b>\n\n{reply_text}",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Ответ отправлен: <code>{target_id}</code>", parse_mode="HTML")

    except ValueError:
        await message.answer("❌ ID должно быть числом")
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        if "blocked" in str(e).lower():
            await message.answer("🚫 Пользователь заблокировал бота")
        else:
            await message.answer("❌ Ошибка при отправке ответа")

# === Вопрос от пользователя ===
async def handle_user_question(message: types.Message):
    user_id = message.from_user.id
    state = user_states.pop(user_id, "normal")
    is_urgent = state == "urgent"
    awaiting_question.discard(user_id)

    username = message.from_user.username
    name = message.from_user.full_name
    from_info = f"👤 {name}"
    if username:
        from_info += f" (@{username})"
    from_info += f" | ID: {user_id}"

    admin_message = (
        f"{'❗️ СРОЧНЫЙ ВОПРОС ❗️' if is_urgent else '💬 Новый вопрос'}\n\n"
        f"{from_info}\n\n"
        f"<b>Текст вопроса:</b>\n"
        f"{message.text}\n\n"
        f"📩 Чтобы ответить — введи:\n"
        f"<code>/reply {user_id} Текст ответа</code>\n\n"
        f"⏰ {datetime.now().strftime('%H:%M %d.%m')}"
    )

    try:
        await bot.send_message(ADMIN_ID, admin_message, parse_mode="HTML")
        await message.answer(
            "✅ Вопрос отправлен!\n\n"
            "Я отвечу тебе в течение 24 часов.\n\n"
            "❗️ Не удаляй чат с ботом — иначе не получишь ответ.",
            reply_markup=main_menu
        )
    except (TelegramBadRequest, TelegramNetworkError):
        await message.answer(
            "❌ Не удалось отправить вопрос.\n"
            "Попробуй позже или напиши: @knopesh",
            reply_markup=main_menu
        )

# ================= НАЗАД В МЕНЮ =================
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    now = datetime.now()
    last_day = monthrange(now.year, now.month)[1]
    end_date = f"{last_day} {['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'][now.month-1]}"
    sales_count = await get_sales_count()

    text = (
        f"🔥 <b>{sales_count}</b> единомышленников уже в деле\n\n"
        "🚀 Твое время - сделать шаг\n\n"
        f"⏳ <i>Спеццена ждет тебя до {end_date}</i>\n\n"
        "<b>Выбери, что хочешь сделать:</b> 👇🏻"
    )
    await callback.message.edit_text(text, reply_markup=main_menu, parse_mode="HTML")
    await callback.answer()

# ================= ВОРОНКА =================
async def funnel_reminder(user_id: int):
    try:
        await asyncio.sleep(3600)
        if not await is_user_paid(user_id):
            now = datetime.now()
            last_day = monthrange(now.year, now.month)[1]
            end_date = f"{last_day} {['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'][now.month-1]}"
            await bot.send_message(
                user_id,
                f"⏳ Скидка действует до {end_date} — успей купить по минимальной цене!",
                reply_markup=buy_button_with_back
            )

        await asyncio.sleep(14400)
        if not await is_user_paid(user_id):
            await bot.send_message(
                user_id,
                "🔥 Последний шанс взять гайд по минимальной цене.",
                reply_markup=buy_button_with_back
            )
    except (TelegramBadRequest, TelegramNetworkError, TelegramForbiddenError) as e:
        print(f"[FUNNEL] Ошибка напоминания: {e}")
    finally:
        if user_id in active_tasks:
            del active_tasks[user_id]

# ================= HTTP SERVER ДЛЯ RENDER =================
web_app = FastAPI()

@web_app.get("/")
def root():
    return {"status": "Telegram bot is running"}

async def run_server():
    port = int(os.getenv("PORT", "10000"))  # ✅ default as str
    config = Config(web_app, host="0.0.0.0", port=port)
    server = Server(config)
    await server.serve()

# ================= ЗАПУСК =================
async def main():
    await init_db()
    try:
        await bot.get_me()
        print("✅ Бот запущен и готов к работе")
    except (TelegramNetworkError, TelegramBadRequest) as e:
        print(f"❌ Ошибка подключения к Telegram: {e}")
        return

    await asyncio.gather(
        dp.start_polling(bot),
        run_server()
    )

if __name__ == "__main__":
    asyncio.run(main())