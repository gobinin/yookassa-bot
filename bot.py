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

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()

dp.include_router(router)

products = {
    "bot_course": {"name": "Курс: Как создать бота", "price": 199, "file_path": "files/bot_course.pdf"},
    "pdf_guide": {"name": "PDF-инструкция", "price": 99, "file_path": "files/guide.pdf"},
    "combo": {"name": "Пакет: Курс + Гайд", "price": 249, "file_path": "files/combo.zip"},
}

pending_payments = {}

def product_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{v['name']} – {v['price']}₽", callback_data=k)]
        for k, v in products.items()
    ])

@router.message(CommandStart())
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

    # Вот тут убираем чек (receipt) — делаем простой запрос
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
        "description": f"{callback.from_user.id}:{product_id}"  # сохраняем ID покупателя и товара
    }

    response = requests.post(
        "https://api.yookassa.ru/v3/payments",
        json=payment_data,
        auth=(str(SHOP_ID), SECRET_KEY),
        headers={
            "Idempotence-Key": str(uuid.uuid4()),
            "Content-Type": "application/json"
        }
    )

    if response.status_code == 201:
        data = response.json()
        url = data["confirmation"]["confirmation_url"]
        payment_id = data["id"]
        pending_payments[payment_id] = callback.from_user.id
        await callback.message.answer(
            f"🔗 Ссылка для оплаты <b>{product['name']}</b> на {product['price']}₽:\n{url}"
        )
    else:
        logging.error(f"Ошибка от ЮKassa: {response.status_code} — {response.text}")
        await callback.message.answer(
            f"❌ Ошибка при создании оплаты.\n\n{response.json().get('description', 'Нет описания ошибки')}"
        )
    await callback.answer()

async def yookassa_webhook_handler(request):
    data = await request.json()
    logging.info(f"📩 Уведомление от ЮKassa: {data}")

    event = data.get("event")
    obj = data.get("object", {})
    payment_id = obj.get("id")
    status = obj.get("status")
    description = obj.get("description", "")

    if event == "payment.succeeded" and status == "succeeded":
        try:
            user_id_str, product_id = description.split(":")
            user_id = int(user_id_str)
            product = products.get(product_id)
            if product:
                file_path = product["file_path"]
                if os.path.exists(file_path):
                    await bot.send_document(user_id, types.FSInputFile(file_path))
                else:
                    await bot.send_message(user_id, f"✅ Оплата за <b>{product['name']}</b> прошла!\nНо файл не найден.")
            else:
                await bot.send_message(user_id, "✅ Оплата получена, но товар не найден.")
        except Exception as e:
            logging.error(f"Ошибка при разборе уведомления: {e}")
    return web.Response(text="ok")

async def root_handler(request):
    return web.json_response({"status": "ok", "message": "Бот работает!"})

async def telegram_webhook_handler(request: web.Request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.error(f"Ошибка обработки обновления: {e}")
    return web.Response(text="ok")

async def on_startup(app):
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        logging.error("WEBHOOK_URL не задан в переменных окружения")
        return
    await bot.set_webhook(webhook_url)
    logging.info(f"Webhook установлен на {webhook_url}")

async def on_cleanup(app):
    await bot.delete_webhook()
    await bot.session.close()

def setup_web_app():
    app = web.Application()
    app.router.add_post("/yookassa-webhook", yookassa_webhook_handler)
    app.router.add_post("/webhook", telegram_webhook_handler)
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
