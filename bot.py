import logging
import uuid
import os
import asyncio
import re
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
    "bot_course": {"name": "Курс: Как создать бота", "price": 199.00},
    "pdf_guide": {"name": "PDF-инструкция", "price": 99.00},
    "combo": {"name": "Пакет: Курс + Гайд", "price": 249.00},
}

# Ссылки для скачивания
download_links = {
    "bot_course": "https://disk.yandex.ru/i/7sMDMIoR9-Lhnw",
    "pdf_guide": "https://disk.yandex.ru/i/7sMDMIoR9-Lhnw",
    "combo": "https://disk.yandex.ru/i/7sMDMIoR9-Lhnw"
}

user_data = {}

def product_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{v['name']} – {int(v['price'])}₽", callback_data=k)]
        for k, v in products.items()
    ])

@router.message(CommandStart())
async def greet_user(message: Message):
    await message.answer(
        "👋 Привет! Это магазин цифровых товаров.\n"
        "Выберите товар для покупки:",
        reply_markup=product_keyboard()
    )

@router.callback_query()
async def product_chosen(callback: types.CallbackQuery):
    product_id = callback.data
    product = products.get(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    user_data[callback.from_user.id] = {"product_id": product_id, "email": None}
    await callback.message.answer(
        f"Вы выбрали <b>{product['name']}</b> за {int(product['price'])}₽.\n\n"
        "Введите ваш email или номер телефона для получения чека:\n\n"
        "Пример: user@example.com или +79991234567"
    )
    await callback.answer()

def is_valid_email(email: str) -> bool:
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None

def is_valid_phone(phone: str) -> bool:
    return re.match(r"^\+?\d{7,15}$", phone) is not None

@router.message()
async def receive_email_or_phone(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data or user_data[user_id]["email"] is not None:
        return

    contact = message.text.strip()
    if is_valid_email(contact):
        contact_type = "email"
    elif is_valid_phone(contact):
        contact_type = "phone"
    else:
        await message.answer("❌ Введите корректный email или номер телефона.")
        return

    user_data[user_id]["email"] = contact
    product_id = user_data[user_id]["product_id"]
    product = products[product_id]
    bot_info = await bot.get_me()

    receipt_customer = {contact_type: contact}

    payment_data = {
        "amount": {
            "value": f"{product['price']:.2f}",
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/{bot_info.username}"
        },
        "capture": True,
        "description": f"{user_id}:{product_id}",
        "receipt": {
            "customer": receipt_customer,
            "items": [
                {
                    "description": product["name"][:128],
                    "quantity": "1.00",
                    "amount": {
                        "value": f"{product['price']:.2f}",
                        "currency": "RUB"
                    },
                    "vat_code": 1
                }
            ],
            "tax_system_code": 1
        }
    }

    logging.info(f"Создаём платёж с данными: {payment_data}")

    response = requests.post(
        "https://api.yookassa.ru/v3/payments",
        json=payment_data,
        auth=(str(SHOP_ID), SECRET_KEY),
        headers={
            "Idempotence-Key": str(uuid.uuid4()),
            "Content-Type": "application/json"
        }
    )

    try:
        data = response.json()
    except Exception:
        data = {}

    if response.ok and "confirmation" in data:
        url = data["confirmation"]["confirmation_url"]
        pay_button = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=url)]
        ])
        await message.answer(
            f"🔗 Для оплаты <b>{product['name']}</b> на сумму {int(product['price'])}₽ нажмите кнопку ниже.\n\n"
            "После оплаты вы получите ссылку для скачивания.",
            reply_markup=pay_button
        )
    else:
        logging.error(f"❌ Ошибка от YooKassa: {response.status_code} — {response.text}")
        err_desc = data.get("description", "Нет описания ошибки")
        await message.answer(f"❌ Ошибка при создании оплаты:\n\n{err_desc}")

async def yookassa_webhook_handler(request):
    data = await request.json()
    logging.info(f"📩 Уведомление от YooKassa: {data}")

    event = data.get("event")
    obj = data.get("object", {})
    status = obj.get("status")
    description = obj.get("description", "")

    if event == "payment.succeeded" and status == "succeeded":
        try:
            user_id_str, product_id = description.split(":")
            user_id = int(user_id_str)
            product = products.get(product_id)
            if product:
                link = download_links.get(product_id)
                if link:
                    await bot.send_message(
                        user_id,
                        f"✅ Оплата прошла!\n\n📥 Вот ссылка для скачивания <b>{product['name']}</b>:\n\n{link}"
                    )
                else:
                    await bot.send_message(user_id, "✅ Оплата получена, но ссылка не найдена.")
            else:
                await bot.send_message(user_id, "✅ Оплата получена, но товар не найден.")
            user_data.pop(user_id, None)
        except Exception as e:
            logging.error(f"Ошибка при обработке платежа: {e}")
    return web.Response(text="ok")

async def root_handler(request):
    return web.json_response({"status": "ok", "message": "Бот работает!"})

async def telegram_webhook_handler(request: web.Request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.error(f"Ошибка при обработке Telegram-обновления: {e}")
    return web.Response(text="ok")

async def on_startup(app):
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        logging.error("❗ WEBHOOK_URL не задан")
        return
    await bot.set_webhook(webhook_url)
    logging.info(f"✅ Webhook установлен: {webhook_url}")

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
