import asyncio
import os
import json
from datetime import datetime

from aiogram import Bot
from playwright.sync_api import sync_playwright

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID_ENV = os.getenv("CHAT_ID")
ORBITA_LOGIN = os.getenv("ORBITA_LOGIN")
ORBITA_PASSWORD = os.getenv("ORBITA_PASSWORD")
PLAN_DAY = float(os.getenv("PLAN_DAY", "2000"))

CHECK_INTERVAL = 3600  # секунды
HISTORY_FILE = "last.json"


def validate_env() -> int:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN not set")
    if not CHAT_ID_ENV:
        raise RuntimeError("CHAT_ID not set")
    try:
        chat_id_int = int(CHAT_ID_ENV)
    except ValueError:
        raise RuntimeError("CHAT_ID must be int")
    if not ORBITA_LOGIN or not ORBITA_PASSWORD:
        raise RuntimeError("ORBITA_LOGIN or ORBITA_PASSWORD missing")
    return chat_id_int


CHAT_ID = validate_env()


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


# ------------------------------------------------------------
# Парсинг через Playwright
# ------------------------------------------------------------


def _find_today_column(table):
    today_str = f"{datetime.now().day:02d}"
    rows = table.query_selector_all("tr")
    for row in rows:
        ths = row.query_selector_all("th")
        for idx, th in enumerate(ths):
            aria = th.get_attribute("aria-label") or ""
            txt = (th.inner_text() or "").strip()
            if aria.startswith(today_str + ":") or txt == today_str:
                return idx
    return None


def _parse_balance_table(page):
    now = datetime.now()
    today_str = f"{now.day:02d}"
    month_str = f"{now.month:02d}"

    page.wait_for_selector("table")
    table = page.query_selector("table")
    if table is None:
        return f"No table for {today_str}.{month_str}", {}

    today_col = _find_today_column(table)
    if today_col is None:
        return f"❌ Column for {today_str}.{month_str} not found", {}

    rows = table.query_selector_all("tr")
    pairs = []

    for row in rows:
        ths = row.query_selector_all("th")
        if not ths:
            continue
        name = (ths[0].inner_text() or "").strip()
        if not name:
            continue
        lname = name.lower()
        if (
            "всего" in lname
            or "итого" in lname
            or "администратор" in lname
            or name[0].isdigit()
            or len(name.split()) < 2
        ):
            continue
        tds = row.query_selector_all("td")
        if len(tds) <= (today_col or 0):
            continue
        value = (tds[today_col].inner_text() or "").strip() or "0"
        try:
            num_value = float(value.replace(",", ".").replace(" ", ""))
        except Exception:
            num_value = 0.0
        pairs.append((name, num_value))

    if not pairs:
        return f"No data for {today_str}.{month_str}", {}

    pairs.sort(key=lambda x: x[1], reverse=True)
    total = sum(val for _, val in pairs)

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"📊 Баланс за {today_str}.{month_str}\n"]

    for i, (name, val) in enumerate(pairs):
        medal = medals[i] if i < 3 else "▫️"
        lines.append(f"{medal} {name:<20} — {val}")

    lines.append(f"\n💰 Итого: {total}")

    return "\n".join(lines), {name: val for name, val in pairs}


def _parse_admin_actions(page):
    """Возвращает dict {админ: суммарно_действий_за_сегодня}"""
    today = datetime.today().strftime("%Y-%m-%d")
    page.fill("input[name='period']", f"{today} - {today}")

    # выбираем метрику "Сгенерировано действий"
    try:
        page.select_option("select[name='metric']", label="Сгенерировано действий")
    except Exception:
        sel = page.query_selector("select[name='metric']")
        if sel:
            options = sel.query_selector_all("option")
            for opt in options:
                text = (opt.inner_text() or "").strip()
                if "Сгенерировано действий" in text:
                    value = opt.get_attribute("value")
                    if value:
                        sel.select_option(value)
                    break

    page.click("button:has-text('Поиск')")

    page.wait_for_selector("table tbody tr")
    rows = page.query_selector_all("table tbody tr")

    admins = {}
    for row in rows:
        cols = row.query_selector_all("td")
        if len(cols) < 4:
            continue
        admin = (cols[2].inner_text() or "").strip()
        actions24 = (cols[3].inner_text() or "").strip()
        if not admin:
            continue
        try:
            num = float(actions24.replace(",", ".").replace(" ", ""))
        except Exception:
            num = 0.0
        admins[admin] = admins.get(admin, 0.0) + num

    return admins


