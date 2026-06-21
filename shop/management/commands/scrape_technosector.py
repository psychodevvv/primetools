"""Скрейпер каталога technosector.kz (Joomla + jshopping).

Логика:
  1. Стартуем с / — берём дерево разделов из меню (ссылки уровня
     /<разд>/<подразд>/<категория>).
  2. Идём по каждой листовой категории, собираем ссылки на товары
     (товарные URL имеют ≥4 сегмента и ведут на страницу с h1+артикулом).
  3. Парсим каждую карточку: h1 → название, «Артикул:» → артикул,
     block_price → цена, «Описание» блок → описание, img-ы на странице → фото.
  4. Бренд = верхнеуровневая категория `/brendy/<...>` если попалась, иначе
     эвристика по первому слову названия.

Запуск:
    python manage.py scrape_technosector
    python manage.py scrape_technosector --limit 100
    python manage.py scrape_technosector --workers 6
"""
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

BASE = 'https://technosector.kz'
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'),
}

_TAG_RE = re.compile(r'<[^>]+>')

# Корневые разделы каталога (брать ссылки только из этих веток).
ROOT_SECTIONS = (
    '/elektroinstrument',
    '/benzoinstrument',
    '/ruchnoj-instrument',
    '/ruchnoy-instrument',
    '/svarochnoe-oborudovanie',
    '/sadovaya-tehnika',
    '/dom-i-sad',
    '/stroitelnoe-oborudovanie',
    '/izmeritelnyj-instrument',
    '/oborudovanie',
    '/avtoinstrument',
    '/avtotovary',
    '/silovaya-tehnika',
)

# Бренды (нужны как нормализованный список — берём из /brendy на лету).
BRAND_HINTS = ('MAGNETTA', 'DWT', 'DEWALT', 'DEWAL', 'BLACK', 'STANLEY',
               'WORTH', 'DELI', 'BOSCH', 'MAKITA', 'METABO', 'MILWAUKEE',
               'HITACHI', 'HIKOKI', 'INTERSKOL', 'ИНТЕРСКОЛ')


def _text(html):
    s = _TAG_RE.sub(' ', str(html or ''))
    s = (s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&laquo;', '«')
           .replace('&raquo;', '»').replace('&quot;', '"').replace('&mdash;', '—'))
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _price(text):
    if not text:
        return None
    digits = re.sub(r'[^\d]', '', text)
    if not digits:
        return None
    try:
        d = Decimal(digits)
        if d <= 0:
            return None
        return d
    except Exception:
        return None


def collect_category_pages(session):
    """Возвращает множество ссылок-категорий (только в наших корневых разделах)."""
    r = session.get(BASE + '/', timeout=30)
    r.raise_for_status()
    hrefs = set(re.findall(r'href="(/[^"#?]+)"', r.text))
    cats = set()
    for h in hrefs:
        # отбрасываем системные/тех
        if h.startswith(('/component', '/index.php', '/templates', '/media/',
                        '/images/', '/cache/', '/checkout', '/cart',
                        '/account', '/login', '/registration')):
            continue
        # должны попадать в наши корни
        if any(h.startswith(p) for p in ROOT_SECTIONS):
            cats.add(h)
    return sorted(cats)


def _pagination_links(html, base_path):
    """Соберём ссылки пагинации на странице категории."""
    out = set()
    for m in re.findall(rf'href="({re.escape(base_path)}/p\d+)"', html):
        out.add(m)
    # альт. формат ?start=
    for m in re.findall(r'href="([^"]+\?start=\d+)"', html):
        out.add(m)
    return out


def list_products_in_cat(session, cat_path):
    """На странице категории и её пагинации найти ссылки на товары."""
    products = set()
    seen_pages = set()
    queue = [cat_path]
    while queue:
        page = queue.pop()
        if page in seen_pages:
            continue
        seen_pages.add(page)
        url = urljoin(BASE, page)
        try:
            r = session.get(url, timeout=25)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        html = r.text
        for h in re.findall(r'href="(/[^"#?]+)"', html):
            # товар = внутри cat, на уровень глубже
            if h.startswith(cat_path + '/') and h.count('/') == cat_path.count('/') + 1:
                products.add(h)
        # пагинация
        for p in _pagination_links(html, cat_path):
            if p not in seen_pages:
                queue.append(p)
    return sorted(products)


