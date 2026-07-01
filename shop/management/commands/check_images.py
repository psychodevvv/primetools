"""Проверка всех image_url и gallery — битые → удаляем.

Для каждого товара:
  1. HEAD/GET image_url без авторизации (как обычный посетитель сайта).
     Если не 200 image/* — картинка битая.
  2. Если есть gallery — также проверяем каждую ссылку, удаляем битые.
     Если основная битая, но в gallery есть рабочая — продвигаем её в
     image_url, освобождая место в gallery.
  3. Если ни одной рабочей не осталось — удаляем товар (политика «нет
     фото = нет товара» уже принята).

Запуск:
    python manage.py check_images
    python manage.py check_images --workers 16 --limit 100
    python manage.py check_images --dry-run
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from django.core.management.base import BaseCommand
from django.db.models import Q

from shop.models import Product

HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'image/*,*/*;q=0.8'}


def ok(url):
    """True если URL отдаёт картинку публичному посетителю."""
    if not url or not url.startswith(('http://', 'https://')):
        return False
    try:
        r = requests.get(url, timeout=10, allow_redirects=False,
                         headers=HEADERS, stream=True)
    except requests.RequestException:
        return False
    try:
        if r.status_code != 200:
            return False
        ct = (r.headers.get('Content-Type') or '').lower()
        if 'image' not in ct:
            return False
        # дочитываем чуть-чуть и закрываем
        chunk = next(r.iter_content(64), b'')
        if not chunk:
            return False
        return True
    finally:
        r.close()


def verify_product(p):
    """Возвращает dict с новыми image_url, gallery, drop=True если удалять."""
    urls = []
    if p.image_url:
        urls.append(p.image_url)
    if p.gallery:
        urls.extend(u.strip() for u in p.gallery.splitlines() if u.strip())
    # уникальные, сохраняем порядок
    seen = set(); ordered = []
    for u in urls:
        if u in seen: continue
        seen.add(u); ordered.append(u)
    good = [u for u in ordered if ok(u)]
    if not good:
        return {'pk': p.pk, 'drop': True}
    return {
        'pk': p.pk,
        'drop': False,
        'image_url': good[0],
        'gallery': '\n'.join(good[1:]) if len(good) > 1 else '',
    }


class Command(BaseCommand):
    help = 'Проверить публичную доступность всех фото товаров.'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=16)
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        qs = (Product.objects.exclude(Q(image_url='') | Q(image_url__isnull=True))
              .only('pk', 'image_url', 'gallery'))
        if opts['limit']:
            qs = qs[:opts['limit']]
        items = list(qs)
        total = len(items)
        self.stdout.write(f'К проверке: {total} товаров')

        to_drop = []
        to_update = []
        checked = 0
        CHUNK = 200
        for start in range(0, total, CHUNK):
            chunk = items[start:start + CHUNK]
            with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
                futs = {pool.submit(verify_product, p): p for p in chunk}
                for f in as_completed(futs):
                    r = f.result()
                    checked += 1
                    if r['drop']:
                        to_drop.append(r['pk'])
                    elif r['image_url'] != futs[f].image_url or \
                         r['gallery'] != futs[f].gallery:
                        to_update.append(r)
            self.stdout.write(
                f'  {checked}/{total}: drop {len(to_drop)}, fix {len(to_update)}',
                ending='\r')
            time.sleep(0.1)
        self.stdout.write('')

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'DRY: удалили бы {len(to_drop)}, поправили бы {len(to_update)}'))
            return

        # массовое обновление gallery/image_url
        for r in to_update:
            Product.objects.filter(pk=r['pk']).update(
                image_url=r['image_url'], gallery=r['gallery'])
        n_del = 0
        if to_drop:
            n_del = Product.objects.filter(pk__in=to_drop).delete()[0]
        self.stdout.write(self.style.SUCCESS(
            f'Готово. Поправлено: {len(to_update)}, удалено: {n_del}'))
