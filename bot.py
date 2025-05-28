import logging
import uuid
import os
import asyncio
import requests

from aiohttp import web
from aiogram import Bot, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN, SHOP_ID, SECRET_KEY

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
router = Router()

products = {
    "bot_course": {"name": "Курс: Как создать бота", "price": 199},
    "pdf_guide": {"name": "PDF-инструкция", "price": 99},
    "combo": {"name": "Пакет: Курс + Гайд", "price": 249},
}

def product_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{v['name']} – {v['price']}₽", callback_data=k)]
        for k, v in products.items()
    ])

@router.message(CommandStart())
@router.message()
async def greet_user(message: types.Message):
    await message.answer(
        "👋 Приветствуем в вашем цифровом магазине!\n\n"
        "Выберите товар для покупки:",
        reply_markup=product_keyboard()
    )

@router.callback_query()
async def handle_product_selection(callback: types.CallbackQuery):
    product_id = callback.data
    product = products.get(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    payment_data = {
        "amount": {
            "value": f"{product['price']:.2f}",
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/{(await bot.get_me()).username}"
        },
        "capture": True,
        "description": f"Покупка: {product['name']}"
    }

    response = requests.post(
        "https://api.yookassa.ru/v3/payments",
        json=payment_data,
        auth=(SHOP_ID, SECRET_KEY),
        headers={
            "Idempotence-Key": str(uuid.uuid4()),
            "Content-Type": "application/json"
        }
    )

    if response.status_code == 200:
        url = response.json()["confirmation"]["confirmation_url"]
        await callback.message.answer(
            f"🔗 Ссылка для оплаты <b>{product['name']}</b> на {product['price']}₽:\n{url}"
        )
    else:
        await callback.message.answer("❌ Ошибка при создании оплаты.")
    await callback.answer()

# Webhook обработчик от Telegram
async def telegram_webhook_handler(request: web.Request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await router.process_update(update)  # Важно — вызываем именно router.process_update
    except Exception as e:
        logging.error(f"Ошибка обработки обновления: {e}")
    return web.Response(text="ok")

# Обработчик webhook от ЮKassa
async def yookassa_webhook_handler(request: web.Request):
    data = await request.json()
    logging.info(f"📩 Уведомление от ЮKassa: {data}")
    return web.Response(text="ok")

# Просто корневая страница для проверки сервера
async def root_handler(request: web.Request):
    return web.json_response({"status": "ok", "message": "Бот работает!"})

async def on_startup(app: web.Application):
    webhook_url = os.getenv("WEBHOOK_URL")  # Например, https://yourdomain.com/webhook
    if not webhook_url:
        logging.error("WEBHOOK_URL не задан в переменных окружения")
        return
    await bot.set_webhook(webhook_url)
    logging.info(f"Webhook установлен на {webhook_url}")

async def on_cleanup(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()

def setup_web_app():
    app = web.Application()
    app.router.add_post("/yookassa-webhook", yookassa_webhook_handler)
    app.router.add_post("/webhook", telegram_webhook_handler)  # Telegram webhook URL
    app.router.add_get("/", root_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

async def main():
    port = int(os.getenv("PORT", 3000))
    app = setup_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"🚀 Сервер запущен на порту {port}")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
