"""Проверка встраиваемости видео (YouTube/Vimeo) — отмечает video_blocked.

YouTube возвращает Error 153 «настройки видеопроигрывателя», когда автор
канала запретил встраивание. Это определяется через эндпоинт oembed:
если он отдаёт 401/403, встраивать нельзя.

Запуск:
    python manage.py check_video_embeds
    python manage.py check_video_embeds --workers 12 --limit 50
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from django.core.management.base import BaseCommand

from shop.models import Product

HEADERS = {'User-Agent': 'Mozilla/5.0'}


def _check_youtube(url):
    """True если ВСТРАИВАНИЕ запрещено."""
    try:
        r = requests.get('https://www.youtube.com/oembed',
                         params={'url': url, 'format': 'json'},
                         headers=HEADERS, timeout=10)
    except requests.RequestException:
        return None  # сеть упала — не штрафуем
    if r.status_code == 200:
        return False
    # 401 — embedding disabled. 404 — видео удалено (тоже фиаско).
    if r.status_code in (401, 403, 404):
        return True
    return None


def _check_vimeo(url):
    try:
        r = requests.get('https://vimeo.com/api/oembed.json',
                         params={'url': url}, headers=HEADERS, timeout=10)
    except requests.RequestException:
        return None
    if r.status_code == 200:
        return False
    if r.status_code in (401, 403, 404):
        return True
    return None


def check(url):
    u = url or ''
    if not u:
        return False
    if 'youtube' in u or 'youtu.be' in u:
        return _check_youtube(u)
    if 'vimeo' in u:
        return _check_vimeo(u)
    # Rutube/VK — нет публичного oembed, считаем по умолчанию работающим
    return False


class Command(BaseCommand):
    help = 'Проверить какие видео не встраиваются (Error 153) — пометить blocked.'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=10)
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--refresh', action='store_true',
                            help='Перепроверять даже уже отмеченные.')

    def handle(self, *args, **opts):
        qs = Product.objects.exclude(video_url='').only('pk', 'video_url',
                                                         'video_blocked')
        if not opts['refresh']:
            qs = qs.filter(video_blocked=False)
        if opts['limit']:
            qs = qs[:opts['limit']]
        items = list(qs)
        total = len(items)
        self.stdout.write(f'К проверке: {total} видео')
        if not total:
            return

        blocked = []
        checked = 0
        with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
            futs = {pool.submit(check, p.video_url): p for p in items}
            for f in as_completed(futs):
                p = futs[f]
                r = f.result()
                checked += 1
                if r is True:
                    blocked.append(p.pk)
                if checked % 25 == 0:
                    self.stdout.write(
                        f'  {checked}/{total}: blocked {len(blocked)}',
                        ending='\r')
                # лёгкая пауза против троттлинга
                time.sleep(0.02)
        self.stdout.write('')
        if blocked:
            Product.objects.filter(pk__in=blocked).update(video_blocked=True)
        self.stdout.write(self.style.SUCCESS(
            f'Проверено {total}, заблокировано встраивание у {len(blocked)}.'))
