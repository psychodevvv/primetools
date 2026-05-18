# Развёртывание на PythonAnywhere

Пошаговая инструкция, чтобы выложить сайт и дать клиенту ссылку
вида `https://ВАШ_ЛОГИН.pythonanywhere.com`.

## 0. Что уже готово
- `db.sqlite3.gz` — сжатая база (14 МБ) со всеми товарами, фото и категориями.
- `requirements.txt` — список зависимостей.
- Настройки читаются из файла `.env` (через python-decouple).

## 1. Регистрация
1. Зайдите на https://www.pythonanywhere.com → **Pricing & signup**.
2. Создайте **Beginner account** — бесплатно.
3. Подтвердите e-mail.

## 2. Загрузка кода
Вариант А (рекомендуется) — через GitHub:
1. Создайте репозиторий на GitHub и запушьте проект
   (файлы `db.sqlite3`, `.env`, `venv/`, `staticfiles/` уже в `.gitignore`).

Вариант Б — без GitHub: упакуйте папку проекта в zip
(без `venv`, `db.sqlite3`, `staticfiles`) и загрузите через вкладку **Files**.

## 3. Bash-консоль на PythonAnywhere
Откройте **Consoles → Bash** и выполните:
```bash
git clone https://github.com/ВАШ_ЛОГИН/ВАШ_РЕПО.git magaz
cd magaz
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. База данных
1. Вкладка **Files** → зайдите в папку `magaz` → **Upload a file** →
   загрузите `db.sqlite3.gz`.
2. В Bash-консоли:
```bash
cd ~/magaz
gunzip db.sqlite3.gz
```

## 5. Файл .env
Вкладка **Files** → в папке `magaz` создайте файл `.env`:
```
SECRET_KEY=придумайте-длинную-случайную-строку
DEBUG=False
ALLOWED_HOSTS=ВАШ_ЛОГИН.pythonanywhere.com

CALL_NUMBER=+7 700 000 00 00
WHATSAPP_NUMBER=77000000000

TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=
SMS_API_KEY=
SMS_API_URL=
SMS_SENDER=
```

## 6. Создание веб-приложения
1. Вкладка **Web** → **Add a new web app**.
2. **Manual configuration** (не «Django»!) → **Python 3.13**.
3. В разделе **Virtualenv** укажите:
   `/home/ВАШ_ЛОГИН/magaz/venv`
4. В разделе **Code** → **Source code**: `/home/ВАШ_ЛОГИН/magaz`

## 7. WSGI-файл
В разделе **Code** нажмите на ссылку WSGI-файла и замените всё содержимое на:
```python
import os, sys

path = '/home/ВАШ_ЛОГИН/magaz'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'tool_shop.settings'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

## 8. Статика
В Bash-консоли:
```bash
cd ~/magaz
source venv/bin/activate
python manage.py collectstatic --noinput
```
Затем во вкладке **Web → Static files** добавьте:
- **URL:** `/static/`
- **Directory:** `/home/ВАШ_ЛОГИН/magaz/staticfiles`

## 9. Запуск
Нажмите зелёную кнопку **Reload** во вкладке Web.
Сайт откроется по адресу `https://ВАШ_ЛОГИН.pythonanywhere.com`.

Админка: `https://ВАШ_ЛОГИН.pythonanywhere.com/admin-panel/`
(логин `admin`, пароль `admin123` — **обязательно смените**).

## Важно про бесплатный тариф
- Раз в 3 месяца нужно зайти и нажать на вкладке **Web** кнопку
  «Run until 3 months from today», иначе сайт отключат.
- Фотографии товаров грузятся напрямую в браузере клиента с сайтов
  поставщиков — отображаются нормально.
- Уведомления в Telegram и отправка SMS-кодов с бесплатного тарифа
  могут не работать (ограничен исходящий интернет). Регистрация при этом
  работает в демо-режиме — код показывается прямо на экране.
- Места на диске — 512 МБ; проект с базой укладывается.

## Обновление сайта позже
```bash
cd ~/magaz
git pull
source venv/bin/activate
pip install -r requirements.txt
python manage.py collectstatic --noinput
```
Затем **Reload** во вкладке Web.
