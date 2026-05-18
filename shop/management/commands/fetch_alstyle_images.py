"""Загружает фото для товаров Al-Style (электроника) по артикулу с al-style.kz.

Запуск:  python manage.py fetch_alstyle_images
Опции:   --workers 24    (число параллельных потоков)
         --refresh       (перезаписать уже заданные фото)
"""
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand

from shop.images import fetch_alstyle_image
from shop.models import Category, Product

CHUNK = 200


class Command(BaseCommand):
    help = 'Загружает фото товаров Al-Style по артикулу с al-style.kz.'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=24)
        parser.add_argument('--refresh', action='store_true')

    def handle(self, *args, **options):
        workers = max(1, options['workers'])
        refresh = options['refresh']

        parent = Category.objects.filter(name='Электроника и гаджеты').first()
        if not parent:
            self.stdout.write('Категория Al-Style не найдена.')
            return

        qs = Product.objects.filter(category_id__in=parent.descendant_ids())
        qs = qs.exclude(article='')
        if not refresh:
            qs = qs.filter(image_url='')
        pks = list(qs.values_list('pk', flat=True))
        total = len(pks)
        if not total:
            self.stdout.write('Нет товаров для обработки.')
            return

        self.stdout.write(f'Товаров Al-Style для обработки: {total}. '
                          f'Потоков: {workers}.')
        done = got = 0
        for start in range(0, total, CHUNK):
            batch = list(Product.objects.filter(pk__in=pks[start:start + CHUNK]))
            images = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for pk, url in pool.map(
                    lambda p: (p.pk, fetch_alstyle_image(p.article)), batch
                ):
                    images[pk] = url

            to_update = []
            for product in batch:
                url = images.get(product.pk)
                if url and (refresh or not product.image_url):
                    product.image_url = url
                    to_update.append(product)
                    got += 1
            if to_update:
                Product.objects.bulk_update(to_update, ['image_url'])

            done += len(batch)
            self.stdout.write(f'  {done}/{total} — найдено фото: {got}')

        self.stdout.write(self.style.SUCCESS(
            f'Готово. Обработано {done}, фото загружено: {got}.'))
