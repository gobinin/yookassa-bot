import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env-файла
load_dotenv()

# Получаем значения переменных
BOT_TOKEN = os.getenv("BOT_TOKEN")
SHOP_ID = str(os.getenv("SHOP_ID"))
SECRET_KEY = os.getenv("SECRET_KEY")