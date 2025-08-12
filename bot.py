# bot.py — ЧИСТЫЙ БОТ ДЛЯ ПРИЁМА ЗАКАЗОВ (без YooKassa)
import os
import json
import logging
import asyncio
import re

from aiohttp import web
from aiogram import Bot, Dispatcher, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart, Command

# --- Настройка логов ---
logging.basicConfig(level=logging.INFO)

# --- Конфиг: читаем из config.py или из окружения ---
try:
    # если у тебя есть config.py — он может содержать BOT_TOKEN, WEBHOOK_URL, PORT
    from config import BOT_TOKEN, WEBHOOK_URL, PORT, ADMINS_FILE, ADMIN_IDS
except Exception:
    # fallback — читаем из окружения
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    try:
        PORT = int(os.getenv("PORT", 3000))
    except:
        PORT = 3000
    ADMINS_FILE = os.getenv("ADMINS_FILE", "admins.json")
    ADMIN_IDS = os.getenv("ADMIN_IDS", "")  # строка "123,456"

# --- Утилиты для админов ---
def parse_default_admins(admins_str: str):
    out = []
    if not admins_str:
        return out
    for part in admins_str.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except:
            continue
    return out

DEFAULT_ADMINS = parse_default_admins(ADMIN_IDS if 'ADMIN_IDS' in globals() else "")

if 'ADMINS_FILE' not in globals():
    ADMINS_FILE = "admins.json"

def load_admins():
    """Возвращает список админов (list[int]). Если файл есть — загружает, иначе создаёт и возвращает DEFAULT_ADMINS."""
    if os.path.exists(ADMINS_FILE):
        try:
            with open(ADMINS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [int(x) for x in data]
        except Exception as e:
            logging.warning(f"Не удалось прочитать {ADMINS_FILE}: {e}")
    # создать файл с default
    try:
        with open(ADMINS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_ADMINS, f)
    except Exception:
        pass
    return DEFAULT_ADMINS.copy()

def save_admins(admins):
    try:
        with open(ADMINS_FILE, "w", encoding="utf-8") as f:
            json.dump([int(x) for x in admins], f)
        return True
    except Exception as e:
        logging.error(f"Ошибка записи admins: {e}")
        return False

# --- Проверки формата телефона ---
PHONE_RE = re.compile(r"^\+?\d{7,15}$")
def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone.strip()))

# --- Инициализация бота и диспетчера ---
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# --- Простое меню ---
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

# Временное хранилище состояний пользователей (в памяти)
order_data = {}  # {user_id: {"state": "await_contact"/"await_address"/"await_items", "phone":..., "address":..., "items":...}}

# --- Команды /start ---
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Это бот доставки вашего магазина.\n\n"
        "Удобно оформляйте заказ — курьер привезёт всё к вам.",
        reply_markup=main_menu_keyboard()
    )

# --- Обработка нажатий на inline-кнопки ---
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

