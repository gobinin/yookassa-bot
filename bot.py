# bot.py — ЧИСТЫЙ БОТ ДЛЯ ПРИЁМА ЗАКАЗОВ (без YooKassa, админы из .env)
import os
import json
import logging
import asyncio
import re

from aiohttp import web
from aiogram import Bot, Dispatcher, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import CommandStart, Command
from dotenv import load_dotenv

# --- Логи ---
logging.basicConfig(level=logging.INFO)

# --- Конфиг из .env/окружения ---
# файл можно назвать config.env или .env — подхватится любой
load_dotenv("config.env")
load_dotenv()

BOT_TOKEN   = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT        = int(os.getenv("PORT", "3000"))

# читаем список админов из ADMINS_IDS или из ADMIN_IDS — удобно для совместимости
ADMINS_RAW  = os.getenv("ADMINS_IDS") or os.getenv("ADMIN_IDS") or ""

def parse_admins(value: str):
    """
    Поддерживает форматы:
    - "123,456"
    - "123 456"
    - "[123, 456]"
    - "123"
    Возвращает List[int]
    """
    if not value:
        return []
    s = value.strip()
    # формат JSON-списка
    if (s.startswith("[") and s.endswith("]")) or (s.startswith("(") and s.endswith(")")):
        try:
            arr = json.loads(s.replace("(", "[").replace(")", "]"))
            return [int(x) for x in arr if str(x).strip()]
        except Exception as e:
            logging.warning(f"Не удалось распарсить список админов как JSON: {e}")
    # формат через запятую/пробел
    parts = re.split(r"[,\s]+", s)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except:
            logging.warning(f"Пропускаю некорректный admin id: {p}")
    return out

ADMINS = parse_admins(ADMINS_RAW)
# дефолтно подставим твой ID, чтобы точно не было пусто
if not ADMINS:
    ADMINS = [5112853993,1098404204]

# --- Проверка телефона ---
PHONE_RE = re.compile(r"^\+?\d{7,15}$")
def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone.strip()))

# --- Инициализация бота/роутера ---
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не указан в окружении/.env")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# --- Клавиатуры ---
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Сделать заказ", callback_data="start_order")],
        [InlineKeyboardButton(text="ℹ Помощь", callback_data="help")]
    ])

contact_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Отправить контакт", request_contact=True)]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# --- Временное хранилище заказов ---
# {user_id: {"state": "...", "phone":..., "address":..., "items":...}}
order_data = {}

# --- /start ---
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Это бот доставки вашего магазина.\n\n"
        "Удобно оформляйте заказ — курьер привезёт всё к вам.",
        reply_markup=main_menu_keyboard()
    )

# --- Inline-кнопки ---
@router.callback_query()
async def callback_handler(cq: types.CallbackQuery):
    data = (cq.data or "").strip()
    uid = cq.from_user.id

    if data == "start_order":
        order_data[uid] = {"state": "await_contact", "phone": None, "address": None, "items": None}
        await cq.message.answer(
            "📝 Отлично! Для начала пришлите, пожалуйста, ваш номер телефона (курьер сможет с вами связаться).",
            reply_markup=contact_keyboard
        )
        await cq.answer()
        return

    if data == "help":
        await cq.message.answer(
            "Как оформить заказ:\n"
            "1) Нажмите «Сделать заказ»\n"
            "2) Отправьте контакт или введите номер\n"
            "3) Введите адрес доставки\n"
            "4) Напишите список товаров\n\n"
            "После отправки заказа админ или курьер свяжется с вами."
        )
        await cq.answer()
        return

    await cq.answer()

# --- Основной обработчик сообщений ---
@router.message()
async def messages_handler(message: Message):
    uid = message.from_user.id
    text = (message.text or "").strip()

    # пользователь заполняет заказ
    if uid in order_data:
        state = order_data[uid].get("state")

        # 1) телефон
        if state == "await_contact":
            phone = None
            if message.contact and message.contact.phone_number:
                phone = message.contact.phone_number
            elif text and is_valid_phone(text):
                phone = text
            else:
                await message.answer("❗ Пожалуйста, отправьте контакт через кнопку или введите номер в формате +79991234567.")
                return

            order_data[uid]["phone"] = phone
            order_data[uid]["state"] = "await_address"
            await message.answer("📍 Отлично. Теперь напишите адрес доставки (улица, дом, подъезд, этаж).", reply_markup=ReplyKeyboardRemove())
            return

        # 2) адрес
        if state == "await_address":
            if not text:
                await message.answer("❗ Введите адрес текстом (например: ул. Ленина, д. 15, кв. 3, подъезд 2).")
                return
            order_data[uid]["address"] = text
            order_data[uid]["state"] = "await_items"
            await message.answer("🛒 Напишите список товаров (пример: хлеб, молоко, яйца). Указывайте подробно.")
            return

        # 3) перечень товаров
        if state == "await_items":
            if not text:
                await message.answer("❗ Введите список товаров текстом.")
                return
            order_data[uid]["items"] = text

            # собираем заказ
            user = message.from_user
            user_name = user.full_name or "Клиент"
            username = f"@{user.username}" if user.username else "—"

            order_text = (
                f"📬 <b>Новый заказ</b>\n\n"
                f"👤 Клиент: {user_name} ({username})\n"
                f"🆔 UserID: <code>{uid}</code>\n"
                f"📱 Телефон: {order_data[uid]['phone']}\n"
                f"📍 Адрес: {order_data[uid]['address']}\n"
                f"🛍 Список товаров:\n{order_data[uid]['items']}\n\n"
                "— Ответить клиенту можно прямо в Telegram."
            )

            # отправляем всем админам (из .env)
            send_errors = False
            for admin_id in ADMINS:
                try:
                    await bot.send_message(int(admin_id), order_text)
                except Exception as e:
                    logging.error(f"Ошибка отправки админу {admin_id}: {e}")
                    send_errors = True

            if send_errors:
                await message.answer("⚠ Заказ принят, но возникли ошибки при отправке админам. Проверьте настройки.")
            else:
                await message.answer("✅ Спасибо! Ваш заказ отправлен. Скоро с вами свяжется курьер.")

            order_data.pop(uid, None)
            return

    # не в процессе — подсказываем
    if text:
        await message.answer("Чтобы оформить заказ — нажмите /start и затем кнопку «Сделать заказ».")

# --- Webhook / сервер для Render ---
async def telegram_webhook_handler(request: web.Request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.error(f"Ошибка при обработке Telegram-обновления: {e}")
    return web.Response(text="ok")

async def root_handler(request):
    return web.json_response({"status": "ok", "message": "bot running"})

async def on_startup(app):
    if WEBHOOK_URL:
        try:
            await bot.set_webhook(WEBHOOK_URL)
            logging.info(f"Webhook установлен: {WEBHOOK_URL}")
        except Exception as e:
            logging.error(f"Не удалось установить webhook: {e}")
    else:
        logging.info("WEBHOOK_URL не указан — для Render он обязателен.")

async def on_cleanup(app):
    try:
        await bot.delete_webhook()
    except:
        pass
    await bot.session.close()

def setup_web_app():
    app = web.Application()
    app.router.add_post("/webhook", telegram_webhook_handler)
    app.router.add_get("/", root_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

async def main():
    app = setup_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Server started on port {PORT}")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())