def fetch_data_with_playwright():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://orbita.life/login", wait_until="networkidle")
        page.fill("input[type='email'], input[name='email'], input[name='login']", ORBITA_LOGIN)
        page.fill("input[type='password'], input[name='password']", ORBITA_PASSWORD)
        page.click("button[type='submit'], button.btn-primary")
        page.wait_for_timeout(2000)
        page.wait_for_load_state("networkidle")

        page.goto("https://orbita.life", wait_until="networkidle")
        balance_text, balance_values = _parse_balance_table(page)

        page.goto("https://orbita.life/statistics/efficiency/operators/", wait_until="networkidle")
        admins_actions = _parse_admin_actions(page)

        browser.close()

    combined = {
        "balance": balance_values,
        "admins": admins_actions,
    }
    return balance_text, combined


async def send_long(bot: Bot, chat_id: int, text: str):
    if len(text) <= 4000:
        await bot.send_message(chat_id, text)
        return
    for i in range(0, len(text), 4000):
        await bot.send_message(chat_id, text[i : i + 4000])


async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        while True:
            try:
                loop = asyncio.get_running_loop()
                balance_text, combined_data = await loop.run_in_executor(
                    None, fetch_data_with_playwright
                )

                last_values = load_last()
                last_balances = last_values.get("balance", {})
                last_admins = last_values.get("admins", {})

                total_balance_diff = 0.0
                for name, val in combined_data["balance"].items():
                    old = last_balances.get(name, val)
                    total_balance_diff += round(val - old, 2)

                total_actions_diff = 0.0
                for admin, val in combined_data["admins"].items():
                    old = last_admins.get(admin, val)
                    total_actions_diff += round(val - old, 2)

                save_last(combined_data)

                if total_balance_diff > 0:
                    total_balance_text = f"💰 Общий прирост баланса за час: +{total_balance_diff}"
                elif total_balance_diff < 0:
                    total_balance_text = f"💰 Общий спад баланса за час: {total_balance_diff}"
                else:
                    total_balance_text = "💰 Баланс без изменений за час"

                if total_actions_diff > 0:
                    total_actions_text = f"🕹 Общий прирост действий за час: +{total_actions_diff}"
                elif total_actions_diff < 0:
                    total_actions_text = f"🕹 Общий спад действий за час: {total_actions_diff}"
                else:
                    total_actions_text = "🕹 Действия без изменений за час"

                sorted_admins = sorted(
                    combined_data["admins"].items(),
                    key=lambda x: x[1],
                    reverse=True,
                )

                admins_lines = []
                for admin, total in sorted_admins:
                    old = last_admins.get(admin, total)
                    diff = round(total - old, 2)
                    admins_lines.append(f"{admin} — {total} ({diff:+})")

                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                full_text = (
                    f"⏰ Обновление ORBITA ({now_str})\n\n"
                    f"{total_balance_text}\n"
                    f"{total_actions_text}\n\n"
                    f"{balance_text}\n\n"
                    "🕹 Действия по администраторам (за сегодня):\n" + "\n".join(admins_lines)
                )

                await send_long(bot, CHAT_ID, full_text)

            except Exception as e:
                await bot.send_message(CHAT_ID, f"❌ Error:\n{e}")

            await asyncio.sleep(CHECK_INTERVAL)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
