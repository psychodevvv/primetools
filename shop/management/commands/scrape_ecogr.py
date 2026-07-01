"""Скрейпер каталога ecogr.kz (Laravel + Alpine.js).

Структура:
  /catalog/<id>                   — top-level раздел
  /catalog/<id>/<sub>[/...]       — подкатегории до 3-4 уровней
  /product/<id>                   — карточка товара
  ?page=N                         — пагинация

На карточке товара есть JSON-LD (Product), хлебные крошки, таблица
характеристик, картинки на content.ecogr.kz.

Запуск:
    python manage.py scrape_ecogr
    python manage.py scrape_ecogr --limit 100
    python manage.py scrape_ecogr --workers 6
    python manage.py scrape_ecogr --only-new
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

BASE = 'https://ecogr.kz'
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'),
}
TAG_RE = re.compile(r'<[^>]+>')


def _text(s):
    if not s:
        return ''
    s = TAG_RE.sub(' ', str(s))
    s = (s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&laquo;', '«')
           .replace('&raquo;', '»').replace('&quot;', '"').replace('&mdash;', '—'))
    return re.sub(r'\s+', ' ', s).strip()


def _price(v):
    if v is None:
        return None
    try:
        d = Decimal(str(v).replace(',', '.'))
        if d <= 0:
            return None
        return d.quantize(Decimal('1.'))
    except Exception:
        return None


def _abs_links(html):
    """Внутренние ссылки на ecogr.kz (без хоста)."""
    return sorted(set(re.findall(r'https?://ecogr\.kz(/[^\s"\'<>]+)', html)))


def fetch_top_cats(session):
    """Top-level /catalog/<id> со страницы /catalog."""
    r = session.get(BASE + '/catalog', timeout=20)
    return sorted(set(
        l for l in _abs_links(r.text)
        if re.match(r'^/catalog/\d+$', l)))


def walk_categories(session, top_cats):
    """BFS по дереву категорий. Возвращает множество leaf-URL (для парсинга товаров)
    и кэш всех узлов (для построения дерева)."""
    seen = set()
    leaves = set()
    queue = list(top_cats)
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        try:
            r = session.get(BASE + path, timeout=20)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        subs = [l for l in _abs_links(r.text)
                if re.match(rf'^{re.escape(path)}/\d+$', l)]
        if subs:
            queue.extend(subs)
        else:
            leaves.add(path)
    return leaves


def list_products(session, cat_path):
    """Пагинация ?page=N — стоп когда множество продуктов перестаёт расти."""
    seen_products = set()
    last_size = -1
    page = 1
    while page < 200:  # защита от бесконечного цикла
        url = f'{BASE}{cat_path}?page={page}' if page > 1 else BASE + cat_path
        try:
            r = session.get(url, timeout=20)
        except requests.RequestException:
            break
        if r.status_code != 200:
            break
        ids = re.findall(r'/product/(\d+)', r.text)
        before = len(seen_products)
        for pid in ids:
            seen_products.add(pid)
        if len(seen_products) == before:
            break
        page += 1
    return seen_products


def parse_breadcrumbs(html):
    """Возвращает список имён категорий по крошкам, без 'Назад' и без последнего
    (имя самого товара)."""
    bc = re.search(r'<(?:nav|ol|ul)[^>]*breadcrumb[^>]*>(.*?)</(?:nav|ol|ul)>',
                   html, re.S | re.I)
    if not bc:
        return []
    crumbs = []
    for a in re.findall(r'<a[^>]*>(.*?)</a>', bc.group(1), re.S):
        t = _text(a)
        if not t or t.startswith('←') or t.lower() in ('назад', 'главная', 'каталог'):
            continue
        crumbs.append(t)
    return crumbs


def parse_characteristics(html):
    idx = html.find('Характеристик')
    if idx < 0:
        return ''
    chunk = html[idx:idx + 15000]
    out = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', chunk, re.S):
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)
        if len(cells) >= 2:
            k = _text(cells[0]).rstrip(':')
            v = _text(cells[1])
            if k and v and k.lower() != v.lower() and len(k) < 80 and len(v) < 400:
                out.append(f'{k}: {v}')
    if not out:
        # fallback на dl/dt/dd
        for k, v in re.findall(
                r'<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>', chunk, re.S):
            k, v = _text(k).rstrip(':'), _text(v)
            if k and v:
                out.append(f'{k}: {v}')
    return '\n'.join(out)


def parse_product(session, pid):
    url = f'{BASE}/product/{pid}'
    try:
        r = session.get(url, timeout=25)
        if r.status_code != 200:
            return None
        html = r.text
    except requests.RequestException:
        return None

    # JSON-LD Product
    ld = None
    for blob in re.findall(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(blob.strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and it.get('@type') == 'Product':
                ld = it; break
        if ld:
            break
    if not ld:
        return None

    name = (ld.get('name') or '').strip()
    if not name:
        return None
    description = (ld.get('description') or '').strip()
    sku = (ld.get('sku') or '').strip()
    brand = ''
    b = ld.get('brand')
    if isinstance(b, dict):
        brand = (b.get('name') or '').strip()
    elif isinstance(b, str):
        brand = b.strip()

    price = None
    in_stock = True
    offer = ld.get('offers')
    if isinstance(offer, dict):
        price = _price(offer.get('price'))
        if 'outofstock' in (offer.get('availability') or '').lower():
            in_stock = False

    # картинки: JSON-LD image (мб строка или список) + все 640x480 в HTML
    images = []
    img_ld = ld.get('image')
    if isinstance(img_ld, str):
        images.append(img_ld)
    elif isinstance(img_ld, list):
        images.extend(i for i in img_ld if isinstance(i, str))
    # увеличим thumbnails: -160x120 → -640x480
    images = [re.sub(r'-160x120\.', '-640x480.', i) for i in images]
    for m in re.findall(
            r'src=["\'](https?://content\.ecogr\.kz/images/products/[^"\']+\.(?:jpg|jpeg|png|webp))["\']',
            html, re.I):
        u = re.sub(r'-160x120\.', '-640x480.', m)
        if u not in images:
            images.append(u)

    breadcrumbs = parse_breadcrumbs(html)
    # Последняя крошка на ecogr — это бренд (SOLARIS, TOPTUL и т.д.).
    # Не нужна как категория.
    if breadcrumbs and brand and breadcrumbs[-1].strip().lower() == brand.strip().lower():
        breadcrumbs = breadcrumbs[:-1]
    characteristics = parse_characteristics(html)

    # видео — youtube/vimeo/rutube embed
    video_url = ''
    vm = re.search(
        r'<iframe[^>]+src=["\']('
        r'https?://(?:www\.)?(?:youtube\.com/embed/|youtu\.be/|'
        r'player\.vimeo\.com/video/|rutube\.ru/play/embed/)[^"\']+'
        r')["\']', html, re.I)
    if vm:
        video_url = vm.group(1)
        # youtube embed → watch для нормального проигрывания на сайте
        ym = re.match(
            r'https?://(?:www\.)?youtube\.com/embed/([\w\-]+)', video_url)
        if ym:
            video_url = f'https://www.youtube.com/watch?v={ym.group(1)}'

    return {
        'pid': pid,
        'name': name,
        'article': sku or pid,
        'brand': brand,
        'description': description,
        'characteristics': characteristics,
        'image_url': images[0] if images else '',
        'gallery': '\n'.join(images[1:10]) if len(images) > 1 else '',
        'video_url': video_url,
        'price': price,
        'in_stock': in_stock,
        'breadcrumbs': breadcrumbs,
    }


_cat_cache = {}


def get_or_make_cat(names):
    if not names:
        return None
    key = ' / '.join(names)
    if key in _cat_cache:
        return _cat_cache[key]
    parent = None
    for nm in names:
        nm = nm[:200]
        cat = Category.objects.filter(name=nm, parent=parent).first()
        if not cat:
            base = slugify(nm, allow_unicode=True) or 'cat'
            slug, n = base, 2
            while Category.objects.filter(slug=slug).exists():
                slug = f'{base}-{n}'; n += 1
            cat = Category.objects.create(name=nm, slug=slug, parent=parent)
        parent = cat
    _cat_cache[key] = parent
    return parent


class Command(BaseCommand):
    help = 'Скрейп каталога ecogr.kz.'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=6)
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--only-new', action='store_true')
        parser.add_argument('--prefix', default='ECOGR-',
                            help='Префикс артикулов.')

    def handle(self, *args, **opts):
        s = requests.Session()
        s.headers.update(HEADERS)
        self.stdout.write('Сбор top-level разделов…')
        top = fetch_top_cats(s)
        self.stdout.write(f'  разделов: {len(top)}')

        self.stdout.write('Обход дерева категорий (BFS)…')
        leaves = walk_categories(s, top)
        self.stdout.write(f'  листовых категорий: {len(leaves)}')

        self.stdout.write('Сбор товарных ID по категориям…')
        all_pids = set()
        with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
            futs = {pool.submit(list_products, s, c): c for c in leaves}
            done = 0
            for f in as_completed(futs):
                all_pids.update(f.result())
                done += 1
                if done % 20 == 0:
                    self.stdout.write(
                        f'  категорий {done}/{len(leaves)}, товаров пока {len(all_pids)}',
                        ending='\r')
        self.stdout.write('')
        pids = sorted(all_pids, key=int)
        if opts['limit']:
            pids = pids[:opts['limit']]
        self.stdout.write(f'Всего товаров к парсингу: {len(pids)}')

        existing = set()
        if opts['only_new']:
            existing = set(
                Product.objects.filter(article__startswith=opts['prefix'])
                .values_list('article', flat=True))

        ok = skipped = failed = 0
        CHUNK = 80
        for start in range(0, len(pids), CHUNK):
            batch = pids[start:start + CHUNK]
            parsed = []
            with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
                futs = {pool.submit(parse_product, s, p): p for p in batch}
                for f in as_completed(futs):
                    info = f.result()
                    if not info:
                        failed += 1; continue
                    parsed.append(info)
            with transaction.atomic():
                for info in parsed:
                    article = f"{opts['prefix']}{info['article']}"[:200]
                    if opts['only_new'] and article in existing:
                        skipped += 1; continue
                    if info['price'] is None:
                        skipped += 1; continue
                    cat = get_or_make_cat(info['breadcrumbs'] or ['EcoGroup', 'Без категории'])
                    defaults = {
                        'category': cat,
                        'name': info['name'][:500],
                        'brand': info['brand'][:200],
                        'description': info['description'][:8000],
                        'characteristics': info['characteristics'][:6000],
                        'image_url': info['image_url'][:500],
                        'gallery': info['gallery'][:4000],
                        'video_url': info['video_url'][:500],
                        'price': info['price'],
                        'in_stock': info['in_stock'],
                    }
                    Product.objects.update_or_create(
                        article=article, defaults=defaults)
                    ok += 1
            self.stdout.write(
                f'  {min(start+CHUNK, len(pids))}/{len(pids)}: +{ok}, '
                f'пропущено {skipped}, ошибок {failed}', ending='\r')
            time.sleep(0.2)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'EcoGroup: импортировано {ok}, пропущено {skipped}, '
            f'ошибок {failed}.'))
