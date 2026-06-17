"""Импорт прайса МКС (мкс.xlsx) — основной каталог.

Структура: Раздел / Группа / Подгруппа / Артикул / Наименование / Бренд / Новинка /
           ... / Остатки / Ед. изм. / Цена / РРЦ / МРЦ / Штрих-код

Создаётся 3-уровневое дерево категорий (parent-child), товары
кладутся в листовую подгруппу. Цена берётся из РРЦ (если есть),
иначе из «Цена, тг». Если «Новинка» = «Да» — флаг `_is_new` в имени
(использовать на сайте необязательно — мы используем `created_at`).

Запуск:
    python manage.py import_mks
    python manage.py import_mks --file "C:\\Users\\QazTool\\Downloads\\мкс.xlsx"
"""
import os
from decimal import Decimal

import openpyxl
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from shop.models import Category, Product

DEFAULT_FILE = os.path.join(
    os.path.expanduser('~'), 'Downloads', 'мкс.xlsx')


def _slug(name, existing):
    base = slugify(name, allow_unicode=True) or 'cat'
    slug, n = base, 2
    while slug in existing:
        slug = f'{base}-{n}'
        n += 1
    existing.add(slug)
    return slug


def _price(value):
    if value is None:
        return None
    try:
        d = Decimal(str(value).replace(',', '.').replace(' ', ''))
        if d <= 0:
            return None
        # отбрасываем дробные копейки
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


class Command(BaseCommand):
    help = 'Импорт прайс-листа МКС со полным деревом категорий.'

    def add_arguments(self, parser):
        parser.add_argument('--file', default=DEFAULT_FILE,
                            help='Путь к мкс.xlsx')
        parser.add_argument('--limit', type=int, default=0,
                            help='Ограничить N товаров для теста.')

    def handle(self, *args, **opts):
        path = opts['file']
        if not os.path.exists(path):
            self.stdout.write(self.style.ERROR(f'Файл не найден: {path}'))
            return

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header = next(rows)
        self.stdout.write(f'Заголовок: {[str(c) for c in header[:4]]}')

        # Кэш существующих категорий для дедупликации.
        existing_slugs = set(Category.objects.values_list('slug', flat=True))
        cat_cache = {}    # (parent_id|None, name) -> Category

        def get_or_make_cat(name, parent=None):
            key = (parent.pk if parent else None, name.strip())
            if key in cat_cache:
                return cat_cache[key]
            cat = Category.objects.filter(parent=parent, name=name).first()
            if cat is None:
                cat = Category.objects.create(
                    name=name[:200], slug=_slug(name, existing_slugs),
                    parent=parent)
            cat_cache[key] = cat
            return cat

        to_create = []
        seen_articles = set()
        i = added = skipped = 0
        for row in rows:
            i += 1
            if opts['limit'] and added >= opts['limit']:
                break
            section, group, subgroup, article, name, brand, novinka, *_rest = row
            if not name or not article:
                skipped += 1
                continue
            article = str(article).strip()
            if article in seen_articles:
                continue
            # цена: РРЦ (column 13), иначе «Цена, тг» (column 12)
            price = _price(row[13]) or _price(row[12])
            if price is None:
                skipped += 1
                continue

            cat_section = get_or_make_cat(str(section).strip()) if section else None
            cat_group = get_or_make_cat(str(group).strip(), cat_section) if (group and cat_section) else cat_section
            cat_sub = get_or_make_cat(str(subgroup).strip(), cat_group) if (subgroup and cat_group) else cat_group
            target = cat_sub or cat_group or cat_section
            if target is None:
                skipped += 1
                continue

            p = Product(
                category=target,
                name=str(name)[:500],
                brand=(str(brand or '').strip())[:200],
                article=article[:200],
                price=price,
                in_stock=_stock(row[10]),
            )
            to_create.append(p)
            seen_articles.add(article)
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
            f'Готово. Прочитано: {i}, добавлено: {added}, пропущено: {skipped}.'))
        self.stdout.write(
            f'Категорий всего: {Category.objects.count()} '
            f'(верхний уровень: {Category.objects.filter(parent__isnull=True).count()}).')
