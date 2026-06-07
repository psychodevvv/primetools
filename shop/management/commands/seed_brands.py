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

# Логотипы. Каждый URL вручную проверен HTTP-запросом (`verify_brand_logos`).
# Если URL отвалится — `verify_brand_logos` его уберёт, бренд станет текстом.
EXTRA_LOGOS = {
    # ── проверенные SVG прямо из Wikimedia Commons (без /thumb/) ──
    'BOSCH':       'https://upload.wikimedia.org/wikipedia/commons/1/16/Bosch-logo.svg',
    'METABO':      'https://upload.wikimedia.org/wikipedia/commons/8/81/Metabo_logo_%28no_tagline%29.svg',
    'EINHELL':     'https://upload.wikimedia.org/wikipedia/commons/e/e2/Einhell_Germany_logo.svg',
    'STIHL':       'https://upload.wikimedia.org/wikipedia/commons/3/38/Stihl_Logo_WhiteOnOrange.svg',
    'BLACK+DECKER':'https://upload.wikimedia.org/wikipedia/commons/b/b9/Black%2BDecker_Logo.svg',
    'BLACK&DECKER':'https://upload.wikimedia.org/wikipedia/commons/b/b9/Black%2BDecker_Logo.svg',
    'BLACKDECKER': 'https://upload.wikimedia.org/wikipedia/commons/b/b9/Black%2BDecker_Logo.svg',
    'STANLEY':     'https://upload.wikimedia.org/wikipedia/commons/a/a7/Stanley_Hand_Tools_logo.svg',
    'MAKITA':      'https://upload.wikimedia.org/wikipedia/commons/7/71/Makita_Logo.svg',
    'DEWALT':      'https://upload.wikimedia.org/wikipedia/commons/thumb/8/89/DeWalt_Logo.svg/3840px-DeWalt_Logo.svg.png',
    'MILWAUKEE':   'https://upload.wikimedia.org/wikipedia/commons/thumb/d/de/Milwaukee_Logo.svg/1280px-Milwaukee_Logo.svg.png',
    # ── электроника / IT — все через SimpleIcons CDN ──
    'BOSCH-SI':    'https://cdn.simpleicons.org/bosch',
    'HUSQVARNA':   'https://cdn.simpleicons.org/husqvarna',
    'HITACHI':     'https://cdn.simpleicons.org/hitachi',
    'PANASONIC':   'https://cdn.simpleicons.org/panasonic',
    'SAMSUNG':     'https://cdn.simpleicons.org/samsung',
    'XIAOMI':      'https://cdn.simpleicons.org/xiaomi',
    'HUAWEI':      'https://cdn.simpleicons.org/huawei',
    'APPLE':       'https://cdn.simpleicons.org/apple',
    'HP':          'https://cdn.simpleicons.org/hp',
    'SONY':        'https://cdn.simpleicons.org/sony',
    'LG':          'https://cdn.simpleicons.org/lg',
    'ACER':        'https://cdn.simpleicons.org/acer',
    'ASUS':        'https://cdn.simpleicons.org/asus',
    'LENOVO':      'https://cdn.simpleicons.org/lenovo',
    'DELL':        'https://cdn.simpleicons.org/dell',
    'EPSON':       'https://cdn.simpleicons.org/epson',
    'INTEL':       'https://cdn.simpleicons.org/intel',
    'AMD':         'https://cdn.simpleicons.org/amd',
    'NVIDIA':      'https://cdn.simpleicons.org/nvidia',
    'NIKON':       'https://cdn.simpleicons.org/nikon',
    # ── собственные домены брендов ──
    'STAYER':      'https://www.stayer-instrument.ru/image/catalog/stayer_logo.png',
    'KRAFTOOL':    'https://www.instrument18.ru/upload/iblock/3e3/3e3f728e3d3cb876a81a9582d7341185.png',
    # ── подтверждённые через Wikipedia API ──
    'STIHL':       'https://upload.wikimedia.org/wikipedia/commons/3/38/Stihl_Logo_WhiteOnOrange.svg',
    'FISKARS':     'https://upload.wikimedia.org/wikipedia/commons/8/87/Fiskars_group_logo_2022.svg',
    'HUSQVARNA':   'https://upload.wikimedia.org/wikipedia/commons/7/7a/Husqvarna_logo.svg',
    'KARCHER':     'https://upload.wikimedia.org/wikipedia/commons/c/ce/K%C3%A4rcher_Logo_2015.svg',
    'KÄRCHER':     'https://upload.wikimedia.org/wikipedia/commons/c/ce/K%C3%A4rcher_Logo_2015.svg',
    'GEDORE':      'https://upload.wikimedia.org/wikipedia/commons/9/9c/Gedore_logo.svg',
    'WIHA':        'https://upload.wikimedia.org/wikipedia/en/e/eb/Wiha_Tools_logo.svg',
    'PHILIPS':     'https://upload.wikimedia.org/wikipedia/commons/8/8c/Philips_logo.svg',
    'GARDENA':     'https://upload.wikimedia.org/wikipedia/commons/f/fc/Logo_Gardena.svg',
    'ASUS':        'https://upload.wikimedia.org/wikipedia/commons/2/2e/ASUS_Logo.svg',
    'DELL':        'https://upload.wikimedia.org/wikipedia/commons/1/18/Dell_logo_2016.svg',
    'ACER':        'https://upload.wikimedia.org/wikipedia/commons/2/2a/Acer-Logo_2001.svg',
    'FISCHER':     'https://upload.wikimedia.org/wikipedia/commons/2/2a/Fischer_logo.svg',
    # ── ещё проверенные SimpleIcons (общая бытовая электроника) ──
    'NIKON':       'https://cdn.simpleicons.org/nikon',
    'CANON':       'https://cdn.simpleicons.org/canon',
    'EPSON':       'https://cdn.simpleicons.org/epson',
    'INTEL':       'https://cdn.simpleicons.org/intel',
    'AMD':         'https://cdn.simpleicons.org/amd',
    'NVIDIA':      'https://cdn.simpleicons.org/nvidia',
    'LENOVO':      'https://cdn.simpleicons.org/lenovo',
    'TOSHIBA':     'https://cdn.simpleicons.org/toshiba',
    'PIONEER':     'https://cdn.simpleicons.org/pioneer',
    'JBL':         'https://cdn.simpleicons.org/jbl',
    'GOOGLE':      'https://cdn.simpleicons.org/google',
    'MICROSOFT':   'https://cdn.simpleicons.org/microsoft',
}