# --- Главный обработчик текстов/контактов ---
@router.message()
async def messages_handler(message: Message):
    uid = message.from_user.id
    text = (message.text or "").strip()

    # если пользователь в процессе заказа
    if uid in order_data:
        state = order_data[uid].get("state")

        # 1) ожидание контакта
        if state == "await_contact":
            phone = None
            # если пришёл контакт через кнопку
            if message.contact and message.contact.phone_number:
                phone = message.contact.phone_number
            else:
                # если текст — пробуем валидировать как телефон
                if text and is_valid_phone(text):
                    phone = text
                else:
                    await message.answer("❗ Пожалуйста, отправьте контакт через кнопку или введите номер в формате +79991234567.")
                    return
            order_data[uid]["phone"] = phone
            order_data[uid]["state"] = "await_address"
            await message.answer("📍 Отлично. Теперь напишите адрес доставки (улица, дом, подъезд, этаж).", reply_markup=ReplyKeyboardRemove())
            return

        # 2) ожидание адреса
        if state == "await_address":
            if not text:
                await message.answer("❗ Введите адрес текстом (например: ул. Ленина, д. 15, кв. 3, подъезд 2).")
                return
            order_data[uid]["address"] = text
            order_data[uid]["state"] = "await_items"
            await message.answer("🛒 Напишите список товаров (пример: хлеб, молоко, яйца). Указывайте подробно.")
            return

        # 3) ожидание списка товаров
        if state == "await_items":
            if not text:
                await message.answer("❗ Введите список товаров текстом.")
                return
            order_data[uid]["items"] = text

            # Формируем сообщение для админов
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
                "— Ответить клиенту можно прямо в Telegram (нажать на ник/номер)."
            )

            admins_now = load_admins()
            if not admins_now:
                await message.answer("✅ Заказ принят, но пока нет администраторов для отправки. Владелец должен добавить ваш ID в ADMIN_IDS.")
            else:
                send_errors = False
                for admin_id in admins_now:
                    try:
                        await bot.send_message(admin_id, order_text)
                    except Exception as e:
                        logging.error(f"Ошибка отправки админу {admin_id}: {e}")
                        send_errors = True

                if send_errors:
                    await message.answer("⚠ Ваш заказ принят, но возникли ошибки при отправке админам. Попробуйте позже.")
                else:
                    await message.answer("✅ Спасибо! Ваш заказ отправлен. Скоро с вами свяжется курьер.")

            # удаляем состояние
            order_data.pop(uid, None)
            return

    # если сообщение не в потоке — даём подсказку
    if text:
        await message.answer("Чтобы оформить заказ — нажмите /start и затем кнопку «Сделать заказ».")

# --- Команды админов: add/del/list ---
@router.message(Command("addadmin"))
async def cmd_addadmin(message: Message):
    caller = message.from_user.id
    admins_now = load_admins()
    if caller not in admins_now:
        await message.reply("❌ Только существующий админ может добавлять новых админов.")
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply("Использование: /addadmin <user_id>\nПример: /addadmin 123456789")
        return
    try:
        new_id = int(parts[1])
    except:
        await message.reply("Неверный ID — должно быть число.")
        return
    if new_id in admins_now:
        await message.reply("Этот пользователь уже админ.")
        return
    admins_now.append(new_id)
    if save_admins(admins_now):
        await message.reply(f"✅ Админ {new_id} добавлен.")
    else:
        await message.reply("❌ Ошибка при сохранении списка админов.")

@router.message(Command("deladmin"))
async def cmd_deladmin(message: Message):
    caller = message.from_user.id
    admins_now = load_admins()
    if caller not in admins_now:
        await message.reply("❌ Только админ может удалять админов.")
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply("Использование: /deladmin <user_id>")
        return
    try:
        rem_id = int(parts[1])
    except:
        await message.reply("Неверный ID.")
        return
    if rem_id not in admins_now:
        await message.reply("Этот пользователь не в списке админов.")
        return
    admins_now = [a for a in admins_now if a != rem_id]
    if save_admins(admins_now):
        await message.reply(f"✅ Админ {rem_id} удалён.")
    else:
        await message.reply("❌ Ошибка при сохранении списка админов.")

@router.message(Command("admins"))
async def cmd_list_admins(message: Message):
    admins_now = load_admins()
    if not admins_now:
        await message.reply("Список админов пуст.")
        return
    await message.reply("Список админов:\n" + "\n".join([str(x) for x in admins_now]))

# --- Webhook / сервер (для Render) ---
async def telegram_webhook_handler(request: web.Request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.error(f"Ошибка при обработке Telegram-обновления: {e}")
    return web.Response(text="ok")

async def root_handler(request):
    return web.json_response({"status":"ok","message":"bot running"})

async def on_startup(app):
    webhook = os.getenv("WEBHOOK_URL") or (WEBHOOK_URL if 'WEBHOOK_URL' in globals() else None)
    if webhook:
        try:
            await bot.set_webhook(webhook)
            logging.info(f"Webhook установлен: {webhook}")
        except Exception as e:
            logging.error(f"Не удалось установить webhook: {e}")
    else:
        logging.info("WEBHOOK_URL не указан — бот ожидает обновлений (можно использовать long-polling локально)")

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
    port = int(os.getenv("PORT", PORT if 'PORT' in globals() else 3000))
    app = setup_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Server started on port {port}")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())