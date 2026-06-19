"""Импорт прайса BCM (!2026 NEW_BCM_Distr_price_list.xlsx).

Структура: Артикул | Фото | Наименование | Описание+характеристики |
           (новинка) | Кол-во | Ваша цена со скидкой | РРЦ | Сумма заказа

Все товары падают в одну верхнюю категорию «BCM» (или указанную в --cat),
с автоматическим распределением по новинкам.

Запуск:
    python manage.py import_bcm
    python manage.py import_bcm --file "C:\\...\\!2026 NEW_BCM_Distr_price_list.xlsx"
"""
import os
from decimal import Decimal

import openpyxl
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from shop.models import Category, Product

DEFAULT_FILE = os.path.join(
    os.path.expanduser('~'), 'Downloads', '!2026 NEW_BCM_Distr_price_list.xlsx')


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


def _get_or_make(name, parent=None):
    cat = Category.objects.filter(name=name, parent=parent).first()
    if cat:
        return cat
    base = slugify(name, allow_unicode=True) or 'cat'
    slug, n = base, 2
    while Category.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'; n += 1
    return Category.objects.create(name=name[:200], slug=slug, parent=parent)


class Command(BaseCommand):
    help = 'Импорт прайса BCM в общую категорию.'

    def add_arguments(self, parser):
        parser.add_argument('--file', default=DEFAULT_FILE)
        parser.add_argument('--top', default='Аккумуляторный инструмент BCM',
                            help='Имя верхней категории.')

    def handle(self, *args, **opts):
        path = opts['file']
        if not os.path.exists(path):
            self.stdout.write(self.style.ERROR(f'Файл не найден: {path}'))
            return

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))

        # шапка на строке 1 (индекс 1)
        header_idx = 1
        data_rows = rows[header_idx + 1:]

        top = _get_or_make(opts['top'])
        sub_news = _get_or_make('Новинки', parent=top)

        to_create = []
        seen = set()
        added = skipped = 0
        for r in data_rows:
            if not r or len(r) < 4:
                continue
            article = r[0]
            name = r[2]
            desc = r[3] or ''
            novinka = (r[4] or '')
            qty = r[5]
            price_sale = _price(r[6])
            price_rrc = _price(r[7])
            if not name or not article:
                continue
            article = str(article).strip()
            if article in seen:
                continue
            price = price_sale or price_rrc
            if price is None:
                skipped += 1
                continue
            cat = sub_news if 'новинк' in str(novinka).lower() else top
            p = Product(
                category=cat,
                name=str(name).strip()[:500],
                brand='BCM',
                article=article[:200],
                description=str(desc).strip()[:6000],
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
            f'BCM: добавлено {added}, пропущено {skipped} (без цены или имени).'))
