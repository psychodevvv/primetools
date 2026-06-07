"""Проверяет каждый logo_url у Brand HTTP-запросом и убирает битые.

Запуск:  python manage.py verify_brand_logos
"""
from concurrent.futures import ThreadPoolExecutor

import requests
from django.core.management.base import BaseCommand

from shop.models import Brand

_HEADERS = {
    'User-Agent': 'PrimeToolsBot/1.0 (https://primetools.kz; admin@primetools.kz)'
}


def check(url):
    """Возвращает 'ok' (рабочее изображение), 'bad' (404/403/не картинка),
    либо 'unknown' (сеть/таймаут — оставляем как есть).
    """
    if not url:
        return 'bad'
    for attempt in range(2):
        try:
            r = requests.get(url, timeout=20, headers=_HEADERS, stream=True,
                             allow_redirects=True)
            if r.status_code in (200,):
                ct = (r.headers.get('Content-Type') or '').lower()
                if 'image' in ct or 'svg' in ct:
                    return 'ok'
                chunk = next(r.iter_content(32), b'')
                sig = chunk[:8]
                if (sig.startswith(b'\x89PNG') or sig.startswith(b'\xff\xd8')
                        or sig.startswith(b'GIF8') or b'<svg' in chunk.lower()
                        or sig.startswith(b'RIFF')):
                    return 'ok'
                return 'bad'
            if r.status_code in (403, 404, 410, 451):
                return 'bad'
            return 'unknown'
        except requests.RequestException:
            continue
    return 'unknown'


class Command(BaseCommand):
    help = 'Проверяет logo_url у Brand. Удаляет только явно битые (404/etc), таймауты не трогает.'

    def handle(self, *args, **options):
        brands = list(Brand.objects.exclude(logo_url=''))
        self.stdout.write(f'Проверяю {len(brands)} ссылок (4 потока, 20s timeout)…')
        results = {}
        # ниже параллелизм — Wikimedia/SimpleIcons менее склонны к 429
        with ThreadPoolExecutor(max_workers=4) as pool:
            for b, status in zip(brands, pool.map(lambda b: check(b.logo_url), brands)):
                results[b.pk] = status

        bad = [b for b in brands if results.get(b.pk) == 'bad']
        unknown = [b for b in brands if results.get(b.pk) == 'unknown']
        self.stdout.write(f'  ok: {len(brands)-len(bad)-len(unknown)}, '
                          f'bad: {len(bad)}, неопределённо (оставляем): {len(unknown)}')
        for b in bad:
            self.stdout.write(f'  ✕ {b.name}: {b.logo_url[:80]}')
            b.logo_url = ''
            b.save(update_fields=['logo_url'])

        ok = Brand.objects.exclude(logo='').count() + Brand.objects.exclude(
            logo_url='').count()
        no_logo = Brand.objects.filter(featured=True, logo='', logo_url='').count()
        self.stdout.write(self.style.SUCCESS(
            f'Готово. С рабочим лого: {ok}, без лого: {no_logo} '
            f'(показываются как текст).'))
