import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import Command
import os
from dotenv import load_dotenv

# Загружаем токен
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Настройка логов
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- Указываем ID админа напрямую ---
ADMIN_IDS = [5112853993]  # твой ID

# Состояния для FSM
class OrderStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()
    waiting_for_items = State()

# Данные заказов
order_data = {}

# --- Главное меню ---
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📦 Сделать заказ")],
        [KeyboardButton(text="ℹ О нас")]
    ],
    resize_keyboard=True
)

# --- Старт ---
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Привет 👋 Я бот для приема заказов!\nВыберите действие:", reply_markup=main_kb)

# --- Кнопка "О нас" ---
@dp.message(lambda msg: msg.text == "ℹ О нас")
async def about(message: types.Message):
    await message.answer("Мы принимаем ваши заказы через Telegram. 🚀")

# --- Начало заказа ---
@dp.message(lambda msg: msg.text == "📦 Сделать заказ")
async def make_order(message: types.Message, state: FSMContext):
    await message.answer("Введите ваше имя:")
    await state.set_state(OrderStates.waiting_for_name)

# --- Имя ---
@dp.message(OrderStates.waiting_for_name)
async def get_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите адрес доставки:")
    await state.set_state(OrderStates.waiting_for_address)

# --- Адрес ---
@dp.message(OrderStates.waiting_for_address)
async def get_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    await message.answer("Напишите список товаров (через запятую):")
    await state.set_state(OrderStates.waiting_for_items)

# --- Список товаров и отправка админу ---
@dp.message(OrderStates.waiting_for_items)
async def get_items(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()

    name = data.get("name")
    address = data.get("address")
    items = message.text

    order_text = (
        f"📦 Новый заказ!\n\n"
        f"👤 Имя: {name}\n"
        f"📍 Адрес: {address}\n"
        f"🛒 Товары: {items}\n\n"
        f"Telegram ID заказчика: {user_id}"
    )

    # Отправляем админу
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, order_text)
        except Exception as e:
            logging.error(f"Ошибка отправки админу {admin_id}: {e}")

    await message.answer("✅ Спасибо! Ваш заказ отправлен. Скоро с вами свяжется курьер.", reply_markup=main_kb)
    await state.clear()

# --- Запуск ---
async def main():
    await dp.start_polling(bot)

if _name_ == "_main_":
    asyncio.run(main())