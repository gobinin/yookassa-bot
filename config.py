import os
import json
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHOP_ID = os.getenv("SHOP_ID")
SECRET_KEY = os.getenv("SECRET_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 3000))

# По умолчанию — берем из переменной ADMIN_IDS (comma-separated)
ADMIN_IDS = os.getenv("ADMIN_IDS", "")  # строка "123,456"
ADMINS_FILE = os.getenv("ADMINS_FILE", "admins.json")

def _parse_default_admins():
    s = ADMIN_IDS.strip()
    if not s:
        return []
    parts = [p.strip() for p in s.split(",") if p.strip()]
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except:
            continue
    return result

DEFAULT_ADMINS = _parse_default_admins()

def load_admins():
    """Возвращает список admin_id (int). Если admins.json есть — загружает, иначе возвращает DEFAULT_ADMINS."""
    if os.path.exists(ADMINS_FILE):
        try:
            with open(ADMINS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [int(x) for x in data]
        except Exception:
            pass
    # если файла нет или он плохой — создадим файл с DEFAULT_ADMINS
    try:
        with open(ADMINS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_ADMINS, f)
    except Exception:
        pass
    return DEFAULT_ADMINS.copy()

def save_admins(admins):
    """Сохраняет список админов (list of int) в ADMINS_FILE."""
    try:
        with open(ADMINS_FILE, "w", encoding="utf-8") as f:
            json.dump([int(x) for x in admins], f)
        return True
    except Exception:
        return False