"""Загружает фото, описания и характеристики для ВСЕХ товаров со ссылкой-источником.

Запуск:  python manage.py fetch_images
Опции:   --workers 32   (число параллельных потоков)
"""
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand
from django.db.models import Q

from shop.images import fetch_product_info
from shop.models import Product

CHUNK = 200


class Command(BaseCommand):
    help = 'Загружает фото, описания и характеристики для товаров со ссылкой-источником.'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=32,
                            help='Число параллельных потоков (по умолчанию 32).')
        parser.add_argument('--refresh', action='store_true',
                            help='Перезаписать уже заполненные фото/описания/характеристики.')

    def handle(self, *args, **options):
        workers = max(1, options['workers'])
        refresh = options['refresh']

        qs = Product.objects.exclude(source_url='')
        if not refresh:
            qs = qs.filter(Q(image_url='') | Q(description='') | Q(characteristics=''))
        pks = list(qs.values_list('pk', flat=True))
        total = len(pks)
        if not total:
            self.stdout.write('Нет товаров для обработки.')
            return

        self.stdout.write(f'Товаров для обработки: {total}. Потоков: {workers}.')
        done = got_image = got_desc = got_char = 0

        for start in range(0, total, CHUNK):
            batch = list(Product.objects.filter(pk__in=pks[start:start + CHUNK]))

            info = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for pk, data in pool.map(
                    lambda p: (p.pk, fetch_product_info(p.source_url)), batch
                ):
                    info[pk] = data

            to_update = []
            for product in batch:
                data = info.get(product.pk) or {}
                changed = False
                if (refresh or not product.image_url) and data.get('image'):
                    product.image_url = data['image']
                    got_image += 1
                    changed = True
                if (refresh or not product.description) and data.get('description'):
                    product.description = data['description']
                    got_desc += 1
                    changed = True
                if (refresh or not product.characteristics) and data.get('characteristics'):
                    product.characteristics = data['characteristics']
                    got_char += 1
                    changed = True
                if changed:
                    to_update.append(product)
            if to_update:
                Product.objects.bulk_update(
                    to_update, ['image_url', 'description', 'characteristics'])

            done += len(batch)
            self.stdout.write(
                f'  {done}/{total} — фото: {got_image}, описаний: {got_desc}, '
                f'характеристик: {got_char}'
            )

        self.stdout.write(self.style.SUCCESS(
            f'Готово. Обработано {done} — фото: {got_image}, описаний: {got_desc}, '
            f'характеристик: {got_char}.'
        ))