# Маппинг: УПЕРКЕЙСНОЕ_ИМЯ -> домен. Если у бренда нет своего лого выше,
# берём favicon с домена через Google s2/favicons — это всегда работает,
# даёт хоть какую-то узнаваемую картинку.
BRAND_DOMAINS = {
    'STARFIX': 'starfix.ru',
    'ЗУБР': 'zubr.ru',
    'TOPTUL': 'toptul.com',
    'STARTUL': 'startul.ru',
    'PERFECTO LINEA': 'perfectolinea.com',
    'YATO': 'yato.eu',
    'GEPARD': 'gepard.kz',
    'WORTEX': 'wortex.ru',
    'BYLECTRICA': 'bylectrica.by',
    'ЮПИТЕР': 'unidragon.ru',
    'GARDENA': 'gardena.com',
    'ВОЛАТ': 'volat.by',
    'ECO': 'eco-tools.ru',
    'PFERD': 'pferd.com',
    'FISKARS': 'fiskars.com',
    'GRINDA': 'grinda.ru',
    'GEDORE': 'gedore.com',
    'СИБИН': 'gross-online.com',
    'FUBAG': 'fubag.ru',
    'PRO STARTUL': 'startul.ru',
    'SOLARIS': 'solaris-tools.com',
    'PROXXON': 'proxxon.com',
    'SOLA': 'sola.at',
    'BULL': 'bull-spb.ru',
    'DISTAR': 'distar.com',
    'STEHER': 'steher.ru',
    'REXANT': 'rexant.ru',
    'RACO': 'raco.ru',
    'GREENWORKS': 'greenworkstools.com',
    'FELO': 'felo.de',
    'FISCHER': 'fischer-international.com',
    'DAEWOO': 'daewoo-electronics.com',
    'TDM': 'tdme.ru',
    'BINZEL': 'binzel-abicor.com',
    'URAGAN': 'instrument18.ru',
    'NORMANN': 'normann.kz',
    'STIHL': 'stihl.com',
    'HUSQVARNA': 'husqvarna.com',
    'KARCHER': 'karcher.com',
    'KÄRCHER': 'karcher.com',
    'EINHELL': 'einhell.com',
    'AEG': 'aeg.com',
    'RYOBI': 'ryobitools.com',
    'HITACHI': 'hitachi.com',
    'HIKOKI': 'hikoki-powertools.com',
    'STANLEY': 'stanleyblackanddecker.com',
    'BLACK+DECKER': 'blackanddecker.com',
    'CRAFTSMAN': 'craftsman.com',
    'KRESS': 'kress.com',
    'OLFA': 'olfa.com',
    'PATRIOT': 'patriot-tools.ru',
    'GROSS': 'gross-online.com',
    'BOSCH': 'bosch.com',
    'METABO': 'metabo.com',
    'MAKITA': 'makita.com',
    'DEWALT': 'dewalt.com',
    'MILWAUKEE': 'milwaukeetool.com',
    'KAPRO': 'kapro.com',
    'WIHA': 'wiha.com',
    'CHAMPION': 'championtool.ru',
    'BRENNENSTUHL': 'brennenstuhl.com',
    'WAGNER': 'wagner-group.com',
    'WOLFCRAFT': 'wolfcraft.com',
    'WORX': 'worx.com',
    'FESTOOL': 'festool.com',
    'HILTI': 'hilti.com',
    'PHILIPS': 'philips.com',
    'CANON': 'canon.com',
    'EPSON': 'epson.com',
    'NIKON': 'nikon.com',
    'PANASONIC': 'panasonic.com',
    'SAMSUNG': 'samsung.com',
    'HUAWEI': 'huawei.com',
    'XIAOMI': 'mi.com',
    'APPLE': 'apple.com',
    'HP': 'hp.com',
    'SONY': 'sony.com',
    'LG': 'lg.com',
    'DELL': 'dell.com',
    'ASUS': 'asus.com',
    'ACER': 'acer.com',
    'LENOVO': 'lenovo.com',
    'AV ENGINEERING': 'av-engineering.ru',
    'SPARTA': 'gross-online.com',
    'STAYER': 'stayer-instrument.ru',
    'KRAFTOOL': 'kraftool.ru',
    'РЕДИУС': 'redius.kz',
    'NORDBERG': 'nordberg.ru',
    'ECONOCE': 'econoce.kz',
    'BEORN': 'beorn.kz',
    'CAPSTONE': 'capstone-tools.com',
    'JIPS': 'jips.kz',
    'JCB': 'jcb.com',
    'NORMANN': 'normann.kz',
    'KRESTOOL': 'krestool.ru',
    'JONNESWAY': 'jonnesway.com',
    'KING TONY': 'kingtony.com',
    'STELS': 'gross-online.com',
    'BAHCO': 'bahco.com',
    'KNIPEX': 'knipex.com',
    'WERA': 'wera.de',
    'GROSS-ONLINE': 'gross-online.com',
    'TRUPER': 'truper.com',
    'KARCHER PRO': 'karcher.com',
    'GEMBIRD': 'gembird.com',
    'GENIUS': 'geniusnet.com',
    'GENESIS': 'genesisproject.eu',
    'GENWAY': 'genway.kz',
    'NOVA': 'nova.kz',
    'GIPFEL': 'gipfel.ru',
    'ИНТЕРСКОЛ': 'interskol.ru',
    'INTERSKOL': 'interskol.ru',
    'BOEHRER': 'boehrer.kz',
    'FORTIS': 'fortis-online.com',
    'KS TOOLS': 'kstools.com',
    'NEO': 'neo-tools.com',
    'SPECIAL': 'specialtools.ru',
    'CHENGFENG': 'chengfeng.com',
    'STANDARD': 'standard-tools.ru',
    'MASTER': 'mastertools.ru',
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
            # fallback — Google favicon домена. Гарантировано работает.
            if not b.logo_src and BRAND_DOMAINS.get(key):
                b.logo_url = (f'https://www.google.com/s2/favicons?'
                              f'domain={BRAND_DOMAINS[key]}&sz=128')
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
