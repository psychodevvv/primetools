"""HTTP-проверяет image_url у Product и убирает битые ссылки.

Запуск:  python manage.py verify_product_images
Опции:   --workers 64
         --only-with-source   (только товары, где есть source_url для возможной
                              перепрошивки картинкой со страницы поставщика)

После очистки битых ссылок такие товары отображаются с плейсхолдером,
а в списках «Хиты продаж» и «Распродажа» они автоматически отфильтровываются
(views исключают image_url='').
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from django.core.management.base import BaseCommand

from shop.models import Product

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}
CHUNK = 500


def _ok(url):
    if not url or not url.lower().startswith(('http://', 'https://')):
        return False
    try:
        r = requests.head(url, timeout=10, headers=_HEADERS, allow_redirects=True)
        if r.status_code == 200:
            ct = (r.headers.get('Content-Type') or '').lower()
            if 'image' in ct or 'svg' in ct or 'octet-stream' in ct:
                return True
            # некоторые CDN не выставляют CT — пробуем GET 1 байт
            rr = requests.get(url, timeout=8, headers=_HEADERS, stream=True)
            chunk = next(rr.iter_content(8), b'')
            sig = chunk[:8]
            return (sig.startswith(b'\x89PNG') or sig.startswith(b'\xff\xd8')
                    or sig.startswith(b'GIF8') or b'<svg' in chunk.lower()
                    or sig[:4] == b'RIFF')
        if r.status_code == 405:    # сервер не любит HEAD
            r2 = requests.get(url, timeout=10, headers=_HEADERS, stream=True)
            return r2.status_code == 200 and 'image' in (
                r2.headers.get('Content-Type') or '').lower()
        return False
    except requests.RequestException:
        return False


class Command(BaseCommand):
    help = 'Удаляет битые image_url у Product (404, тайм-аут, не-картинка).'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=64)
        parser.add_argument('--only-with-source', action='store_true')

    def handle(self, *args, **options):
        workers = max(1, options['workers'])
        qs = Product.objects.exclude(image_url='')
        if options['only_with_source']:
            qs = qs.exclude(source_url='')

        pks = list(qs.values_list('pk', flat=True))
        total = len(pks)
        if not total:
            self.stdout.write('Нет товаров для проверки.')
            return
        self.stdout.write(f'Проверяю {total} товаров в {workers} потоков…')

        processed = bad = 0
        for start in range(0, total, CHUNK):
            batch = list(Product.objects.filter(pk__in=pks[start:start + CHUNK]).only(
                'pk', 'image_url'))
            broken = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(_ok, p.image_url): p for p in batch}
                for f in as_completed(futs):
                    if not f.result():
                        broken.append(futs[f])
            if broken:
                Product.objects.filter(pk__in=[p.pk for p in broken]).update(image_url='')
                bad += len(broken)
            processed += len(batch)
            self.stdout.write(f'  {processed}/{total} — битых найдено: {bad}',
                              ending='\r')

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Готово. Проверено: {processed}, битых очищено: {bad}, '
            f'осталось с фото: {Product.objects.exclude(image_url="").count()}.'))
