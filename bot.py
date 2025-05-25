
import asyncio
import logging
import uuid
import requests
from aiogram import Bot, Dispatcher, Router, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, SHOP_ID, SECRET_KEY

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()

products = {
    "bot_course": {"name": "Курс: Как создать бота", "price": 199},
    "pdf_guide": {"name": "PDF-инструкция", "price": 99},
    "combo": {"name": "Пакет: Курс + Гайд", "price": 249},
}

def product_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{v['name']} – {v['price']}₽", callback_data=k)]
        for k, v in products.items()
    ])
    return kb

@router.message(CommandStart())
@router.message()
async def greet_user(message: Message):
    logging.info(f"Received message: {message.text}")
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
        payment_url = response.json()["confirmation"]["confirmation_url"]
        await callback.message.answer(
            f"🔗 Ссылка для оплаты <b>{product['name']}</b> на {product['price']}₽:\n{payment_url}"
        )
        await callback.answer()
    else:
        await callback.message.answer("❌ Ошибка при создании оплаты. Попробуйте позже.")
        await callback.answer()

dp.include_router(router)

async def main():
    logging.info("Bot is polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())