"""Нормализация дерева категорий.

1. Объединяет очевидные дубли top-level («Электроинструмент» / «Электроинструменты»,
   «Сад и огород» / «Все для сада» / «Dom i sad» и т.п.) — переносит детей
   и товары к canonical, удаляет alias.
2. Удаляет пустые top-level (без товаров и без потомков с товарами).
3. Сжимает глубину дерева до 3: для категорий уровня ≥4 переносит детей-листьев
   (с товарами) на уровень 3 (как подгруппы группы).

Запуск:
    python manage.py normalize_categories
    python manage.py normalize_categories --dry-run
"""
from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils.text import slugify

from shop.models import Category, Product


# Canonical → варианты, которые должны схлопнуться в этот canonical.
# Сравнение по lower-имени, без пробелов и кириллицы/латиницы тонкостей.
MERGE_GROUPS = [
    ('Электроинструменты', [
        'электроинструменты', 'электроинструмент', 'elektroinstrument',
        'механизированные инструменты',
    ]),
    ('Ручной инструмент', [
        'ручной инструмент', 'ручные инструменты', 'ruchnoj instrument',
        'ruchnoy instrument', 'расходные инструменты',
    ]),
    ('Сад и огород', [
        'сад и огород', 'все для сада', 'dom i sad', 'дом и сад',
        'садовая техника', 'садовый инструмент',
        'садовый инструмент, вазоны, горшки и кашпо, теплицы, парники',
        'садовая техника, инвентарь и материалы',
    ]),
    ('Крепёж', [
        'крепёж', 'крепеж', 'крепежные материалы', 'крепежные изделия',
    ]),
    ('Сварочное оборудование', [
        'сварочное оборудование и принадлежности',
        'сварочное оборудование и материалы',
        'сварочное оборудование', 'svarochnoe oborudovanie',
    ]),
    ('Измерительный инструмент', [
        'измерительный инструмент', 'измерительные инструменты',
        'izmeritelnyj instrument',
    ]),
    ('Электрика и свет', [
        'электрика и свет', 'электрика', 'свет',
    ]),
    ('Химия, крепёж, СИЗ', [
        'химия, крепеж, сиз', 'химия, крепёж, сиз',
        'строительная химия и принадлежности', 'строительная химия',
    ]),
    ('Малярные инструменты', [
        'малярно-штукатурные инструменты', 'малярные инструменты',
        'малярно штукатурные инструменты',
    ]),
    ('Хозтовары', [
        'хозяйственные принадлежности', 'товары для дома', 'хозтовары',
        'инвентарь',
    ]),
    ('Все для уборки', [
        'все для уборки', 'товары для уборки',
    ]),
    ('Тачки и тележки', [
        'тачки и тележки',
    ]),
    ('Оборудование', [
        'оборудование', 'oborudovanie',
    ]),
    ('Автотовары', [
        'автотовары', 'avtotovary', 'автоинструмент',
    ]),
    ('Инженерная сантехника', [
        'инженерная сантехника и инструменты', 'сантехника',
    ]),
    ('Бетономесители', [
        'бетономесители',
    ]),
    ('Электрогенераторы', [
        'электрогенераторы и аксессуары', 'генераторы', 'силовая техника',
    ]),
    ('Расходные материалы', [
        'расходные материалы', 'расходники',
    ]),
    ('Строительные материалы', [
        'строительные материалы', 'стройматериалы', 'строительное оборудование',
    ]),
    ('Аккумуляторный инструмент BCM', [
        'аккумуляторный инструмент bcm',
    ]),
]


def norm(s):
    return ' '.join((s or '').strip().lower().split())


def _category_depth(c):
    d = 1; p = c
    while p.parent_id:
        d += 1
        p = p.parent
    return d


def _all_descendants(cat):
    out = []
    for ch in cat.children.all():
        out.append(ch)
        out.extend(_all_descendants(ch))
    return out


def _ensure_unique_slug(base):
    slug = slugify(base, allow_unicode=True) or 'cat'
    if not Category.objects.filter(slug=slug).exists():
        return slug
    n = 2
    while Category.objects.filter(slug=f'{slug}-{n}').exists():
        n += 1
    return f'{slug}-{n}'


