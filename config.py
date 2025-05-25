import os
from dotenv import load_dotenv

load_dotenv()  # загружает переменные из .env файла (если запускаешь локально)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHOP_ID = os.getenv("SHOP_ID")
SECRET_KEY = os.getenv("SECRET_KEY")