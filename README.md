# Goswork ORBITA Bot (Playwright)

Бот для Telegram, который каждые 1 часа(ов):

- логинится в ORBITA через Playwright (chromium headless)
- собирает баланс по переводчикам с главной страницы
- считает прирост общего баланса за час
- заходит в "Статистика | КПД операторов"
- выбирает метрику "Сгенерировано действий"
- ставит период: сегодня — сегодня
- суммирует колонку "24" по администраторам
- считает прирост действий по администраторам за час
- отправляет отчёт в Telegram.

## Переменные окружения на Railway

Нужно задать в Settings → Variables:

- TELEGRAM_TOKEN — токен бота от @BotFather
- CHAT_ID — id чата/канала/группы, куда слать отчёт
- ORBITA_LOGIN — логин от orbita.life
- ORBITA_PASSWORD — пароль от orbita.life
- PLAN_DAY — план на день по балансу (например, 2000)

## Установка Playwright (важно)

Railway после установки зависимостей должен один раз скачать браузер Chromium.

Самый простой вариант — в Build команду поставить:

    pip install -r requirements.txt && python -m playwright install --with-deps chromium

## Запуск на Railway

Тип сервиса: Worker.

Команда запуска берётся из Procfile:

    python orbita_bot.py
