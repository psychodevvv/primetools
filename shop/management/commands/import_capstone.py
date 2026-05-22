"""Импорт прайса CAPSTONE («Прайс от 18.05.2026.xlsx»).

Структура файла:
  колонка 1 — подкатегория (Бокорезы, Бур по бетону, Болгарка и т.п.)
  колонка 3 — остаток, 5 — название, 7 — артикул, 8 — цена

Подкатегория из прайса становится подразделом, родитель определяется
классификатором по названию. Это нормализует структуру каталога.

Запуск:  python manage.py import_capstone
"""
import os

import openpyxl
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from shop.ai import classify
from shop.models import Category, Product

FILE = os.path.join(os.path.expanduser('~'), 'Downloads',
                    'Прайс от 18.05.2026.xlsx')
MISC = 'Прочий инструмент и оборудование'
HEADER_ROW = 9


def _make_category(name, parent=None):
    base = slugify(name, allow_unicode=True) or 'cat'
    slug, n = base, 2
    while Category.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return Category.objects.create(name=name[:200], slug=slug, parent=parent)


class Command(BaseCommand):
    help = 'Импортирует прайс CAPSTONE.'

    def handle(self, *args, **options):
        if not os.path.exists(FILE):
            self.stdout.write(self.style.ERROR(f'Файл не найден: {FILE}'))
            return

        wb = openpyxl.load_workbook(FILE, read_only=True, data_only=True)
        ws = wb.active

        # Кеш категорий: top-level по имени и (родитель, имя) для подкат.
        top = {c.name: c for c in Category.objects.filter(parent__isnull=True)}
        sub_cache = {}

        def get_subcategory(sub_name):
            sub_name = sub_name.strip()
            if not sub_name:
                return None
            parent_name = classify(sub_name) or MISC
            parent = top.get(parent_name)
            if parent is None:
                parent = _make_category(parent_name)
                top[parent_name] = parent
            key = (parent.pk, sub_name.lower())
            if key in sub_cache:
                return sub_cache[key]
            sub = (Category.objects
                   .filter(name__iexact=sub_name, parent=parent).first()
                   or _make_category(sub_name, parent=parent))
            sub_cache[key] = sub
            return sub

        existing = {p.name: p for p in Product.objects.all()}
        to_create, to_update = {}, {}

        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i <= HEADER_ROW:
                continue
            sub = str(row[1]).strip() if row[1] else ''
            name = str(row[5]).strip() if row[5] else ''
            try:
                price = float(str(row[8]).replace(',', '.').replace(' ', ''))
            except (TypeError, ValueError):
                price = 0
            if not name or price <= 0 or not sub:
                continue
            category = get_subcategory(sub)
            if not category:
                continue

            try:
                stock_val = int(float(str(row[3]).replace(' ', '') or 0))
            except (ValueError, TypeError):
                stock_val = 0

            fields = dict(
                category=category, brand='CAPSTONE',
                article=str(row[7]).strip()[:200] if row[7] else '',
                price=price, in_stock=stock_val > 0,
            )

            if name in existing:
                p = existing[name]
                for k, v in fields.items():
                    setattr(p, k, v)
                to_update[name] = p
            elif name not in to_create:
                to_create[name] = Product(name=name[:500], **fields)
        wb.close()

        with transaction.atomic():
            if to_create:
                Product.objects.bulk_create(
                    list(to_create.values()), batch_size=500)
            if to_update:
                Product.objects.bulk_update(
                    list(to_update.values()),
                    ['category', 'brand', 'article', 'price', 'in_stock'],
                    batch_size=500)

        self.stdout.write(self.style.SUCCESS(
            f'CAPSTONE: добавлено {len(to_create)}, обновлено {len(to_update)}. '
            f'Подкатегорий создано: {len(sub_cache)}.'))
