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

# Логотипы. Проверяй через `manage.py verify_brand_logos` — битые удаляются,
# бренд тогда показывается как название. Wikimedia ссылки наиболее стабильны.
EXTRA_LOGOS = {
    # верифицированные Wikimedia URL (svg → png через /thumb/)
    'BOSCH':     'https://upload.wikimedia.org/wikipedia/commons/thumb/4/46/Bosch-logo.svg/2560px-Bosch-logo.svg.png',
    'METABO':    'https://upload.wikimedia.org/wikipedia/commons/thumb/c/cf/Metabo_logo.svg/2560px-Metabo_logo.svg.png',
    'DEWALT':    'https://upload.wikimedia.org/wikipedia/commons/thumb/8/89/DeWalt_Logo.svg/2560px-DeWalt_Logo.svg.png',
    'MAKITA':    'https://upload.wikimedia.org/wikipedia/commons/thumb/7/71/Makita_Logo.svg/2560px-Makita_Logo.svg.png',
    'MILWAUKEE': 'https://upload.wikimedia.org/wikipedia/commons/thumb/d/de/Milwaukee_Logo.svg/2560px-Milwaukee_Logo.svg.png',
    'HITACHI':   'https://upload.wikimedia.org/wikipedia/commons/thumb/2/25/Hitachi_inspire_the_next_logo.svg/2560px-Hitachi_inspire_the_next_logo.svg.png',
    'HIKOKI':    'https://upload.wikimedia.org/wikipedia/commons/thumb/d/de/HiKOKI_logo.svg/2560px-HiKOKI_logo.svg.png',
    'STIHL':     'https://upload.wikimedia.org/wikipedia/commons/thumb/c/cd/Stihl_logo.svg/2560px-Stihl_logo.svg.png',
    'HUSQVARNA': 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/9a/Husqvarna_AB_logo.svg/2560px-Husqvarna_AB_logo.svg.png',
    'FISKARS':   'https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Fiskars_logo.svg/2560px-Fiskars_logo.svg.png',
    'GARDENA':   'https://upload.wikimedia.org/wikipedia/commons/thumb/f/fc/Logo_Gardena.svg/2560px-Logo_Gardena.svg.png',
    'KARCHER':   'https://upload.wikimedia.org/wikipedia/commons/thumb/1/12/K%C3%A4rcher_Logo.svg/2560px-K%C3%A4rcher_Logo.svg.png',
    'KÄRCHER':   'https://upload.wikimedia.org/wikipedia/commons/thumb/1/12/K%C3%A4rcher_Logo.svg/2560px-K%C3%A4rcher_Logo.svg.png',
    'EINHELL':   'https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Einhell_logo.svg/2560px-Einhell_logo.svg.png',
    'BLACK+DECKER': 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Black_%26_Decker_Logo.svg/2560px-Black_%26_Decker_Logo.svg.png',
    'STANLEY':   'https://upload.wikimedia.org/wikipedia/commons/thumb/d/da/Stanley_Hand_Tools_logo.svg/2560px-Stanley_Hand_Tools_logo.svg.png',
    'AEG':       'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f2/AEG_logo.svg/2560px-AEG_logo.svg.png',
    'RYOBI':     'https://upload.wikimedia.org/wikipedia/commons/thumb/b/b6/Ryobi_logo.svg/2560px-Ryobi_logo.svg.png',
    'INTERSKOL': 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Logo_INTERSKOL.svg/2560px-Logo_INTERSKOL.svg.png',
    'ИНТЕРСКОЛ': 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Logo_INTERSKOL.svg/2560px-Logo_INTERSKOL.svg.png',
    'PATRIOT':   'https://upload.wikimedia.org/wikipedia/commons/thumb/3/3d/Patriot_logo.svg/2560px-Patriot_logo.svg.png',
    'KRESS':     'https://upload.wikimedia.org/wikipedia/commons/thumb/4/4c/Kress_logo.svg/2560px-Kress_logo.svg.png',
    'CRAFTSMAN': 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Craftsman_logo.svg/2560px-Craftsman_logo.svg.png',
    'WAGNER':    'https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/Wagner_Group_Logo.svg/2560px-Wagner_Group_Logo.svg.png',
    'SONY':      'https://upload.wikimedia.org/wikipedia/commons/thumb/c/ca/Sony_logo.svg/2560px-Sony_logo.svg.png',
    'SAMSUNG':   'https://upload.wikimedia.org/wikipedia/commons/thumb/2/24/Samsung_Logo.svg/2560px-Samsung_Logo.svg.png',
    'HUAWEI':    'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e8/Huawei_Standard_logo.svg/2560px-Huawei_Standard_logo.svg.png',
    'XIAOMI':    'https://upload.wikimedia.org/wikipedia/commons/thumb/0/06/Xiaomi_logo_%282021-%29.svg/2560px-Xiaomi_logo_%282021-%29.svg.png',
    'APPLE':     'https://upload.wikimedia.org/wikipedia/commons/thumb/f/fa/Apple_logo_black.svg/1024px-Apple_logo_black.svg.png',
    'HP':        'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ad/HP_logo_2008.svg/1024px-HP_logo_2008.svg.png',
    'CANON':     'https://upload.wikimedia.org/wikipedia/commons/thumb/4/4e/Canon_wordmark.svg/2560px-Canon_wordmark.svg.png',
    'PHILIPS':   'https://upload.wikimedia.org/wikipedia/commons/thumb/f/fd/Philips_logo_new.svg/2560px-Philips_logo_new.svg.png',
    'LG':        'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8b/LG_symbol.svg/2560px-LG_symbol.svg.png',
    'BRENNENSTUHL': 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/93/Brennenstuhl-Logo.svg/2560px-Brennenstuhl-Logo.svg.png',
    'OLFA':      'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/OLFA_Corporation_logo.svg/2560px-OLFA_Corporation_logo.svg.png',
    'KOBALT':    'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8c/Kobalt_Tools_logo.svg/2560px-Kobalt_Tools_logo.svg.png',
    'PROXXON':   'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Proxxon_Logo.svg/2560px-Proxxon_Logo.svg.png',
    'YATO':      'https://upload.wikimedia.org/wikipedia/commons/thumb/4/49/Yato_logo.svg/2560px-Yato_logo.svg.png',
    'KAPRO':     'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8c/Kapro_logo.svg/2560px-Kapro_logo.svg.png',
    'CHAMPION':  'https://upload.wikimedia.org/wikipedia/commons/thumb/6/6c/Champion_Logo_2018.svg/2560px-Champion_Logo_2018.svg.png',
    'GROSS':     'https://www.gross-online.com/local/templates/.default/img/logo.svg',
    'STAYER':    'https://www.stayer-instrument.ru/image/catalog/stayer_logo.png',
    'KRAFTOOL':  'https://www.instrument18.ru/upload/iblock/3e3/3e3f728e3d3cb876a81a9582d7341185.png',
    'ЗУБР':      'https://upload.wikimedia.org/wikipedia/commons/thumb/f/fb/%D0%9B%D0%BE%D0%B3%D0%BE%D1%82%D0%B8%D0%BF_%D0%97%D0%A3%D0%91%D0%A0.png/640px-%D0%9B%D0%BE%D0%B3%D0%BE%D1%82%D0%B8%D0%BF_%D0%97%D0%A3%D0%91%D0%A0.png',
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

        # 2) ВСЕ бренды каталога PrimeTools — у кого нет лого, идут как текст.
        from django.db.models import Count
        all_names = list(
            Product.objects.exclude(brand='')
            .values('brand').annotate(n=Count('id'))
            .order_by('-n').values_list('brand', flat=True)
        )
        for raw in all_names:
            name = (raw or '').strip()
            if not name or len(name) > 100:
                continue
            # отсекаем явный мусор (артикулы вместо брендов, числа, и т.п.)
            if name.replace('-', '').replace(' ', '').isdigit():
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
