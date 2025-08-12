import logging
import uuid
import os
import asyncio
import re
import requests
import json
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart, Command, Text
from config import BOT_TOKEN, SHOP_ID, SECRET_KEY, WEBHOOK_URL, PORT, load_admins, save_admins

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# --- ПРОДУКТЫ (оставил твой цифровой товар как пример) ---
products = {
    "bot_course": {"name": "Скачать GTA 5", "price": 199.00},
}

download_links = {
    "bot_course": "https://disk.yandex.ru/i/7sMDMIoR9-Lhnw"
}

# данные для оплаты (как были)
user_data = {}  # для оплаты (old flow)
# данные для заказов доставки (новый поток)
order_data = {}  # {user_id: {"state": "await_contact"/"await_address"/"await_items", "phone":..., "address":..., "items":...}}

# Загрузка админов (из admins.json или DEFAULT_ADMINS)
ADMINS = load_admins()  # список int

def is_valid_phone(phone: str) -> bool:
    return re.match(r"^\+?\d{7,15}$", phone) is not None

def is_valid_email(email: str) -> bool:
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None

def product_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{v['name']} – {int(v['price'])}₽", callback_data=k)]
        for k, v in products.items()
    ])

def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Сделать заказ", callback_data="start_order")],
        [InlineKeyboardButton(text="💾 Магазин (цифровые товары)", callback_data="show_products")]
    ])

# клавиатура для отправки контакта (request_contact)
contact_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Отправить контакт", request_contact=True)]],
    resize_keyboard=True,
    one_time_keyboard=True
)