class Command(BaseCommand):
    help = 'Объединить дубли категорий, очистить пустые, сжать глубину до 3.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Только показать что будет сделано.')

    @transaction.atomic
    def handle(self, *args, **opts):
        dry = opts['dry_run']
        self.stdout.write('=== Шаг 1: объединение дублей top-level ===')

        # alias-name (norm) → canonical name
        alias_map = {}
        for canon, aliases in MERGE_GROUPS:
            for a in aliases:
                alias_map[norm(a)] = canon

        # все top-level + по имени
        existing_by_name = {}
        for c in Category.objects.filter(parent__isnull=True):
            existing_by_name.setdefault(norm(c.name), []).append(c)

        merged_count = 0
        for canon_name, aliases in MERGE_GROUPS:
            # canonical из БД, если есть — берём первого
            canon = (Category.objects.filter(parent__isnull=True,
                                             name__iexact=canon_name).first())
            if not canon:
                if dry:
                    self.stdout.write(f'  (создал бы) canonical: {canon_name}')
                    continue
                canon = Category.objects.create(
                    name=canon_name, slug=_ensure_unique_slug(canon_name))
            # все алиасы, которые уже есть в БД и не равны canonical
            for alias_norm in {norm(a) for a in aliases}:
                if alias_norm == norm(canon.name):
                    continue
                for cat in existing_by_name.get(alias_norm, []):
                    if cat.pk == canon.pk:
                        continue
                    if dry:
                        self.stdout.write(
                            f'  → "{cat.name}" → "{canon.name}"')
                        continue
                    # переносим детей
                    cat.children.update(parent=canon)
                    # переносим товары
                    Product.objects.filter(category=cat).update(category=canon)
                    cat.delete()
                    merged_count += 1
        self.stdout.write(f'  объединено: {merged_count}')

        # === Шаг 2: удаление пустых top-level ===
        self.stdout.write('=== Шаг 2: удаление пустых top-level ===')
        removed_empty = 0
        for c in list(Category.objects.filter(parent__isnull=True)):
            ids = c.descendant_ids()
            cnt = Product.objects.filter(category_id__in=ids).count()
            if cnt == 0:
                if dry:
                    self.stdout.write(f'  (удалил бы) {c.name}')
                else:
                    c.delete()
                    removed_empty += 1
        self.stdout.write(f'  удалено пустых: {removed_empty}')

        # === Шаг 3: сжатие глубины до 3 ===
        self.stdout.write('=== Шаг 3: сжатие глубины до 3 ===')
        flattened = 0
        # Берём категории с глубиной ≥4 и переносим их на глубину 3:
        # дед-родитель становится новым родителем.
        deep = [c for c in Category.objects.all() if _category_depth(c) >= 4]
        # сортируем по уменьшению глубины, чтобы сначала схлопнуть самые глубокие
        deep.sort(key=lambda c: -_category_depth(c))
        for c in deep:
            if _category_depth(c) < 4:
                continue
            # лезем вверх до уровня 3 (3-уровневая иерархия)
            target_parent = c.parent
            while _category_depth(target_parent) > 2:
                target_parent = target_parent.parent
            if dry:
                self.stdout.write(
                    f'  (поднял бы) {c.name} → под "{target_parent.name}"')
                continue
            c.parent = target_parent
            c.save(update_fields=['parent'])
            flattened += 1
        self.stdout.write(f'  поднято: {flattened}')

        # финальная сводка
        from collections import Counter
        ck = Counter()
        for c in Category.objects.all():
            ck[_category_depth(c)] += 1
        self.stdout.write('\nИтоговая глубина дерева:')
        for d in sorted(ck):
            self.stdout.write(f'  depth {d}: {ck[d]} категорий')
        self.stdout.write(f'\nВсего категорий: {Category.objects.count()}')
        self.stdout.write(f'Top-level:        '
                          f'{Category.objects.filter(parent__isnull=True).count()}')

        if dry:
            self.stdout.write(self.style.WARNING(
                'DRY-RUN — изменения откачены (transaction).'))
            transaction.set_rollback(True)
        else:
            self.stdout.write(self.style.SUCCESS('Нормализация завершена.'))
