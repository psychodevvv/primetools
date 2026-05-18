"""Приводит категории в порядок: убирает дубли и параллельные деревья.

Из-за импорта из разных прайсов возникли повторяющиеся категории
(«Крепёж»/«Крепеж», «Электрика и освещение»/«Электрика и свет» и т.п.)
и два параллельных дерева. Команда переносит все товары-инструменты в
единый набор категорий (по классификатору названий), а электронику
Al-Style оставляет в её разделе. Пустые категории удаляются.

Запуск:  python manage.py tidy_categories
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from shop.ai import CATEGORY_RULES, classify
from shop.models import Category, Product

MISC = 'Прочий инструмент и оборудование'
ELECTRONICS = 'Электроника и гаджеты'


class Command(BaseCommand):
    help = 'Убирает дубли категорий и сводит товары в единый набор разделов.'

    def handle(self, *args, **options):
        # Электронику Al-Style не трогаем — у неё свои разделы.
        elec = Category.objects.filter(
            name=ELECTRONICS, parent__isnull=True).first()
        elec_ids = set(elec.descendant_ids()) if elec else set()

        # Каноничные разделы инструмента (верхний уровень, без родителя).
        canon = {}
        for name in [c for c, _ in CATEGORY_RULES] + [MISC]:
            cat = (Category.objects
                   .filter(name=name, parent__isnull=True)
                   .order_by('pk').first())
            if cat is None:
                base = slugify(name, allow_unicode=True) or 'cat'
                slug, n = base, 2
                while Category.objects.filter(slug=slug).exists():
                    slug = f'{base}-{n}'
                    n += 1
                cat = Category.objects.create(name=name[:200], slug=slug)
            elif cat.parent_id is not None:
                cat.parent = None
                cat.save(update_fields=['parent'])
            canon[name] = cat

        # Переклассифицируем все товары-инструменты по названию.
        moved = 0
        batch = []
        qs = Product.objects.all()
        if elec_ids:
            qs = qs.exclude(category_id__in=elec_ids)
        for product in qs.only('pk', 'name', 'category_id').iterator():
            target = canon[classify(product.name) or MISC]
            if product.category_id != target.pk:
                product.category_id = target.pk
                batch.append(product)
                if len(batch) >= 500:
                    Product.objects.bulk_update(batch, ['category'])
                    moved += len(batch)
                    batch = []
        if batch:
            Product.objects.bulk_update(batch, ['category'])
            moved += len(batch)

        # Удаляем опустевшие категории (каскадом: листья -> родители).
        removed = 0
        while True:
            ids = list(Category.objects.filter(
                products__isnull=True, children__isnull=True
            ).exclude(pk__in=[c.pk for c in canon.values()])
              .values_list('pk', flat=True)[:400])
            if not ids:
                break
            Category.objects.filter(pk__in=ids).delete()
            removed += len(ids)

        total = Category.objects.count()
        top = Category.objects.filter(parent__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(
            f'Готово. Перемещено товаров: {moved}. Удалено категорий: {removed}. '
            f'Осталось категорий: {total} (верхнего уровня: {top}).'))
