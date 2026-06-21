"""Подкачка фото, галереи и видео для товаров МКС через авторизованный
портал mkskz.master.pro.

Логика:
  1. Авторизация на /login/ (логин — код контрагента, пароль).
  2. Поиск по артикулу через /api/search/?keyword=ARTICUL → отдаёт id товара.
  3. GET /api/product/{id}/ → JSON c полями `picture`, `picturetype`,
     `images: [{image_id, type}, ...]`, `videos: [...]`.
  4. Картинки лежат как https://mkskz.master.pro/dbpics/{image_id}.{type}.
  5. Главное фото → Product.image_url, остальные → Product.gallery
     (по одному URL на строку). Видео → Product.video_url.

Запуск:
    python manage.py fetch_mks_media --login 0K00000681 --password XXX
    python manage.py fetch_mks_media --refresh    # перезаписать заполненные
    python manage.py fetch_mks_media --limit 50   # тест на 50 товарах
    python manage.py fetch_mks_media --workers 8  # параллельность
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from django.core.management.base import BaseCommand
from django.db.models import Q

from shop.models import Product

BASE = 'https://mkskz.master.pro'
PIC_BASE = f'{BASE}/dbpics'
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'),
    'X-Requested-With': 'XMLHttpRequest',
}


def login(login_code, password):
    """Возвращает авторизованную requests.Session или None."""
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(BASE + '/', timeout=20)
    r = s.post(BASE + '/login/',
               data={'email': login_code, 'password': password},
               timeout=20, allow_redirects=False)
    if r.status_code not in (200, 302):
        return None
    # проверим, что куки выданы (b2busercompoauth и т.п.)
    if not any(k.startswith('b2b') for k in s.cookies.keys()):
        return None
    return s


def fetch_one(session, article):
    """Возвращает dict с image_url / gallery / video_url для одного артикула."""
    art = (article or '').strip()
    if not art:
        return None
    try:
        r = session.get(f'{BASE}/api/search/', params={'keyword': art}, timeout=20)
        if r.status_code != 200:
            return None
        j = r.json()
        results = j.get('results') or []
        # ищем точное совпадение articul, иначе берём первое
        pid = None
        for it in results:
            if (it.get('articul') or '').strip() == art:
                pid = it.get('id'); break
        if pid is None and results:
            pid = results[0].get('id')
        if not pid:
            return None
        r2 = session.get(f'{BASE}/api/product/{pid}/', timeout=20)
        if r2.status_code != 200:
            return None
        p = r2.json()
    except (requests.RequestException, ValueError):
        return None

    images = p.get('images') or []
    urls = []
    # главная — поле picture+picturetype, фолбэк на первый элемент images
    main_id = p.get('picture')
    main_ext = (p.get('picturetype') or 'jpg').lower()
    if main_id:
        urls.append(f'{PIC_BASE}/{main_id}.{main_ext}')
    for img in images:
        iid = img.get('image_id'); ext = (img.get('type') or 'jpg').lower()
        if not iid:
            continue
        u = f'{PIC_BASE}/{iid}.{ext}'
        if u not in urls:
            urls.append(u)

    videos = p.get('videos') or []
    video_url = ''
    for v in videos:
        if isinstance(v, dict):
            video_url = v.get('url') or v.get('link') or v.get('href') or ''
        elif isinstance(v, str):
            video_url = v
        if video_url:
            break

    return {
        'image_url': urls[0] if urls else '',
        'gallery': '\n'.join(urls[1:]) if len(urls) > 1 else '',
        'video_url': video_url,
    }


class Command(BaseCommand):
    help = 'Подкачка фото/галереи/видео для товаров МКС через mkskz.master.pro.'

    def add_arguments(self, parser):
        parser.add_argument('--login', default='0K00000681')
        parser.add_argument('--password', required=True,
                            help='Пароль для mkskz.master.pro')
        parser.add_argument('--workers', type=int, default=6,
                            help='Параллельных запросов.')
        parser.add_argument('--refresh', action='store_true',
                            help='Перезаписать уже заполненные image_url.')
        parser.add_argument('--limit', type=int, default=0,
                            help='Ограничить N товаров (для теста).')
        parser.add_argument('--brand-contains', default='',
                            help='Брать только товары, где бренд содержит подстроку.')

    def handle(self, *args, **opts):
        s = login(opts['login'], opts['password'])
        if s is None:
            self.stdout.write(self.style.ERROR(
                'Логин не прошёл — проверь логин/пароль mkskz.master.pro.'))
            return
        self.stdout.write(self.style.SUCCESS('Авторизация ок.'))

        qs = Product.objects.exclude(article='')
        if not opts['refresh']:
            qs = qs.filter(Q(image_url='') | Q(image_url__isnull=True))
        if opts['brand_contains']:
            qs = qs.filter(brand__icontains=opts['brand_contains'])
        if opts['limit']:
            qs = qs.order_by('pk')[:opts['limit']]
        pks = list(qs.values_list('pk', flat=True))
        total = len(pks)
        if not total:
            self.stdout.write('Нет товаров для обработки.')
            return
        self.stdout.write(f'К обработке: {total} товаров, {opts["workers"]} потоков.')

        # Параллельная подкачка по чанкам, чтобы не открывать 12k futures сразу.
        CHUNK = 200
        done = updated = not_found = 0
        for start in range(0, total, CHUNK):
            chunk = list(Product.objects.filter(
                pk__in=pks[start:start + CHUNK]).only(
                'pk', 'article', 'image_url', 'gallery', 'video_url'))
            batch_updates = []
            with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
                futs = {pool.submit(fetch_one, s, p.article): p for p in chunk}
                for f in as_completed(futs):
                    p = futs[f]
                    info = f.result()
                    done += 1
                    if not info or not info['image_url']:
                        not_found += 1
                        continue
                    p.image_url = info['image_url']
                    p.gallery = info['gallery']
                    if info['video_url']:
                        p.video_url = info['video_url']
                    batch_updates.append(p)
            if batch_updates:
                Product.objects.bulk_update(
                    batch_updates, ['image_url', 'gallery', 'video_url'],
                    batch_size=300)
                updated += len(batch_updates)
            self.stdout.write(
                f'  {done}/{total} обработано, +{updated} с медиа, '
                f'не найдено: {not_found}', ending='\r')
            # лёгкая пауза, чтобы не злить сервер
            time.sleep(0.3)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Готово. Обработано: {done}, обновлено: {updated}, '
            f'не найдено на портале: {not_found}.'))
