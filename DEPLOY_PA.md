# Деплой на PythonAnywhere

## 1. Залить код

В Bash-консоли PA:

```bash
cd ~
git clone https://github.com/psychodevvv/primetools.git magaz
cd magaz
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. Залить .env

```bash
cp .env.example .env
nano .env
```

В `.env` обязательно:
- `SECRET_KEY` — сгенерируй: `python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"`
- `DEBUG=False`
- `ALLOWED_HOSTS=твой-логин.pythonanywhere.com`

## 3. Залить базу с товарами

Локальный снапшот лежит в `db.snapshot.sqlite3` (207 МБ, был снят пока шёл скрейп).
На PA через вкладку **Files** загрузить его в `~/magaz/` и переименовать:

```bash
cd ~/magaz
mv db.snapshot.sqlite3 db.sqlite3
```

> На бесплатном тарифе PA лимит диска 512 МБ — 207 МБ влезает, но впритык.
> Если не хватает места, удали `venv/` после установки колёс, либо переходи на
> платный план.

## 4. Миграции и статика

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

(Создать суперюзера, если нужен админ-доступ:
`python manage.py createsuperuser`)

## 5. Web app

Вкладка **Web** → **Add a new web app** → **Manual configuration** → Python 3.13.

- **Source code:** `/home/<логин>/magaz`
- **Working directory:** `/home/<логин>/magaz`
- **Virtualenv:** `/home/<логин>/magaz/venv`
- **WSGI file:** в редакторе заменить содержимое на:

```python
import os, sys
from pathlib import Path

BASE = Path('/home/<логин>/magaz')
sys.path.insert(0, str(BASE))

# Подгрузить .env вручную (PA не загружает его сам)
from dotenv import load_dotenv  # либо просто прописать переменные ниже
# Если не ставить python-dotenv — раскомментируй блок из .env как os.environ[…].

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tool_shop.settings')
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Альтернатива без `python-dotenv` — указать переменные в разделе **Environment variables** на вкладке Web.

## 6. Static / Media маппинг

На вкладке **Web** → **Static files**:

| URL       | Directory                              |
|-----------|----------------------------------------|
| `/static/`| `/home/<логин>/magaz/staticfiles`      |
| `/media/` | `/home/<логин>/magaz/media`            |

## 7. Reload и проверка

Нажать **Reload** на вкладке Web. Открыть `https://<логин>.pythonanywhere.com`.

---

## Обновление БД после полного скрейпа

Когда локальный Lamed-скрейп закончится, на хосте сделать снапшот:

```bash
python -c "import sqlite3; s=sqlite3.connect('db.sqlite3'); d=sqlite3.connect('db.snapshot.sqlite3'); s.backup(d); d.close()"
```

Залить `db.snapshot.sqlite3` на PA через Files, переименовать в `db.sqlite3`, нажать **Reload**.