def parse_product(session, path):
    url = urljoin(BASE, path)
    try:
        r = session.get(url, timeout=25)
        if r.status_code != 200:
            return None
        html = r.text
    except requests.RequestException:
        return None

    # имя — h1
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    if not m:
        return None
    name = _text(m.group(1))
    if not name:
        return None

    # артикул
    article = ''
    m = re.search(r'product-page-artikul[^>]*>\s*Артикул[^:]*:\s*([\w\-./]+)', html)
    if m:
        article = m.group(1).strip()
    if not article:
        m = re.search(r'Артикул[^<]*</[^>]+>\s*([\w\-./]+)', html)
        if m:
            article = m.group(1).strip()

    # цена
    price = None
    m = re.search(r'id="block_price\d*"[^>]*>(.*?)</span>', html, re.S)
    if m:
        price = _price(_text(m.group(1)))
    if price is None:
        m = re.search(r'class="prod_price"[^>]*>(.*?)</div>', html, re.S)
        if m:
            price = _price(_text(m.group(1)))

    # описание — блок «Описание»
    description = ''
    idx = html.find('Описание')
    if idx > 0:
        # найдём ближайший контейнер
        chunk = html[idx:idx + 30000]
        # текст до маркера «Похожие товары» / «Отзывы» / «Характеристики»
        for stop in ('Похожие товары', 'Отзывы', 'Доставка', 'Сопутствующие'):
            ci = chunk.find(stop)
            if ci > 100:
                chunk = chunk[:ci]; break
        description = _text(chunk).replace('Описание', '', 1).strip()

    # характеристики — если есть таблица или dl
    chars = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)
        if len(cells) == 2:
            k, v = _text(cells[0]), _text(cells[1])
            if k and v and k.lower() != v.lower() and len(k) < 80 and len(v) < 200:
                chars.append(f'{k}: {v}')
    characteristics = '\n'.join(chars)

    # картинки — собираем все img/source/data-src/data-original; фильтруем мусор.
    imgs = []
    for pat in (r'(?:src|data-src|data-original|srcset)="([^"\s]+\.(?:jpg|jpeg|png|webp))"',
                r'href="([^"]+\.(?:jpg|jpeg|png|webp))"'):
        for m in re.findall(pat, html, re.I):
            u = m.strip()
            if u.startswith('//'):
                u = 'https:' + u
            elif u.startswith('/'):
                u = BASE + u
            elif not u.startswith('http'):
                u = urljoin(url, u)
            if any(bad in u.lower() for bad in (
                    'logo', '/brands/', 'instagram', 'tiktok', 'kaspi',
                    'whatsapp', 'social', 'icon', '/favicon')):
                continue
            if u not in imgs:
                imgs.append(u)

    # бренд из заголовка (первое слово до запятой) или из имени
    brand = ''
    head = name.split(',')[0].strip()
    if head and len(head) < 30:
        brand = head
    else:
        upper = name.upper()
        for b in BRAND_HINTS:
            if upper.startswith(b):
                brand = b.capitalize(); break

    # категория — из path-крошек
    parts = [p for p in path.strip('/').split('/') if p]
    cat_slugs = parts[:-1]  # без последнего (slug товара)
    return {
        'url': url,
        'path': path,
        'name': name,
        'article': article,
        'brand': brand,
        'price': price,
        'description': description,
        'characteristics': characteristics,
        'image_url': imgs[0] if imgs else '',
        'gallery': '\n'.join(imgs[1:8]) if len(imgs) > 1 else '',
        'cat_slugs': cat_slugs,
    }


_cat_cache = {}


def _humanize(slug):
    s = slug.replace('-', ' ').replace('_', ' ').strip()
    return s.capitalize()


def get_or_make_cat(slugs):
    if not slugs:
        return None
    key = '/'.join(slugs)
    if key in _cat_cache:
        return _cat_cache[key]
    parent = None
    for slug_part in slugs:
        name = _humanize(slug_part)[:200]
        cat = Category.objects.filter(name__iexact=name, parent=parent).first()
        if not cat:
            base = slugify(name, allow_unicode=True) or slug_part
            slug, n = base, 2
            while Category.objects.filter(slug=slug).exists():
                slug = f'{base}-{n}'; n += 1
            cat = Category.objects.create(name=name, slug=slug, parent=parent)
        parent = cat
    _cat_cache[key] = parent
    return parent


class Command(BaseCommand):
    help = 'Скрейп каталога technosector.kz.'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=5)
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--only-new', action='store_true')
        parser.add_argument('--prefix', default='TS-',
                            help='Префикс артикулов.')

    def handle(self, *args, **opts):
        s = requests.Session()
        s.headers.update(HEADERS)
        self.stdout.write('Сбор категорий…')
        cats = collect_category_pages(s)
        self.stdout.write(f'Категорий найдено: {len(cats)}')

        # собираем ссылки на товары по всем категориям параллельно
        self.stdout.write('Сбор товарных ссылок…')
        all_products = set()
        with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
            futs = {pool.submit(list_products_in_cat, s, c): c for c in cats}
            done = 0
            for f in as_completed(futs):
                all_products.update(f.result())
                done += 1
                if done % 10 == 0:
                    self.stdout.write(
                        f'  обработано категорий {done}/{len(cats)}, '
                        f'товаров пока {len(all_products)}', ending='\r')
        self.stdout.write('')
        paths = sorted(all_products)
        if opts['limit']:
            paths = paths[:opts['limit']]
        self.stdout.write(f'Всего товарных страниц: {len(paths)}')

        existing = set()
        if opts['only_new']:
            existing = set(
                Product.objects.filter(article__startswith=opts['prefix'])
                .values_list('article', flat=True))

        ok = skipped = failed = 0
        CHUNK = 60
        for start in range(0, len(paths), CHUNK):
            batch = paths[start:start + CHUNK]
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
                    sku = info['article'] or info['path'].rstrip('/').rsplit('/', 1)[-1][:60]
                    article = f"{opts['prefix']}{sku}"[:200]
                    if opts['only_new'] and article in existing:
                        skipped += 1; continue
                    if not info['name'] or info['price'] is None:
                        skipped += 1; continue
                    cat = get_or_make_cat(info['cat_slugs'])
                    defaults = {
                        'category': cat,
                        'name': info['name'][:500],
                        'brand': info['brand'][:200],
                        'description': info['description'][:8000],
                        'characteristics': info['characteristics'][:6000],
                        'image_url': info['image_url'][:500],
                        'gallery': info['gallery'][:4000],
                        'price': info['price'],
                        'in_stock': True,
                    }
                    Product.objects.update_or_create(
                        article=article, defaults=defaults)
                    ok += 1
            self.stdout.write(
                f'  {min(start+CHUNK, len(paths))}/{len(paths)}: +{ok}, '
                f'пропущено {skipped}, ошибок {failed}', ending='\r')
            time.sleep(0.2)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Technosector: импортировано {ok}, пропущено {skipped}, '
            f'ошибок {failed}.'))
