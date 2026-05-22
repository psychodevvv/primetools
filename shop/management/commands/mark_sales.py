"""Помечает часть товаров как «на распродаже» — для блока «РАСПРОДАЖА».

Случайно отбирает заданный процент товаров с фото и проставляет
им old_price = price * (1 + скидка). Скидка в диапазоне 10–35%.

Запуск:  python manage.py mark_sales            (10% товаров)
         python manage.py mark_sales --pct 15
         python manage.py mark_sales --reset    (сбросить все распродажи)
"""
import random
from decimal import Decimal

from django.core.management.base import BaseCommand

from shop.models import Product


class Command(BaseCommand):
    help = 'Случайно помечает товары как «на распродаже».'

    def add_arguments(self, parser):
        parser.add_argument('--pct', type=int, default=10,
                            help='Процент товаров на распродаже (по умолчанию 10).')
        parser.add_argument('--reset', action='store_true',
                            help='Сбросить old_price у всех товаров.')

    def handle(self, *args, **options):
        if options['reset']:
            n = Product.objects.exclude(old_price__isnull=True).update(old_price=None)
            self.stdout.write(self.style.SUCCESS(f'Сброшено: {n}.'))
            return

        pct = max(1, min(60, options['pct']))
        Product.objects.update(old_price=None)

        pks = list(Product.objects
                   .exclude(image_url='')
                   .values_list('pk', flat=True))
        random.seed(42)
        random.shuffle(pks)
        target = pks[:len(pks) * pct // 100]
        self.stdout.write(f'Помечаем {len(target)} из {len(pks)} товаров с фото.')

        for start in range(0, len(target), 500):
            chunk = list(Product.objects.filter(pk__in=target[start:start + 500]))
            for p in chunk:
                # скидка 10–35%
                disc = Decimal(random.choice(['1.12', '1.18', '1.25', '1.33']))
                p.old_price = (p.price * disc).quantize(Decimal('0.01'))
            Product.objects.bulk_update(chunk, ['old_price'])

        on_sale = Product.objects.exclude(old_price__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(
            f'Готово. На распродаже сейчас: {on_sale}.'))