@router.message(CommandStart())
async def greet_user(message: Message):
    await message.answer(
        "👋 Привет! Добро пожаловать в сервис доставки нашего магазина.\n\n"
        "Мы делаем всё просто: оформляете заказ — курьер привозит.\n\n"
        "Нажмите кнопку ниже, чтобы начать.",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    data = callback.data or ""
    if data == "start_order":
        # инициируем поток заказа
        uid = callback.from_user.id
        order_data[uid] = {"state": "await_contact", "phone": None, "address": None, "items": None}
        await callback.message.answer(
            "📝 Отлично — начнём оформление заказа.\n\n"
            "Нам потребуется ваш номер телефона (чтобы курьер мог связаться).",
            reply_markup=contact_keyboard
        )
        await callback.answer()
        return

    if data == "show_products":
        await callback.message.answer(
            "💾 Наш магазин цифровых товаров. Выберите товар:",
            reply_markup=product_keyboard()
        )
        await callback.answer()
        return

    # иначе считаем, что это product_id (старый поток оплаты)
    product_id = data
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
    return

@router.message()
async def general_message_handler(message: Message):
    uid = message.from_user.id
    text = (message.text or "").strip()

    # ---------- 1) Обработка заказов (новый поток) ----------
    if uid in order_data:
        state = order_data[uid]["state"]

        # 1.1 ожидание контакта
        if state == "await_contact":
            # если пришёл контакт (кнопка)
            if message.contact and message.contact.phone_number:
                phone = message.contact.phone_number
            else:
                # если просто текст — принимаем как номер, если валидный
                if is_valid_phone(text):
                    phone = text
                else:
                    await message.answer("❗ Пожалуйста, отправьте контакт через кнопку или введите номер в формате +7999XXXXXXX.")
                    return
            order_data[uid]["phone"] = phone
            order_data[uid]["state"] = "await_address"
            await message.answer("📍 Отлично! Пришлите, пожалуйста, адрес доставки (улица, дом, подъезд, этаж).", reply_markup=ReplyKeyboardRemove())
            return

        # 1.2 ожидание адреса
        if state == "await_address":
            if not text:
                await message.answer("❗ Введите адрес текстом.")
                return
            order_data[uid]["address"] = text
            order_data[uid]["state"] = "await_items"
            await message.answer("🛒 Теперь пришлите список товаров (пример: хлеб, молоко, яйца). Укажите максимально подробно.")
            return

        # 1.3 ожидание списка товаров
        if state == "await_items":
            if not text:
                await message.answer("❗ Введите список товаров текстом.")
                return
            order_data[uid]["items"] = text

            # Сформируем сообщение подтверждения и отправим всем админам
            user = message.from_user
            user_name = f"{user.full_name}" if user.full_name else f"User {uid}"
            username = f"@{user.username}" if user.username else "—"

            order_text = (
                f"📬 <b>Новый заказ</b>\n\n"
                f"👤 Клиент: {user_name} ({username})\n"
                f"🆔 UserID: <code>{uid}</code>\n"
                f"📱 Телефон: {order_data[uid]['phone']}\n"
                f"📍 Адрес: {order_data[uid]['address']}\n"
                f"🛍 Список товаров:\n{order_data[uid]['items']}\n\n"
                "— Отвечать клиенту можно прямо в Telegram (нажать на ник/номер)."
            )

            # отправляем всем админам
            admins_now = load_admins()
            if not admins_now:
                await message.answer("❗ Заказ сформирован, но нет доступных администраторов для отправки. Свяжитесь с владельцем.")
            else:
                for admin_id in admins_now:
                    try:
                        await bot.send_message(admin_id, order_text)
                    except Exception as e:
                        logging.error(f"Ошибка отправки заказа админу {admin_id}: {e}")

                await message.answer("✅ Спасибо! Ваш заказ отправлен. Скоро с вами свяжется курьер.")
            # завершаем
            del order_data[uid]
            return

    # ---------- 2) Обработка старого потока оплаты (если пользователь начал покупку цифрового товара) ----------
    # Если пользователь в процессе покупки (user_data есть и email ещё не задан)
    if uid in user_data and user_data[uid].get("email") is None:
        contact = text
        if is_valid_email(contact):
            contact_type = "email"
        elif is_valid_phone(contact):
            contact_type = "phone"
        else:
            await message.answer("❌ Введите корректный email или номер телефона (пример: user@example.com или +79991234567).")
            return

        user_data[uid]["email"] = contact
        product_id = user_data[uid]["product_id"]
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
            "description": f"{uid}:{product_id}",
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

        return

    # ---------- 3) Остальные сообщения (не в потоке) ----------
    # Можно отвечать или игнорировать
    # Например: подсказка меню
    if text:
        await message.answer("Чтобы оформить заказ — нажмите /start и затем кнопку «Сделать заказ».")
    return

# --- YooKassa webhook (оставил как было) ---
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

# --- Команды админа: add/del/list ---
@router.message(Command("addadmin"))
async def add_admin_handler(message: Message):
    from_user = message.from_user.id
    admins_now = load_admins()
    if from_user not in admins_now:
        await message.reply("❌ Только администратор может добавлять новых админов.")
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply("Использование: /addadmin <user_id>\nПример: /addadmin 123456789")
        return
    try:
        new_id = int(parts[1])
    except:
        await message.reply("Неверный ID. Это должно быть число.")
        return
    if new_id in admins_now:
        await message.reply("Этот пользователь уже в списке администраторов.")
        return
    admins_now.append(new_id)
    if save_admins(admins_now):
        await message.reply(f"✅ Админ {new_id} добавлен.")
    else:
        await message.reply("❌ Ошибка при сохранении списка админов.")

@router.message(Command("deladmin"))
async def del_admin_handler(message: Message):
    from_user = message.from_user.id
    admins_now = load_admins()
    if from_user not in admins_now:
        await message.reply("❌ Только администратор может удалять админов.")
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply("Использование: /deladmin <user_id>\nПример: /deladmin 123456789")
        return
    try:
        rem_id = int(parts[1])
    except:
        await message.reply("Неверный ID. Это должно быть число.")
        return
    if rem_id not in admins_now:
        await message.reply("Этот пользователь не найден в списке админов.")
        return
    admins_now = [a for a in admins_now if a != rem_id]
    if save_admins(admins_now):
        await message.reply(f"✅ Админ {rem_id} удалён.")
    else:
        await message.reply("❌ Ошибка при сохранении списка админов.")

@router.message(Command("admins"))
async def list_admins(message: Message):
    admins_now = load_admins()
    if not admins_now:
        await message.reply("Список админов пуст.")
        return
    await message.reply("Список админов:\n" + "\n".join([str(x) for x in admins_now]))

# --- Веб-сервер и запуск ---
async def on_startup(app):
    webhook_url = os.getenv("WEBHOOK_URL") or WEBHOOK_URL
    if not webhook_url:
        logging.error("❗ WEBHOOK_URL не задан")
        return
    try:
        await bot.set_webhook(webhook_url)
        logging.info(f"✅ Webhook установлен: {webhook_url}")
    except Exception as e:
        logging.error(f"Не удалось установить webhook: {e}")

async def on_cleanup(app):
    try:
        await bot.delete_webhook()
    except:
        pass
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
    port = int(os.getenv("PORT", PORT))
    app = setup_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"🚀 Сервер запущен на порту {port}")
    while True:
        await asyncio.sleep(3600)

if _name_ == "_main_":
    asyncio.run(main())