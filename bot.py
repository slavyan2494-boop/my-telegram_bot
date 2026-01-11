
# -*- coding: utf-8 -*-
from dotenv import load_dotenv
load_dotenv()
import sys
import asyncio
import os
import pickle
from datetime import datetime, timedelta
from calendar import monthrange
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, FSInputFile
from fastapi import FastAPI
from uvicorn import Server, Config

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", -1003310607267))  # -100... по умолчанию

PRICE = 199
ORIGINAL_PRICE = 990
PDF_PATH = "guide.pdf"
MAX_QUESTIONS_PER_DAY = 25

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

# ================= ХРАНИЛИЩА =================
def load_set(filename):
    try:
        with open(filename, "rb") as f:
            return set(pickle.load(f))
    except:
        return set()

def save_set(data, filename):
    with open(filename, "wb") as f:
        pickle.dump(list(data), f)

def load_int(filename, default=0):
    try:
        with open(filename, "rb") as f:
            return pickle.load(f)
    except:
        return default

def save_int(value, filename):
    with open(filename, "wb") as f:
        pickle.dump(value, f)

def load_questions_db():
    try:
        with open("questions_db.pkl", "rb") as f:
            return pickle.load(f)
    except:
        return {}

def save_questions_db():
    with open("questions_db.pkl", "wb") as f:
        pickle.dump(questions_db, f)

# Глобальные переменные
paid_users = load_set("paid_users.pkl")
sales_count = load_int("sales_count.pkl", 15)
questions_db = load_questions_db()
awaiting_question = set()
user_states = {}
active_tasks = {}

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
    except:
        pass

# ================= ПОДПИСКА =================
@dp.callback_query(F.data == "show_subscribe")
async def show_subscribe(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Чтобы продолжить, подпишись на канал 👇",
        reply_markup=subscribe_keyboard
    )
    await callback.answer()

@dp.callback_query(F.data == "check_sub")
async def check_sub(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status not in ("member", "administrator", "creator"):
            await callback.answer("❌ Нет подписки", show_alert=True)
            return
    except:
        await callback.answer("⚠️ Ошибка проверки", show_alert=True)
        return

    now = datetime.now()
    last_day = monthrange(now.year, now.month)[1]
    end_date = f"{last_day} {['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'][now.month-1]}"

    await callback.message.edit_text(
        f"✅ Подписка подтверждена!\n\n"
        f"⏳ Скидка действует до {end_date}\n\n"
        "⚠️ Если ты ничего не изменишь — через год будешь в той же точке.\n\n"
        "Этот гайд — не мотивация. Это шаги.",
        reply_markup=main_menu
    )

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
        "📌 Что внутри:\n"
        "✅ Как найти идею без опросов и спама\n"
        "✅ Упаковка: название, обложка, описание\n"
        "✅ Продажи без аудитории — 3 рабочих способа\n"
        "✅ Автоматизация: бот, ссылки, воронка\n"
        "✅ Чек-лист «7 дней до первой продажи»\n\n"
        "🚀 Подходит для новичков. Никакой воды — только действия."
    )
    await callback.message.edit_text(text, reply_markup=about_back_button, parse_mode="HTML")
    await callback.answer()

