"""Скрейпер каталога lamed.kz.

Логика:
  1. Берём sitemap.xml — там все URL: /catalog/<slug>/ (категории)
     и /card/<slug>/ (карточки товаров).
  2. Для каждой карточки парсим JSON-LD (schema.org/Product) — оттуда
     name, sku, brand, price, image, description.
  3. Дополнительно из HTML — все картинки товара (/media/goods/...),
     характеристики (таблица), категорию из крошек.
  4. Категорию создаём (или находим) в нашем дереве Category, привязываем.

Запуск:
    python manage.py scrape_lamed                # всё
    python manage.py scrape_lamed --limit 50     # тест на 50
    python manage.py scrape_lamed --workers 8
    python manage.py scrape_lamed --only-new     # пропускать уже импортированные article
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from urllib.parse import urljoin

import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from shop.models import Category, Product

BASE = 'https://www.lamed.kz'
SITEMAP = f'{BASE}/sitemap.xml'
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'),
}

_TAG_RE = re.compile(r'<[^>]+>')
_PRICE_RE = re.compile(r'[^\d.]')


def _text(html):
    if not html:
        return ''
    s = _TAG_RE.sub(' ', str(html))
    s = (s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&laquo;', '«')
           .replace('&raquo;', '»').replace('&quot;', '"').replace('&mdash;', '—'))
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _price(v):
    if v is None:
        return None
    try:
        d = Decimal(_PRICE_RE.sub('', str(v).replace(',', '.')))
        if d <= 0:
            return None
        return d.quantize(Decimal('1.'))
    except Exception:
        return None


def list_card_urls(session):
    """Все товарные URL из sitemap.xml lamed."""
    r = session.get(SITEMAP, timeout=60)
    r.raise_for_status()
    urls = re.findall(r'<loc>([^<]+)</loc>', r.text)
    cards = [u.strip() for u in urls if '/card/' in u]
    return cards


def parse_card(session, url):
    try:
        r = session.get(url, timeout=25)
        if r.status_code != 200:
            return None
        html = r.text
    except requests.RequestException:
        return None

    # 1) JSON-LD Product
    product_ld = None
    breadcrumbs_ld = None
    for blob in re.findall(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
            html, re.S):
        try:
            data = json.loads(blob.strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get('@type') == 'Product':
                product_ld = it
            elif it.get('@type') == 'BreadcrumbList':
                breadcrumbs_ld = it
    if not product_ld:
        return None

    name = (product_ld.get('name') or '').strip()
    sku = (product_ld.get('sku') or '').strip()
    description = (product_ld.get('description') or '').strip()
    brand = ''
    b = product_ld.get('brand')
    if isinstance(b, dict):
        brand = (b.get('name') or '').strip()
    elif isinstance(b, str):
        brand = b.strip()

    price = None
    offer = product_ld.get('offers')
    if isinstance(offer, dict):
        price = _price(offer.get('price'))
    in_stock = True
    if isinstance(offer, dict):
        av = (offer.get('availability') or '').lower()
        if 'outofstock' in av:
            in_stock = False

    # 2) Картинки — главное из JSON-LD + все /media/goods/ из HTML.
    images = []
    img_ld = product_ld.get('image')
    if isinstance(img_ld, str):
        images.append(img_ld)
    elif isinstance(img_ld, list):
        images.extend(i for i in img_ld if isinstance(i, str))
    # дополнительные
    for m in re.findall(
            r'(?:src|data-src|data-original)="(/media/goods/[^"]+)"', html):
        u = urljoin(BASE, m)
        if u not in images:
            images.append(u)
    # уникализируем без потери порядка
    seen = set(); imgs = []
    for u in images:
        if u in seen: continue
        seen.add(u); imgs.append(u)

    # 3) Хлебные крошки → дерево категорий.
    breadcrumbs = []
    if breadcrumbs_ld:
        elems = breadcrumbs_ld.get('itemListElement') or []
        for el in elems:
            n = (el.get('name') or '').strip() if isinstance(el, dict) else ''
            if n and n.lower() not in ('главная', 'lamed', 'ламэд', 'каталог'):
                breadcrumbs.append(n)
    # Фолбэк — HTML-крошки: <nav class="breadcrumbs"> или <ol class="breadcrumb">
    if not breadcrumbs:
        for cls in ('breadcrumbs', 'breadcrumb'):
            bm = re.search(rf'<(?:nav|ol|ul)[^>]*class="[^"]*{cls}[^"]*"[^>]*>(.*?)</(?:nav|ol|ul)>',
                           html, re.S)
            if not bm:
                continue
            for a in re.findall(r'<a[^>]*>(.*?)</a>', bm.group(1), re.S):
                t = _text(a)
                if t and t.lower() not in ('главная', 'lamed', 'ламэд', 'каталог'):
                    breadcrumbs.append(t)
            if breadcrumbs:
                break
    if breadcrumbs and breadcrumbs[-1].lower() == name.lower():
        breadcrumbs = breadcrumbs[:-1]

    # 3b) Полное описание из HTML — JSON-LD часто обрезает на 200 символов.
    full_desc = ''
    for pat in (r'<div[^>]*class="[^"]*product-description[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*itemprop="description"[^>]*>(.*?)</div>',
                r'<section[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</section>'):
        dm = re.search(pat, html, re.S | re.I)
        if dm:
            full_desc = _text(dm.group(1))
            break
    if full_desc and len(full_desc) > len(description):
        description = full_desc

    # 4) Характеристики — ищем таблицу после слова «Характеристики».
    chars = []
    chunk_idx = html.find('Характеристики')
    if chunk_idx > 0:
        chunk = html[chunk_idx:chunk_idx + 12000]
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', chunk, re.S):
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)
            if len(cells) >= 2:
                k = _text(cells[0]); v = _text(cells[1])
                if k and v and k.lower() != v.lower():
                    chars.append(f'{k}: {v}')
        # альтернатива — list-style "name: value"
        if not chars:
            for li in re.findall(r'<li[^>]*>(.*?)</li>', chunk, re.S)[:50]:
                txt = _text(li)
                if ':' in txt and len(txt) < 200:
                    chars.append(txt)

    return {
        'url': url,
        'name': name,
        'article': sku,
        'brand': brand,
        'description': description,
        'characteristics': '\n'.join(chars),
        'image_url': imgs[0] if imgs else '',
        'gallery': '\n'.join(imgs[1:]) if len(imgs) > 1 else '',
        'price': price,
        'in_stock': in_stock,
        'breadcrumbs': breadcrumbs,
    }


_cat_cache = {}


def get_or_make_cat(path):
    """path — список имён ['Электроинструмент', 'Дрели', ...]."""
    if not path:
        return None
    key = ' / '.join(path)
    if key in _cat_cache:
        return _cat_cache[key]
    parent = None
    for name in path:
        name = name[:200]
        cat = Category.objects.filter(name=name, parent=parent).first()
        if not cat:
            base = slugify(name, allow_unicode=True) or 'cat'
            slug, n = base, 2
            while Category.objects.filter(slug=slug).exists():
                slug = f'{base}-{n}'; n += 1
            cat = Category.objects.create(name=name, slug=slug, parent=parent)
        parent = cat
    _cat_cache[key] = parent
    return parent


class Command(BaseCommand):
    help = 'Скрейп каталога lamed.kz через sitemap.xml + JSON-LD.'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=6)
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--only-new', action='store_true',
                            help='Пропускать товары, у которых уже есть article.')
        parser.add_argument('--prefix', default='LAMED-',
                            help='Префикс артикулов, чтобы не пересеклись с МКС/BCM.')

    def handle(self, *args, **opts):
        s = requests.Session()
        s.headers.update(HEADERS)
        self.stdout.write('Получаю sitemap…')
        urls = list_card_urls(s)
        self.stdout.write(f'Карточек в sitemap: {len(urls)}')
        if opts['limit']:
            urls = urls[:opts['limit']]

        existing_articles = set()
        if opts['only_new']:
            existing_articles = set(
                Product.objects.filter(article__startswith=opts['prefix'])
                .values_list('article', flat=True))

        ok = skipped = failed = 0
        CHUNK = 80
        for start in range(0, len(urls), CHUNK):
            batch = urls[start:start + CHUNK]
            parsed = []
            with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
                futs = {pool.submit(parse_card, s, u): u for u in batch}
                for f in as_completed(futs):
                    info = f.result()
                    if not info:
                        failed += 1; continue
                    parsed.append(info)

            with transaction.atomic():
                for info in parsed:
                    sku = info['article'] or info['url'].rstrip('/').rsplit('/', 1)[-1]
                    article = f"{opts['prefix']}{sku}"[:200]
                    if opts['only_new'] and article in existing_articles:
                        skipped += 1; continue
                    if not info['name'] or info['price'] is None:
                        skipped += 1; continue

                    cat = get_or_make_cat(info['breadcrumbs'] or ['Lamed', 'Без категории'])
                    defaults = {
                        'category': cat,
                        'name': info['name'][:500],
                        'brand': info['brand'][:200],
                        'description': info['description'][:8000],
                        'characteristics': info['characteristics'][:6000],
                        'image_url': info['image_url'][:500],
                        'gallery': info['gallery'][:4000],
                        'price': info['price'],
                        'in_stock': info['in_stock'],
                    }
                    obj, created = Product.objects.update_or_create(
                        article=article, defaults=defaults)
                    ok += 1
            self.stdout.write(
                f'  {min(start+CHUNK, len(urls))}/{len(urls)}: +{ok}, пропущено {skipped}, ошибок {failed}',
                ending='\r')
            time.sleep(0.2)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Lamed: импортировано {ok}, пропущено {skipped}, ошибок {failed}.'))
