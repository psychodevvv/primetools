"""Импорт прайса Tulex (tulex.xlsx).

Файл — плоский список товаров, отсортированный по брендам.
Берём ТОЛЬКО: электроинструменты, тачки/тележки, бетономесители, генераторы.
Фильтр — по ключевым словам в названии.

Запуск:
    python manage.py import_tulex
    python manage.py import_tulex --file "C:\\Users\\QazTool\\Downloads\\tulex.xlsx"
"""
import os
from decimal import Decimal

import openpyxl
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from shop.models import Category, Product

DEFAULT_FILE = os.path.join(
    os.path.expanduser('~'), 'Downloads', 'tulex.xlsx')

# Категория → список ключевых слов в названии товара (lower).
CATEGORY_KEYWORDS = [
    ('Электроинструменты', [
        'дрель', 'шуруповёрт', 'шуруповерт', 'перфоратор', 'болгарка',
        'ушм', 'углошлифов', 'лобзик', 'фрезер', 'электрорубанок', 'рубанок',
        'циркулярн', 'пила дисков', 'дисковая пила', 'гравер', 'штроборез',
        'отбойный молоток', 'строит. миксер', 'строительный миксер',
        'плиткорез электр', 'паяльник', 'термофен', 'технический фен',
        'гайковёрт', 'гайковерт', 'миксер строительн', 'аккум. дрель',
        'аккум. шурупов', 'аккум. гайков', 'аккум. болгар', 'аккум. лобзик',
    ]),
    ('Тачки и тележки', [
        'тачка', 'тележк', 'тачки', 'тележки', 'строительная тачка',
        'садовая тачка', 'грузовая тележк', 'ручная тележк',
    ]),
    ('Бетономесители', [
        'бетономеш', 'бетоносмесит', 'растворомеш',
    ]),
    ('Генераторы', [
        'генератор', 'электростанц', 'бензогенератор', 'инверторный генератор',
    ]),
]

# Минимальный отступ продукта в столбце B (Ценовая группа/Номенклатура)
PROD_INDENT = 16


def _price(value):
    if value in (None, ''):
        return None
    try:
        d = Decimal(str(value).replace(',', '.').replace(' ', ''))
        if d <= 0:
            return None
        return d.quantize(Decimal('1.'))
    except Exception:
        return None


def _stock(value):
    if value in (None, ''):
        return True
    try:
        return float(str(value).replace(',', '.')) > 0
    except Exception:
        return True


def _classify(name):
    n = (name or '').lower()
    for cat_name, kws in CATEGORY_KEYWORDS:
        for k in kws:
            if k in n:
                return cat_name
    return None


def _get_or_make(name, parent=None):
    cat = Category.objects.filter(name=name, parent=parent).first()
    if cat:
        return cat
    base = slugify(name, allow_unicode=True) or 'cat'
    slug, n = base, 2
    while Category.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'; n += 1
    return Category.objects.create(name=name[:200], slug=slug, parent=parent)


def _indent(s):
    if not s:
        return 0
    s = str(s)
    return len(s) - len(s.lstrip(' '))


class Command(BaseCommand):
    help = 'Импорт Tulex — только электроинструменты, тачки/тележки, бетономесители, генераторы.'

    def add_arguments(self, parser):
        parser.add_argument('--file', default=DEFAULT_FILE)

    def handle(self, *args, **opts):
        path = opts['file']
        if not os.path.exists(path):
            self.stdout.write(self.style.ERROR(f'Файл не найден: {path}'))
            return

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))

        # Шапка ищется автоматически: первая строка где есть «Ценовая группа»
        header_idx = 9
        for i, r in enumerate(rows[:25]):
            if r and any('Ценовая группа' in str(c or '') for c in r):
                header_idx = i; break

        cat_cache = {}
        def cat_for(name):
            if name not in cat_cache:
                cat_cache[name] = _get_or_make(name)
            return cat_cache[name]

        brand = ''
        to_create = []
        seen = set()
        added = filtered = skipped = 0

        for r in rows[header_idx + 1:]:
            if not r or len(r) < 8:
                continue
            label = r[1]
            if label is None or str(label).strip() == '':
                continue
            indent = _indent(label)
            text = str(label).strip()

            # это запись бренда (без числовых полей в правой части)
            if indent < PROD_INDENT:
                # 12 пробелов = название бренда; <12 — служебные «Товары», «РАБОЧАЯ»
                if indent == 12:
                    brand = text
                continue

            # это товар (indent >= 16)
            cat_name = _classify(text)
            if cat_name is None:
                filtered += 1
                continue

            # Цена — столбец 8 (Алмата)
            price = _price(r[8] if len(r) > 8 else None)
            if price is None:
                # пробуем 9 как РРЦ
                price = _price(r[9] if len(r) > 9 else None)
            if price is None:
                skipped += 1
                continue

            # барк-код может быть в столбце 4, артикул — в 7
            article = (str(r[7]).strip() if len(r) > 7 and r[7] else '')
            if not article:
                article = text[:60].replace(' ', '_')
            if article in seen:
                continue

            qty = r[3] if len(r) > 3 else None
            full_desc = str(r[5]).strip() if len(r) > 5 and r[5] else ''

            p = Product(
                category=cat_for(cat_name),
                name=(full_desc or text)[:500],
                brand=brand[:200],
                article=article[:200],
                price=price,
                in_stock=_stock(qty),
            )
            to_create.append(p)
            seen.add(article)
            added += 1
            if len(to_create) >= 500:
                with transaction.atomic():
                    Product.objects.bulk_create(to_create, batch_size=500)
                to_create.clear()

        if to_create:
            with transaction.atomic():
                Product.objects.bulk_create(to_create, batch_size=500)
        wb.close()
        self.stdout.write(self.style.SUCCESS(
            f'Tulex: добавлено {added}, отфильтровано {filtered} (не подходящих категорий), '
            f'пропущено {skipped} (без цены).'))
