"""Создаёт записи Brand для слайдера на главной (название + лого).

Берёт qaztool-бренды (если есть БД qaztool рядом) и плюсом добавляет ещё
популярные бренды из текущего каталога PrimeTools.

Запуск:  python manage.py seed_brands
"""
import os
import sqlite3

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from shop.models import Brand, Product


QAZTOOL_DB = r'C:\Users\QazTool\Desktop\qaztoolsite\db.sqlite3'

# Резервные логотипы (Wikimedia / производители) — на случай если qaztool
# недоступен или не охватывает бренд из нашего каталога.
EXTRA_LOGOS = {
    'BOSCH':    'https://upload.wikimedia.org/wikipedia/commons/thumb/4/46/Bosch-logo.svg/2560px-Bosch-logo.svg.png',
    'METABO':   'https://upload.wikimedia.org/wikipedia/commons/thumb/4/4a/Metabo_Logo.svg/2560px-Metabo_Logo.svg.png',
    'DEWALT':   'https://upload.wikimedia.org/wikipedia/commons/thumb/8/89/DeWalt_Logo.svg/2560px-DeWalt_Logo.svg.png',
    'MAKITA':   'https://upload.wikimedia.org/wikipedia/commons/thumb/7/71/Makita_Logo.svg/2560px-Makita_Logo.svg.png',
    'MILWAUKEE':'https://upload.wikimedia.org/wikipedia/commons/thumb/d/de/Milwaukee_Logo.svg/2560px-Milwaukee_Logo.svg.png',
    'HITACHI':  'https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Hitachi_inspire_the_next_logo.svg/2560px-Hitachi_inspire_the_next_logo.svg.png',
    'STAYER':   'https://www.stayer-instrument.ru/image/catalog/stayer_logo.png',
    'KRAFTOOL': 'https://www.instrument18.ru/upload/iblock/3e3/3e3f728e3d3cb876a81a9582d7341185.png',
    'ЗУБР':     'https://upload.wikimedia.org/wikipedia/commons/thumb/f/fb/%D0%9B%D0%BE%D0%B3%D0%BE%D1%82%D0%B8%D0%BF_%D0%97%D0%A3%D0%91%D0%A0.png/640px-%D0%9B%D0%BE%D0%B3%D0%BE%D1%82%D0%B8%D0%BF_%D0%97%D0%A3%D0%91%D0%A0.png',
    'YATO':     'https://yato.kz/upload/medialibrary/3df/3df8a9b96e3b8d3e7e3f73a0e76b5f1b.png',
    'TOPTUL':   'https://www.toptul.com/site/images/logo.png',
    'FUBAG':    'https://fubag.ru/local/templates/fubag_v2/assets/img/logo.svg',
    'FISKARS':  'https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Fiskars_logo.svg/2560px-Fiskars_logo.svg.png',
    'GARDENA':  'https://upload.wikimedia.org/wikipedia/commons/thumb/f/fc/Logo_Gardena.svg/2560px-Logo_Gardena.svg.png',
    'WORTEX':   'https://wortex.ru/upload/iblock/d0e/wortex.png',
    'SPARTA':   'https://www.gross.ru/local/templates/.default/img/sparta-logo.png',
    'TEKHMASH': 'https://tehmash.kz/upload/iblock/abc/abc-tehmash.png',
}


class Command(BaseCommand):
    help = 'Создаёт записи Brand с логотипами (для слайдера на главной).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Удалить все существующие бренды перед сидингом.')

    def handle(self, *args, **options):
        if options['reset']:
            Brand.objects.all().delete()
            self.stdout.write('Прежние записи удалены.')

        existing = {b.name.upper(): b for b in Brand.objects.all()}
        created = updated = 0

        # 1) qaztool, если есть БД
        if os.path.exists(QAZTOOL_DB):
            con = sqlite3.connect(QAZTOOL_DB)
            for r in con.execute(
                'SELECT name, logo_url, website, "order" FROM shop_brand '
                "WHERE COALESCE(logo_url,'') != ''"
            ):
                name, logo_url, website, order = r
                key = (name or '').upper().strip()
                if not key:
                    continue
                b = existing.get(key)
                if b is None:
                    b = Brand(name=name[:100], slug=self._slug(name))
                    existing[key] = b
                    created += 1
                else:
                    updated += 1
                b.logo_url = logo_url or b.logo_url
                b.website = website or b.website
                b.order = order or b.order
                b.featured = True
                b.save()
            con.close()
            self.stdout.write(self.style.SUCCESS('Из qaztool добавлено/обновлено.'))

        # 2) популярные бренды каталога PrimeTools
        top_names = list(
            Product.objects.exclude(brand='')
            .values_list('brand', flat=True).distinct()[:60]
        )
        for raw in top_names:
            name = (raw or '').strip()
            if not name:
                continue
            key = name.upper()
            b = existing.get(key)
            if b is None:
                b = Brand(name=name[:100], slug=self._slug(name))
                existing[key] = b
                created += 1
            if not b.logo_src and EXTRA_LOGOS.get(key):
                b.logo_url = EXTRA_LOGOS[key]
                updated += 1
            b.featured = True
            b.save()

        with_logo = Brand.objects.exclude(
            logo_url='').filter(featured=True).count() + \
            Brand.objects.exclude(logo='').filter(featured=True).count()
        self.stdout.write(self.style.SUCCESS(
            f'Готово. Брендов всего: {Brand.objects.count()}, '
            f'с логотипом: {with_logo}, добавлено: {created}, обновлено: {updated}.'))

    def _slug(self, name):
        base = slugify(name, allow_unicode=True) or 'brand'
        slug, n = base, 2
        while Brand.objects.filter(slug=slug).exists():
            slug = f'{base}-{n}'
            n += 1
        return slug
