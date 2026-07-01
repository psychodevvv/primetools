"""Скачивание защищённых картинок с mkskz.master.pro в локальный media/.

Причина: MKS отдаёт /dbpics/... только авторизованным сессиям.
Публичный посетитель нашего сайта получает 302 → битая картинка.
Решение: скачиваем всё, что защищено, в media/mks_pics/ и подменяем
image_url + gallery на публичный /media/mks_pics/<id>.<ext>.

Запуск:
    python manage.py download_mks_images --password Qaztool2026
    python manage.py download_mks_images --password XXX --workers 8 --limit 100
"""
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from shop.models import Product
from .fetch_mks_media import login

MKS_PREFIX = 'https://mkskz.master.pro/'
LOCAL_DIR = os.path.join(settings.MEDIA_ROOT, 'mks_pics')


def local_path_for(url):
    """/dbpics/6974954.jpg → media/mks_pics/6974954.jpg"""
    name = os.path.basename(urlparse(url).path)
    return os.path.join(LOCAL_DIR, name)


def local_url_for(url):
    name = os.path.basename(urlparse(url).path)
    return f'{settings.MEDIA_URL}mks_pics/{name}'


def is_public(url):
    """True если картинка отдаётся без auth (200 + image content-type)."""
    try:
        r = requests.get(url, timeout=8, allow_redirects=False,
                         headers={'User-Agent': 'Mozilla/5.0',
                                  'Accept': 'image/*'}, stream=True)
    except requests.RequestException:
        return False
    try:
        if r.status_code != 200:
            return False
        ct = (r.headers.get('Content-Type') or '').lower()
        return 'image' in ct
    finally:
        r.close()


def download(session, url):
    """Скачиваем с auth и сохраняем в media/mks_pics/. Возвращает local url."""
    path = local_path_for(url)
    if os.path.exists(path) and os.path.getsize(path) > 100:
        return local_url_for(url)
    try:
        r = session.get(url, timeout=30, stream=True)
    except requests.RequestException:
        return None
    try:
        if r.status_code != 200:
            return None
        ct = (r.headers.get('Content-Type') or '').lower()
        if 'image' not in ct:
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            for chunk in r.iter_content(64 * 1024):
                if chunk:
                    f.write(chunk)
        return local_url_for(url)
    finally:
        r.close()


def process(session, p):
    """Для одного товара — обновляем image_url + gallery. Возвращаем dict."""
    urls = []
    if p.image_url and p.image_url.startswith(MKS_PREFIX):
        urls.append(p.image_url)
    if p.gallery:
        for u in p.gallery.splitlines():
            u = u.strip()
            if u.startswith(MKS_PREFIX) and u not in urls:
                urls.append(u)
    if not urls:
        return None
    mapped = {}
    for u in urls:
        if is_public(u):
            mapped[u] = u  # публичная — оставляем как есть
        else:
            local = download(session, u)
            if local:
                mapped[u] = local
            # если не скачалось — не пишем, потом отфильтруем
    if not mapped:
        return None
    # собираем новые image_url + gallery в исходном порядке
    def m(u): return mapped.get(u, '')
    new_main = ''
    new_gal = []
    for u in urls:
        v = m(u)
        if not v: continue
        if not new_main:
            new_main = v
        else:
            new_gal.append(v)
    if not new_main:
        return None
    return {'pk': p.pk, 'image_url': new_main,
            'gallery': '\n'.join(new_gal)}


class Command(BaseCommand):
    help = 'Скачать защищённые MKS-картинки в media/ и подменить ссылки.'

    def add_arguments(self, parser):
        parser.add_argument('--login', default='0K00000681')
        parser.add_argument('--password', required=True)
        parser.add_argument('--workers', type=int, default=6)
        parser.add_argument('--limit', type=int, default=0)

    def handle(self, *args, **opts):
        s = login(opts['login'], opts['password'])
        if s is None:
            self.stdout.write(self.style.ERROR('Логин не прошёл.'))
            return
        os.makedirs(LOCAL_DIR, exist_ok=True)

        qs = (Product.objects
              .filter(image_url__startswith=MKS_PREFIX)
              .only('pk', 'image_url', 'gallery'))
        if opts['limit']:
            qs = qs[:opts['limit']]
        items = list(qs)
        total = len(items)
        self.stdout.write(f'К обработке: {total} товаров')

        ok = fail = 0
        checked = 0
        CHUNK = 100
        for start in range(0, total, CHUNK):
            batch = items[start:start + CHUNK]
            updates = []
            with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
                futs = {pool.submit(process, s, p): p for p in batch}
                for f in as_completed(futs):
                    checked += 1
                    r = f.result()
                    if not r:
                        fail += 1
                        continue
                    updates.append(r)
            for r in updates:
                Product.objects.filter(pk=r['pk']).update(
                    image_url=r['image_url'], gallery=r['gallery'])
                ok += 1
            self.stdout.write(
                f'  {checked}/{total}: локально {ok}, без картинки {fail}',
                ending='\r')
            time.sleep(0.15)
        self.stdout.write('')
        # Товары где не удалось ничего сохранить и image_url всё ещё указывает
        # на MKS — не валидны, чистим.
        left_bad = Product.objects.filter(image_url__startswith=MKS_PREFIX)
        n = left_bad.count()
        if n:
            left_bad.update(image_url='', gallery='')
            deleted = Product.objects.filter(image_url='').delete()[0]
            self.stdout.write(f'Удалено {deleted} товаров без валидных фото.')
        self.stdout.write(self.style.SUCCESS(
            f'Готово. Обновлено {ok}, не смогли {fail}.'))
