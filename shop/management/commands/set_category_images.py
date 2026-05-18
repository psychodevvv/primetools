"""Назначает каждой категории фото — берёт картинку подходящего товара.

Запуск:  python manage.py set_category_images
Опции:   --refresh   (перезаписать уже заданные фото категорий)
         --workers N (потоков для проверки ссылок, по умолчанию 24)

Фото проверяется на доступность (битые ссылки поставщиков отбрасываются),
а для родительских разделов берётся картинка из вложенных подкатегорий.
"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests
from django.core.management.base import BaseCommand

from shop.models import Category, Product

_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
MAX_CANDIDATES = 8


def url_ok(url):
    """Проверяет, что по ссылке действительно отдаётся картинка."""
    if not url or not url.lower().startswith(('http://', 'https://')):
        return False
    try:
        r = requests.head(url, timeout=8, headers=_HEADERS, allow_redirects=True)
        if r.status_code == 405:  # сервер не умеет HEAD — пробуем GET
            r = requests.get(url, timeout=8, headers=_HEADERS, stream=True)
        return r.status_code == 200 and 'image' in r.headers.get('Content-Type', '')
    except requests.RequestException:
        return False


class Command(BaseCommand):
    help = 'Назначает категориям фото из товаров (с проверкой ссылок).'

    def add_arguments(self, parser):
        parser.add_argument('--refresh', action='store_true')
        parser.add_argument('--workers', type=int, default=24)

    def handle(self, *args, **options):
        refresh = options['refresh']
        workers = max(1, options['workers'])
        cats = list(Category.objects.all())
        cat_by_id = {c.pk: c for c in cats}
        by_parent = defaultdict(list)
        for c in cats:
            by_parent[c.parent_id].append(c)

        # Товары с фото по категориям.
        direct = defaultdict(list)
        for cat_id, name, url, stock in (Product.objects
                                         .exclude(image_url='')
                                         .values_list('category_id', 'name',
                                                      'image_url', 'in_stock')):
            direct[cat_id].append((name or '', url, stock))

        def candidates(cat_id):
            """Ссылки-кандидаты для категории, лучшие — первыми."""
            items = direct.get(cat_id)
            if not items:
                return []
            cat = cat_by_id.get(cat_id)
            cat_words = set(cat.name.lower().split()) if cat else set()

            def score(item):
                name, _url, stock = item
                overlap = len(cat_words & set(name.lower().split()))
                return (-overlap, 0 if stock else 1, len(name))

            out, seen = [], set()
            for name, url, stock in sorted(items, key=score):
                if url not in seen:
                    seen.add(url)
                    out.append(url)
                if len(out) >= MAX_CANDIDATES:
                    break
            return out

        # Проверяем доступность всех ссылок-кандидатов разом.
        all_urls = set()
        for c in cats:
            all_urls.update(candidates(c.pk))
        self.stdout.write(f'Проверка {len(all_urls)} ссылок на фото…')
        valid = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for url, ok in zip(all_urls, pool.map(url_ok, all_urls)):
                valid[url] = ok

        chosen = {}

        def pick(cat):
            """Рабочее фото категории (рекурсивно по подкатегориям)."""
            if cat.pk in chosen:
                return chosen[cat.pk]
            chosen[cat.pk] = ''  # защита от циклов
            for url in candidates(cat.pk):
                if valid.get(url):
                    chosen[cat.pk] = url
                    return url
            for child in by_parent.get(cat.pk, []):
                u = pick(child)
                if u:
                    chosen[cat.pk] = u
                    return u
            return ''

        updated, to_save = 0, []
        for cat in cats:
            if cat.image_url and not refresh:
                continue
            url = pick(cat)
            if url and url != cat.image_url:
                cat.image_url = url
                to_save.append(cat)
                updated += 1

        # Категории без своих фото наследуют картинку родительского раздела.
        def inherited(cat, depth=0):
            if cat.image_url:
                return cat.image_url
            if depth > 12 or cat.parent_id is None:
                return ''
            parent = cat_by_id.get(cat.parent_id)
            return inherited(parent, depth + 1) if parent else ''

        for cat in cats:
            if not cat.image_url:
                url = inherited(cat)
                if url:
                    cat.image_url = url
                    to_save.append(cat)
                    updated += 1

        Category.objects.bulk_update(to_save, ['image_url'], batch_size=400)
        empty = sum(1 for c in cats if not c.image_url)
        self.stdout.write(self.style.SUCCESS(
            f'Готово. Фото назначено категориям: {updated}. '
            f'Без фото осталось: {empty}.'))
