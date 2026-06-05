"""Копирует видео-обзоры (video_url) с qaztool в PrimeTools по совпадению артикулов.

Также копирует категорию-лист qaztool: для каждого совпавшего товара
создаёт подкатегорию (по имени листа qaztool) внутри текущей категории
верхнего уровня в PrimeTools и переносит туда товар. Это сохраняет
структуру PrimeTools (16 разделов), но добавляет подробные подкатегории
для товаров, которые есть и у qaztool.

Запуск:
    python manage.py import_qaztool_videos
        --qaztool-db "C:\\Users\\QazTool\\Desktop\\qaztoolsite\\db.sqlite3"
        [--categories]   # переносить и категории-листы тоже
"""
import os
import sqlite3

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from shop.models import Category, Product


DEFAULT_QAZ_DB = r'C:\Users\QazTool\Desktop\qaztoolsite\db.sqlite3'


class Command(BaseCommand):
    help = 'Копирует video_url (и опционально подкатегорию-лист) с qaztool по артикулу.'

    def add_arguments(self, parser):
        parser.add_argument('--qaztool-db', default=DEFAULT_QAZ_DB,
                            help='Путь к файлу qaztool db.sqlite3.')
        parser.add_argument('--categories', action='store_true',
                            help='Переносить и листовые подкатегории qaztool.')
        parser.add_argument('--refresh', action='store_true',
                            help='Перезаписывать уже заданные видео.')

    def handle(self, *args, **options):
        qaz_path = options['qaztool_db']
        if not os.path.exists(qaz_path):
            self.stdout.write(self.style.ERROR(f'Не найден qaztool db: {qaz_path}'))
            return

        do_cats = options['categories']
        refresh = options['refresh']

        con = sqlite3.connect(qaz_path)
        con.row_factory = sqlite3.Row

        self.stdout.write('Читаем qaztool…')
        qaz_cats = {}  # id -> (name, parent_id)
        for r in con.execute('SELECT id, name, parent_id FROM shop_category'):
            qaz_cats[r['id']] = (r['name'], r['parent_id'])

        # Артикул -> (video_url, category_id) для всех qaztool товаров с видео
        # либо со совпадающим артикулом (если категории нужны и есть совпадение).
        qaz_by_article = {}
        rows = con.execute(
            "SELECT article, video_url, category_id FROM shop_product "
            "WHERE article != ''"
        )
        for r in rows:
            art = r['article']
            # Если у нас уже есть запись с видео — не перезатираем без видео.
            existing = qaz_by_article.get(art)
            if existing and existing[0] and not r['video_url']:
                continue
            qaz_by_article[art] = (r['video_url'] or '', r['category_id'])
        con.close()

        self.stdout.write(f'qaztool: {len(qaz_by_article)} артикулов всего, '
                          f'{sum(1 for v in qaz_by_article.values() if v[0])} с видео.')

        # ── Копируем видео ──
        videos_set = 0
        to_update = []
        for p in Product.objects.exclude(article='').only(
                'pk', 'article', 'video_url'
        ).iterator(chunk_size=1000):
            info = qaz_by_article.get(p.article)
            if not info:
                continue
            video, _ = info
            if not video:
                continue
            if p.video_url and not refresh:
                continue
            p.video_url = video
            to_update.append(p)
            if len(to_update) >= 500:
                Product.objects.bulk_update(to_update, ['video_url'])
                videos_set += len(to_update)
                to_update = []
        if to_update:
            Product.objects.bulk_update(to_update, ['video_url'])
            videos_set += len(to_update)

        self.stdout.write(self.style.SUCCESS(
            f'Видео проставлено товарам: {videos_set}.'))

        if not do_cats:
            return

        # ── Подкатегории-листья qaztool ──
        self.stdout.write('Переносим листовые категории qaztool…')

        def qaz_leaf_name(cat_id):
            info = qaz_cats.get(cat_id)
            return info[0].strip() if info else ''

        # Текущая категория-родитель (верхний уровень) товара в PrimeTools.
        def pt_top(category):
            while category and category.parent_id is not None:
                category = Category.objects.filter(pk=category.parent_id).first()
            return category

        sub_cache = {}  # (parent_id, leaf_name) -> Category

        def get_subcategory(parent, leaf_name):
            key = (parent.pk, leaf_name)
            if key in sub_cache:
                return sub_cache[key]
            cat = Category.objects.filter(parent=parent, name=leaf_name[:200]).first()
            if cat is None:
                base = slugify(leaf_name, allow_unicode=True) or 'cat'
                slug, n = base, 2
                while Category.objects.filter(slug=slug).exists():
                    slug = f'{base}-{n}'
                    n += 1
                cat = Category.objects.create(
                    name=leaf_name[:200], slug=slug, parent=parent)
            sub_cache[key] = cat
            return cat

        moved = 0
        batch = []
        for p in Product.objects.exclude(article='').select_related('category').iterator(
                chunk_size=1000):
            info = qaz_by_article.get(p.article)
            if not info:
                continue
            _, qaz_cat_id = info
            leaf = qaz_leaf_name(qaz_cat_id)
            if not leaf:
                continue
            current_top = pt_top(p.category)
            if current_top is None:
                continue
            target = get_subcategory(current_top, leaf)
            if p.category_id == target.pk:
                continue
            p.category_id = target.pk
            batch.append(p)
            if len(batch) >= 500:
                with transaction.atomic():
                    Product.objects.bulk_update(batch, ['category'])
                moved += len(batch)
                batch = []
        if batch:
            with transaction.atomic():
                Product.objects.bulk_update(batch, ['category'])
            moved += len(batch)

        self.stdout.write(self.style.SUCCESS(
            f'Перенесено товаров в qaztool-подкатегории: {moved}.'))
