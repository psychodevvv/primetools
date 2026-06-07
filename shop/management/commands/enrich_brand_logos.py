"""Для каждого Brand без лого пытается автоматически найти и поставить лого.

Источники (в порядке попытки):
  1. жёсткий список EXTRA_LOGOS из seed_brands
  2. SimpleIcons CDN — для популярных брендов (электроника)
  3. Wikipedia API — ищет на странице бренда изображение со словом "logo"

Запуск:  python manage.py enrich_brand_logos
"""
import time

import requests
from django.core.management.base import BaseCommand

from shop.models import Brand
from shop.management.commands.seed_brands import EXTRA_LOGOS

_UA = 'PrimeToolsBot/1.0 (https://primetools.kz; admin@primetools.kz)'
_HEADERS = {'User-Agent': _UA}

# SimpleIcons slug по апперкейс-названию бренда
SIMPLE_ICONS = {
    'BOSCH': 'bosch', 'HUSQVARNA': 'husqvarna', 'HITACHI': 'hitachi',
    'PANASONIC': 'panasonic', 'SAMSUNG': 'samsung', 'XIAOMI': 'xiaomi',
    'HUAWEI': 'huawei', 'APPLE': 'apple', 'HP': 'hp', 'SONY': 'sony',
    'LG': 'lg', 'EPSON': 'epson', 'ACER': 'acer', 'ASUS': 'asus',
    'LENOVO': 'lenovo', 'DELL': 'dell', 'NIKON': 'nikon', 'INTEL': 'intel',
    'AMD': 'amd', 'NVIDIA': 'nvidia', 'WD40': 'wd-40',
}

# Wikipedia-страница, на которой обычно лежит логотип
WIKI_TITLES = {
    'BOSCH': 'Bosch (company)', 'MAKITA': 'Makita',
    'METABO': 'Metabo', 'STIHL': 'Stihl', 'HUSQVARNA': 'Husqvarna Group',
    'KARCHER': 'Kärcher', 'KÄRCHER': 'Kärcher',
    'FISKARS': 'Fiskars Group', 'GARDENA': 'Gardena (company)',
    'HITACHI': 'Hitachi', 'HIKOKI': 'Koki Holdings',
    'RYOBI': 'Ryobi (manufacturer)', 'EINHELL': 'Einhell',
    'AEG': 'AEG', 'STANLEY': 'Stanley Black & Decker',
    'BLACK+DECKER': 'Black %26 Decker', 'BLACK&DECKER': 'Black %26 Decker',
    'BLACKDECKER': 'Black %26 Decker', 'CRAFTSMAN': 'Craftsman (tools)',
    'OLFA': 'Olfa', 'PROXXON': 'Proxxon',
    'PHILIPS': 'Philips', 'CANON': 'Canon Inc.',
    'YATO': 'Yato Tools', 'GREENWORKS': 'Greenworks Tools',
    'FESTOOL': 'Festool', 'HILTI': 'Hilti', 'WOLFCRAFT': 'Wolfcraft',
    'BRENNENSTUHL': 'Brennenstuhl', 'PFERD': 'Pferd',
    'KOBALT': 'Kobalt (tools)', 'WORX': 'Worx',
}


def http_ok(url):
    try:
        r = requests.get(url, timeout=12, headers=_HEADERS, stream=True,
                         allow_redirects=True)
        if r.status_code != 200:
            return False
        ct = (r.headers.get('Content-Type') or '').lower()
        if 'image' in ct or 'svg' in ct:
            return True
        chunk = next(r.iter_content(16), b'')
        sig = chunk[:8]
        return (sig.startswith(b'\x89PNG') or sig.startswith(b'\xff\xd8')
                or sig.startswith(b'GIF8') or b'<svg' in chunk.lower())
    except requests.RequestException:
        return False


def find_via_wikipedia(title):
    """Ищет на статье бренда первое image со словом 'logo' в имени."""
    try:
        r = requests.get('https://en.wikipedia.org/w/api.php', params={
            'action': 'query', 'format': 'json', 'titles': title,
            'prop': 'images', 'imlimit': '60',
        }, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return ''
        for page in r.json().get('query', {}).get('pages', {}).values():
            for img in page.get('images', []):
                t = img.get('title', '').lower()
                if 'logo' not in t:
                    continue
                # пропускаем Commons-logo (placeholder Wikipedia)
                if 'commons-logo' in t or 'wikimedia' in t:
                    continue
                # получаем настоящий URL
                rr = requests.get('https://en.wikipedia.org/w/api.php', params={
                    'action': 'query', 'format': 'json', 'titles': img['title'],
                    'prop': 'imageinfo', 'iiprop': 'url',
                }, headers=_HEADERS, timeout=10)
                if rr.status_code != 200:
                    continue
                for p in rr.json().get('query', {}).get('pages', {}).values():
                    for ii in p.get('imageinfo', []):
                        url = ii.get('url', '')
                        if url and http_ok(url):
                            return url
    except requests.RequestException:
        pass
    return ''


class Command(BaseCommand):
    help = 'Авто-поиск лого для брендов через SimpleIcons и Wikipedia.'

    def handle(self, *args, **options):
        brands = list(Brand.objects.filter(featured=True, logo='', logo_url=''))
        self.stdout.write(f'Брендов без лого: {len(brands)}')
        added = 0
        for b in brands:
            key = b.name.upper().strip()
            url = ''

            # 1) жёсткий справочник
            if EXTRA_LOGOS.get(key) and http_ok(EXTRA_LOGOS[key]):
                url = EXTRA_LOGOS[key]
                src = 'EXTRA'

            # 2) SimpleIcons (электроника, IT)
            if not url and SIMPLE_ICONS.get(key):
                u = f'https://cdn.simpleicons.org/{SIMPLE_ICONS[key]}'
                if http_ok(u):
                    url = u
                    src = 'simpleicons'

            # 3) Wikipedia
            if not url and WIKI_TITLES.get(key):
                u = find_via_wikipedia(WIKI_TITLES[key])
                if u:
                    url = u
                    src = 'wikipedia'

            if url:
                b.logo_url = url
                b.save(update_fields=['logo_url'])
                added += 1
                self.stdout.write(f'  ✓ {b.name} ← {src}')
                time.sleep(0.2)

        with_logo = Brand.objects.exclude(logo_url='').count() + \
            Brand.objects.exclude(logo='').count()
        self.stdout.write(self.style.SUCCESS(
            f'Готово. Добавлено лого: {added}. Всего с лого: {with_logo}/{Brand.objects.count()}'))
