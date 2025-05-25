import logging
import uuid
import os
import asyncio
import requests
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from config import BOT_TOKEN, SHOP_ID, SECRET_KEY

# Логирование
logging.basicConfig(level=logging.INFO)

# Бот и диспетчер
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()

# Товары
products = {
    "bot_course": {"name": "Курс: Как создать бота", "price": 199},
    "pdf_guide": {"name": "PDF-инструкция", "price": 99},
    "combo": {"name": "Пакет: Курс + Гайд", "price": 249},
}

# Клавиатура
def product_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{v['name']} – {v['price']}₽", callback_data=k)]
        for k, v in products.items()
    ])

# Обработка команд
@router.message(CommandStart())
@router.message()
async def greet_user(message: Message):
    await message.answer(
        "👋 Приветствуем в вашем цифровом магазине!\n\n"
        "Выберите товар для покупки:",
        reply_markup=product_keyboard()
    )

# Обработка кнопок
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

dp.include_router(router)

# Webhook ЮKassa
async def yookassa_webhook_handler(request):
    data = await request.json()
    logging.info(f"📩 Уведомление от ЮKassa: {data}")
    return web.Response(text="ok")

# aiohttp-приложение
def setup_web_app():
    app = web.Application()
    app.router.add_post("/yookassa-webhook", yookassa_webhook_handler)
    return app

# Основной запуск
async def start():
    port = int(os.getenv("PORT", 3000))  # Render подставит свой порт
    app = setup_web_app()

    # Параллельный запуск бота и сервера
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logging.info("✅ Сервер запущен, бот работает.")
    await dp.start_polling(bot)

# Запуск (без asyncio.run, безопасно для Windows)
loop = asyncio.get_event_loop()
loop.run_until_complete(start())