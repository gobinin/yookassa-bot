import os
from dotenv import load_dotenv

load_dotenv()  # загружает переменные из .env файла (если запускаешь локально)

BOT_TOKEN = os.getenv("8135011284:AAFfweFaH5SLJBbHBbjF8c820ck5cS0JRiA")
SHOP_ID = os.getenv("1089533")
SECRET_KEY = os.getenv("live_UPCft_ahWDxKs-4mNrJZ4OWoqAcYgOCdPwdtJu0RMO0")