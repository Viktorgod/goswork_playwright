import asyncio
import os
import json
from datetime import datetime, date

from aiogram import Bot
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID_ENV = os.getenv("CHAT_ID")
ORBITA_LOGIN = os.getenv("ORBITA_LOGIN")
ORBITA_PASSWORD = os.getenv("ORBITA_PASSWORD")
PLAN_DAY = float(os.getenv("PLAN_DAY", "2000"))

CHECK_INTERVAL = 3600  # 1 час
BASE_DIR = "/data"  # постоянное хранилище Railway
HISTORY_FILE = os.path.join(BASE_DIR, "last.json")


def validate_env():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN not set")
    if not CHAT_ID_ENV:
        raise RuntimeError("CHAT_ID not set")
    try:
        chat_id_int = int(CHAT_ID_ENV)
    except ValueError:
        raise RuntimeError("CHAT_ID must be int")
    return chat_id_int


CHAT_ID = validate_env()


def ensure_storage():
    """Создаём /data если нет."""
    os.makedirs(BASE_DIR, exist_ok=True)


def save_last(values: dict):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False)


def load_last() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def backup_history():
    """Бэкап last.json → last_YYYY-MM-DD.json"""
    if not os.path.exists(HISTORY_FILE):
        return
    today = datetime.now().strftime("%Y-%m-%d")
    backup_file = os.path.join(BASE_DIR, f"last_{today}.json")
    if not os.path.exists(backup_file):
        with open(HISTORY_FILE, "r", encoding="utf-8") as src, open(
            backup_file, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())


def reset_daily():
    """Ежедневный сброс данных в 00:00"""
    save_last({})
    backup_history()


def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1600,900")
    return webdriver.Chrome(options=options)


def find_today_column(table):
    today_str = f"{datetime.now().day:02d}"
    rows = table.find_elements(By.TAG_NAME, "tr")
    for row in rows:
        ths = row.find_elements(By.TAG_NAME, "th")
        for idx, th in enumerate(ths):
            aria = th.get_attribute("aria-label") or ""
            txt = th.text.strip()
            if aria.startswith(today_str + ":") or txt == today_str:
                return idx
    return None


def parse_balance_table(driver):
    now = datetime.now()
    today_str = f"{now.day:02d}"
    month_str = f"{now.month:02d}"

    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.TAG_NAME, "table"))
    )
    table = driver.find_element(By.TAG_NAME, "table")
    today_col = find_today_column(table)
    if today_col is None:
        return f"❌ Column for {today_str}.{month_str} not found", {}

    rows = table.find_elements(By.TAG_NAME, "tr")
    pairs = []

    for row in rows:
        ths = row.find_elements(By.TAG_NAME, "th")
        if not ths:
            continue
        name = ths[0].text.strip().replace("\n", " ")
        lname = name.lower()
        if (
            not name
            or "всего" in lname
            or "итого" in lname
            or "администратор" in lname
            or name[0].isdigit()
            or len(name.split()) < 2
        ):
            continue

        tds = row.find_elements(By.TAG_NAME, "td")
        if len(tds) <= today_col:
            continue

        value = tds[today_col].text.strip() or "0"
        try:
            num_value = float(value.replace(",", "."))
        except:
            num_value = 0.0

        pairs.append((name, num_value))

    if not pairs:
        return f"No data for {today_str}.{month_str}", {}

    pairs.sort(key=lambda x: x[1], reverse=True)
    total = sum(val for _, val in pairs)

    # Общее отображение
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"📊 Баланс за {today_str}.{month_str}\n"]
    for i, (name, val) in enumerate(pairs):
        medal = medals[i] if i < 3 else "▫️"
        lines.append(f"{medal} {name:<20} — {val}")

    return "\n".join(lines), dict(pairs), total


async def main():
    ensure_storage()
    bot = Bot(token=TELEGRAM_TOKEN)
    last_date = date.today()

    try:
        while True:
            now = datetime.now()

            # Сброс в 00:00
            if date.today() != last_date:
                reset_daily()
                last_date = date.today()

            try:
                balance_text, current_values, total = login_and_get_balance_text()

                last_values = load_last()
                growth_lines = []
                sum_growth = 0

                for name, val in current_values.items():
                    old = last_values.get(name, val)
                    diff = round(val - old, 2)
                    sum_growth += diff
                    if diff > 0:
                        growth_lines.append(f"📈 {name}: +{diff}")
                    elif diff < 0:
                        growth_lines.append(f"📉 {name}: {diff}")
                    else:
                        growth_lines.append(f"⏸ {name}: 0")

                save_last(current_values)

                now_str = now.strftime("%Y-%m-%d %H:%M:%S")
                full_text = (
                    f"⏰ Обновление ORBITA ({now_str})\n\n"
                    f"{balance_text}\n\n"
                    "📊 Прирост за час:\n" + "\n".join(growth_lines) +
                    f"\n\n📈 Общий прирост за час: {sum_growth}"
                )

                await bot.send_message(CHAT_ID, full_text)

            except Exception as e:
                await bot.send_message(CHAT_ID, f"❌ Error:\n{e}")

            await asyncio.sleep(CHECK_INTERVAL)

    finally:
        await bot.session.close()
