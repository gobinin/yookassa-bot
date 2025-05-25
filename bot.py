import asyncio
import logging
import uuid
import os
import requests

from aiohttp import web
from aiogram import Bot, Dispatcher, Router, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, SHOP_ID, SECRET_KEY

logging.basicConfig(level=logging.INFO)

# === Бот ===
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
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
async def greet_user(message: Message):
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
        "amount": {"value": f"{product['price']:.2f}", "currency": "RUB"},
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
        payment_url = response.json()["confirmation"]["confirmation_url"]
        await callback.message.answer(
            f"🔗 Ссылка для оплаты <b>{product['name']}</b> на {product['price']}₽:\n{payment_url}"
        )
        await callback.answer()
    else:
        await callback.message.answer("❌ Ошибка при создании оплаты.")
        await callback.answer()

dp.include_router(router)

# === Webhook обработчик ===
async def yookassa_webhook_handler(request):
    data = await request.json()
    logging.info("📩 Уведомление от ЮKassa: %s", data)
    return web.Response(text="ok")

def create_app():
    app = web.Application()
    app.router.add_post("/yookassa-webhook", yookassa_webhook_handler)
    return app

# === Главная точка запуска ===
async def on_startup(app):
    asyncio.create_task(dp.start_polling(bot))

if __name__ == "__main__":
    app = create_app()
    app.on_startup.append(on_startup)

    port = int(os.environ.get("PORT", 8080))  # Render подставит переменную PORT
    web.run_app(app, port=port)