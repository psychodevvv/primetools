"""Удаляет из каталога товары, загруженные из прайса «Прайс Алматы» (tssp.kz).

Для них нет надёжного источника фотографий, поэтому раздел убран из импорта.
Команда находит товары по названиям из xlsx-файла и удаляет их.

Запуск:  python manage.py purge_almaty
"""
import os

import openpyxl
from django.core.management.base import BaseCommand

from shop.models import Category, Product

ALMATY_FILE = os.path.join(
    os.path.expanduser('~'), 'Downloads', 'Прайс Алматы 13.05.2026 (1).xlsx')


class Command(BaseCommand):
    help = 'Удаляет товары из прайса «Прайс Алматы» (tssp.kz).'

    def handle(self, *args, **options):
        if not os.path.exists(ALMATY_FILE):
            self.stdout.write(self.style.ERROR(
                f'Файл не найден: {ALMATY_FILE}'))
            return

        wb = openpyxl.load_workbook(ALMATY_FILE, read_only=True, data_only=True)
        ws = wb.active
        names = set()
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue
            name = str(row[1]).strip()[:500] if row[1] else ''
            if name:
                names.add(name)
        wb.close()
        self.stdout.write(f'Названий в прайсе «Алматы»: {len(names)}')

        # Не трогаем электронику Al-Style — там возможны совпадения названий.
        skip_ids = []
        elec = Category.objects.filter(name='Электроника и гаджеты').first()
        if elec:
            skip_ids = elec.descendant_ids()

        names = list(names)
        deleted = 0
        for start in range(0, len(names), 400):
            chunk = names[start:start + 400]
            qs = Product.objects.filter(name__in=chunk)
            if skip_ids:
                qs = qs.exclude(category_id__in=skip_ids)
            n, _ = qs.delete()
            deleted += n

        self.stdout.write(self.style.SUCCESS(
            f'Удалено товаров: {deleted}. '
            f'Осталось в каталоге: {Product.objects.count()}.'))