# ================= FAQ — ЧАСТЫЕ ВОПРОСЫ =================
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

        "🔸 <b>Как часто обновляется гайд?</b>\n"
        "Обновления отправляются автоматически всем покупателям раз в месяц."
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

    text = (
        "📘 <b>Гайд: Цифровой продукт с нуля</b>\n\n"
        "— Без аудитории\n"
        "— Без бюджета\n"
        "— Без опыта\n\n"
        f"🔥 Купили: <b>{sales_count} раз</b>\n\n"
        f"💸 Цена до {end_date}: <b>{PRICE} ₽</b>\n"
        f"❌ Обычная: <s>{ORIGINAL_PRICE} ₽</s>\n\n"
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
    global sales_count
    user_id = message.from_user.id

    if user_id not in paid_users:
        paid_users.add(user_id)
        save_set(paid_users, "paid_users.pkl")
        sales_count += 1
        save_int(sales_count, "sales_count.pkl")

    await message.answer("🎉 Оплата прошла успешно!")
    await message.answer_document(document=FSInputFile(PDF_PATH), caption="📘 Твой гайд")

    await asyncio.sleep(2)
    await message.answer(
        "<b>📌 Как использовать гайд</b>\n\n"
        "1️⃣ Прочитай полностью\n"
        "2️⃣ Выбери одну идею\n"
        "3️⃣ Сделай первый шаг",
        parse_mode="HTML"
    )

# ================= ЗАДАТЬ ВОПРОС =================
@dp.callback_query(F.data == "ask_question")
async def ask_question(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    user_data = questions_db.get(user_id)
    used = user_data["count"] if user_data and user_data["date"] == today_str else 0
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
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    user_data = questions_db.get(user_id)

    if user_data and user_data["date"] == today_str:
        if user_data["count"] >= MAX_QUESTIONS_PER_DAY:
            await callback.message.edit_text(
                "⏳ Ты уже задал 3 вопроса сегодня.\nМожно снова завтра.",
                reply_markup=about_back_button
            )
            await callback.answer()
            return
        user_data["count"] += 1
    else:
        questions_db[user_id] = {"date": today_str, "count": 1}

    awaiting_question.add(user_id)
    user_states[user_id] = "urgent" if urgent else "normal"
    save_questions_db()

    await callback.message.edit_text(
        "💬 Напиши свой вопрос текстом.\n"
        "Я его получил и отвечу в ближайшее время.",
        reply_markup=None
    )
    await callback.answer()

# ================= ОБРАБОТКА ВСЕХ СООБЩЕНИЙ =================
@dp.message(F.text)
async def handle_all_text(message: types.Message):
    text = message.text.strip()
    user_id = message.from_user.id

    print(f"[DEBUG] Получено: {repr(text)} от {user_id}")

    # === 1. Обработка /reply от админа ===
    if user_id == ADMIN_ID and text.startswith("/reply"):
        await handle_admin_reply(message)
        return

    # === 2. Обработка текста вопроса от пользователя ===
    if user_id in awaiting_question:
        await handle_user_question(message)
        return

# === Функция: ответ от админа ===
async def handle_admin_reply(message: types.Message):
    text = message.text.strip()
    try:
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("❌ Формат: /reply ID Текст")
            print("[REPLY] Ошибка: недостаточно аргументов")
            return

        target_id = int(parts[1])
        reply_text = parts[2]

        print(f"[REPLY] Ответ на {target_id}: {reply_text}")

        await bot.send_message(
            chat_id=target_id,
            text=f"<b>📬 Ответ от автора:</b>\n\n{reply_text}",
            parse_mode="HTML"
        )
        await message.answer(
            f"✅ Ответ отправлен: <code>{target_id}</code>",
            parse_mode="HTML"
        )
        print(f"[REPLY] Успешно отправлено {target_id}")

    except ValueError:
        await message.answer("❌ ID должно быть числом")
        print("[REPLY] Ошибка: неверный формат ID")
    except Exception as e:
        error = str(e)
        print(f"[REPLY] Ошибка: {error}")
        if "blocked" in error.lower():
            await message.answer("🚫 Пользователь заблокировал бота")
        else:
            await message.answer(f"❌ Ошибка: {e}")

# === Функция: вопрос от пользователя ===
async def handle_user_question(message: types.Message):
    user_id = message.from_user.id
    now = datetime.now()
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
        f"⏰ {now.strftime('%H:%M %d.%m')}"
    )

    try:
        await bot.send_message(ADMIN_ID, admin_message, parse_mode="HTML")
        await message.answer(
            "✅ Вопрос отправлен!\n\n"
            "Я отвечу тебе в течение 24 часов.\n\n"
            "❗️ Не удаляй чат с ботом — иначе не получишь ответ.",
            reply_markup=main_menu
        )
        print(f"[QUESTION] Вопрос от {user_id} отправлен")
    except Exception as e:
        await message.answer(
            "❌ Не удалось отправить вопрос.\n"
            "Попробуй позже или напиши: @knopesh",
            reply_markup=main_menu
        )
        print(f"[ERROR] Ошибка отправки вопроса от {user_id}: {e}")

# ================= НАЗАД В МЕНЮ =================
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    now = datetime.now()
    last_day = monthrange(now.year, now.month)[1]
    end_date = f"{last_day} {['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'][now.month-1]}"

    text = (
        f"🔥 <b>{sales_count}+</b> человек уже запустили свой путь\n\n"
        f"⏳ Скидка действует до {end_date}\n\n"
        "🚀 А ты?\n"
        "Выбери, что хочешь сделать:"
    )
    await callback.message.edit_text(text, reply_markup=main_menu, parse_mode="HTML")
    await callback.answer()

# ================= ВОРОНКА =================
async def funnel_reminder(user_id: int):
    try:
        await asyncio.sleep(3600)
        if user_id not in paid_users:
            now = datetime.now()
            last_day = monthrange(now.year, now.month)[1]
            end_date = f"{last_day} {['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'][now.month-1]}"
            await bot.send_message(
                user_id,
                f"⏳ Скидка действует до {end_date} — успей купить по минимальной цене!",
                reply_markup=buy_button_with_back
            )

        await asyncio.sleep(14400)
        if user_id not in paid_users:
            await bot.send_message(
                user_id,
                "🔥 Последний шанс взять гайд по минимальной цене.",
                reply_markup=buy_button_with_back
            )
    except:
        pass
    finally:
        if user_id in active_tasks:
            del active_tasks[user_id]

# ================= HTTP SERVER ДЛЯ RENDER =================
from fastapi import FastAPI
from uvicorn import Server, Config

web_app = FastAPI()

@web_app.get("/")
def root():
    return {"status": "Telegram bot is running"}

async def run_server():
    config = Config(web_app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
    server = Server(config)
    await server.serve()
# ================= ЗАПУСК =================
async def main():
    try:
        await bot.get_me()
        print("✅ Бот запущен и готов к работе")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return

    # Запускаем бота и веб-сервер одновременно
    await asyncio.gather(
        dp.start_polling(bot),
        run_server()
    )