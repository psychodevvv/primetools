"""Первичная инициализация проекта: создаёт администратора.

Запуск:  python init_project.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tool_shop.settings')

import django
django.setup()

from adminpanel.models import AdminUser

print('=== Инициализация проекта ===\n')

USERNAME = 'admin'
PASSWORD = 'admin123'

if not AdminUser.objects.filter(username=USERNAME).exists():
    AdminUser.objects.create(
        username=USERNAME,
        password_hash=AdminUser.hash_password(PASSWORD),
    )
    print(f'Администратор создан: {USERNAME} / {PASSWORD}')
else:
    print(f'Администратор "{USERNAME}" уже существует.')

print('\n=== Готово ===')
print('Запуск сервера:  python manage.py runserver')
print('Сайт:            http://127.0.0.1:8000/')
print('Админ-панель:    http://127.0.0.1:8000/admin-panel/')
print('Каталог товаров загрузите через админку (Импорт каталога).')
