"""Кросс-проверка медиа, подсосанного с mkskz.master.pro.

Раньше fetch_mks_media искал товар на MKS-портале по article и слепо
записывал найденные image/description/characteristics/video. Если у нашего
локального товара и у MKS-товара articule случайно совпадали, но это
разные товары — мы получили mismatch (картинка лески у тачки и т.п.).

Эта команда:
  1. Для каждого товара с image_url, начинающейся с mkskz.master.pro,
     делает повторный поиск на MKS-портале по article.
  2. Сравнивает имя локального товара (нормализованное) с именем найденного
     MKS-товара через токен-overlap.
  3. Если совпадение слабое (порог по умолчанию 0.30 от слов) — считаем
     это контаминацией и чистим image_url/gallery/description/
     characteristics/video_url.

Запуск:
    python manage.py verify_mks_media --password XXX
    python manage.py verify_mks_media --password XXX --dry-run
    python manage.py verify_mks_media --password XXX --threshold 0.4
    python manage.py verify_mks_media --password XXX --workers 8 --limit 100
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from django.core.management.base import BaseCommand

from shop.models import Product
from .fetch_mks_media import login, BASE


WORD_RE = re.compile(r"[\w\-./]+", re.UNICODE)


def tokens(name):
    return [t.lower() for t in WORD_RE.findall(name or '') if len(t) > 1]


def similarity(local_name, mks_name):
    """Доля токенов локального имени, которые есть и у MKS-имени.

    Числа/коды весят как обычные слова — это хорошо, потому что артикул
    как раз даст совпадение даже когда остальные слова не пересекаются.
    """
    a = set(tokens(local_name))
    b = set(tokens(mks_name))
    if not a or not b:
        return 0.0
    inter = a & b
    return len(inter) / max(1, min(len(a), len(b)))


def search_mks(session, article):
    """Возвращает имя первого товара, найденного на MKS по article."""
    try:
        r = session.get(f'{BASE}/api/search/',
                        params={'keyword': article.strip()}, timeout=15)
        if r.status_code != 200:
            return None
        results = r.json().get('results') or []
    except (requests.RequestException, ValueError):
        return None
    if not results:
        return None
    # ищем точное совпадение articul, иначе первый результат
    def name_of(it):
        return (it.get('title') or it.get('header')
                or it.get('name') or '').strip()
    for it in results:
        if (it.get('articul') or '').strip() == article.strip():
            return name_of(it)
    return name_of(results[0])


def verify_one(session, p, threshold):
    """True если match хороший, False если контаминация (надо чистить)."""
    art = (p.article or '').strip()
    if not art:
        return False
    mks_name = search_mks(session, art)
    if mks_name is None:
        # портал не нашёл — либо товар снят с продажи. Не трогаем картинку
        # на всякий случай (могла быть валидной на момент скачивания).
        return True
    sim = similarity(p.name, mks_name)
    return sim >= threshold


class Command(BaseCommand):
    help = 'Сверить локальные товары с MKS-порталом и почистить контаминацию.'

    def add_arguments(self, parser):
        parser.add_argument('--login', default='0K00000681')
        parser.add_argument('--password', required=True)
        parser.add_argument('--workers', type=int, default=8)
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--threshold', type=float, default=0.30,
                            help='Минимальная доля общих токенов между локальным '
                                 'и MKS-именами. Меньше — контаминация.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Только показать сколько было бы вычищено.')

    def handle(self, *args, **opts):
        s = login(opts['login'], opts['password'])
        if s is None:
            self.stdout.write(self.style.ERROR('Логин не прошёл.'))
            return

        qs = (Product.objects.filter(
            image_url__startswith='https://mkskz.master.pro/')
              .only('pk', 'name', 'article'))
        pks = list(qs.values_list('pk', flat=True))
        if opts['limit']:
            pks = pks[:opts['limit']]
        total = len(pks)
        self.stdout.write(f'К проверке: {total} товаров')

        dry = opts['dry_run']
        threshold = opts['threshold']
        contam_ids = []
        checked = 0
        CHUNK = 200
        for start in range(0, total, CHUNK):
            chunk_pks = pks[start:start + CHUNK]
            chunk = list(Product.objects.filter(pk__in=chunk_pks)
                         .only('pk', 'name', 'article'))
            with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
                futs = {pool.submit(verify_one, s, p, threshold): p
                        for p in chunk}
                for f in as_completed(futs):
                    p = futs[f]
                    ok = f.result()
                    checked += 1
                    if not ok:
                        contam_ids.append(p.pk)
            self.stdout.write(
                f'  {checked}/{total}: контаминированных найдено {len(contam_ids)}',
                ending='\r')
            time.sleep(0.2)
        self.stdout.write('')

        if dry:
            # Показать сэмпл
            self.stdout.write(self.style.WARNING(
                f'DRY: контаминированных {len(contam_ids)} из {checked}'))
            for p in Product.objects.filter(pk__in=contam_ids[:10]):
                self.stdout.write(f'  [{p.article}] {p.name[:70]}')
            return

        if contam_ids:
            self.stdout.write(f'Чищу image_url/gallery/desc/chars/video '
                              f'у {len(contam_ids)} товаров…')
            n = Product.objects.filter(pk__in=contam_ids).update(
                image_url='', gallery='', description='',
                characteristics='', video_url='')
            # удаляем те, что теперь без фото
            n2 = Product.objects.filter(image_url='').delete()[0]
            self.stdout.write(self.style.SUCCESS(
                f'Очищено {n}, удалено без фото {n2}.'))
        else:
            self.stdout.write(self.style.SUCCESS('Контаминации не найдено.'))
