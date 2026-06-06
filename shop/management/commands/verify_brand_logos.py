"""Проверяет каждый logo_url у Brand HTTP-запросом и убирает битые.

Запуск:  python manage.py verify_brand_logos
"""
from concurrent.futures import ThreadPoolExecutor

import requests
from django.core.management.base import BaseCommand

from shop.models import Brand

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
}


def check(url):
    if not url:
        return False
    try:
        r = requests.get(url, timeout=12, headers=_HEADERS, stream=True,
                         allow_redirects=True)
        if r.status_code != 200:
            return False
        ct = (r.headers.get('Content-Type') or '').lower()
        if 'image' in ct or 'svg' in ct:
            return True
        # некоторые CDN отдают octet-stream — пробуем по байтам
        chunk = next(r.iter_content(16), b'')
        sig = chunk[:8]
        return (sig.startswith(b'\x89PNG') or sig.startswith(b'\xff\xd8')
                or sig.startswith(b'GIF8') or b'<svg' in chunk.lower())
    except requests.RequestException:
        return False


class Command(BaseCommand):
    help = 'Проверяет logo_url у Brand и очищает битые.'

    def handle(self, *args, **options):
        brands = list(Brand.objects.exclude(logo_url=''))
        self.stdout.write(f'Проверяю {len(brands)} ссылок на лого…')
        results = {}
        with ThreadPoolExecutor(max_workers=12) as pool:
            for b, ok in zip(brands, pool.map(lambda b: check(b.logo_url), brands)):
                results[b.pk] = ok

        bad = [b for b in brands if not results.get(b.pk)]
        self.stdout.write(f'Битых: {len(bad)} из {len(brands)}')
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
