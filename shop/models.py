from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    image_url = models.URLField(blank=True)
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='children')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def descendant_ids(self):
        """ID самой категории и всех вложенных подкатегорий."""
        ids = [self.pk]
        for child in self.children.all():
            ids.extend(child.descendant_ids())
        return ids


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=500)
    brand = models.CharField(max_length=200, blank=True)
    article = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    characteristics = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    old_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Цена до скидки. Если задана и больше текущей — товар на распродаже.')
    image_url = models.URLField(blank=True)
    gallery = models.TextField(blank=True)  # доп. фото, по одному URL в строке
    source_url = models.URLField(blank=True)
    video_url = models.URLField(blank=True,
        help_text='Ссылка на видео-обзор (YouTube embed или прямая ссылка на .mp4).')
    video_file = models.FileField(upload_to='product_videos/', blank=True, null=True,
        help_text='Видео-файл (mp4). Используется, если ссылка пустая.')
    video_blocked = models.BooleanField(default=False,
        help_text='True если YouTube/Rutube запретил встраивание (Error 153). '
                  'Такие видео отправляем в конец списка.')
    in_stock = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_on_sale(self):
        return self.old_price is not None and self.old_price > self.price

    @property
    def video_embed(self):
        """URL для встраиваемого <iframe> либо <video>. Пусто, если видео нет."""
        if self.video_file:
            return self.video_file.url
        url = self.video_url or ''
        if not url:
            return ''
        # Любую ссылку YouTube приводим к простому embed-URL — он стабильно играется.
        import re
        m = re.search(r'(?:youtube\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{6,})', url)
        if m:
            return 'https://www.youtube.com/embed/' + m.group(1) + '?rel=0'
        return url

    @property
    def video_kind(self):
        """'youtube', 'video' (для .mp4 и пр.), либо '' если видео нет."""
        if self.video_file:
            return 'video'
        url = (self.video_url or '').lower()
        if not url:
            return ''
        if 'youtube.com' in url or 'youtu.be' in url:
            return 'youtube'
        if 'rutube.ru' in url or 'vk.com/video' in url or 'vimeo' in url:
            return 'youtube'  # все используют iframe-плеер
        return 'video'

    @property
    def discount_percent(self):
        if not self.is_on_sale:
            return 0
        return int(round((float(self.old_price) - float(self.price))
                         / float(self.old_price) * 100))

    def image_list(self):
        """Список всех фото товара (галерея + основное, без дублей)."""
        urls = [u.strip() for u in self.gallery.splitlines() if u.strip()] \
            if self.gallery else []
        if self.image_url and self.image_url not in urls:
            urls.insert(0, self.image_url)
        return urls


class Order(models.Model):
    STATUS_CHOICES = [
        ('new', 'Новый'),
        ('processing', 'В обработке'),
        ('completed', 'Завершён'),
        ('cancelled', 'Отменён'),
    ]

    customer_name = models.CharField(max_length=300)
    customer_phone = models.CharField(max_length=30)
    customer_city = models.CharField(max_length=200, blank=True)
    comment = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'
        ordering = ['-created_at']

    def __str__(self):
        return f'Заказ #{self.pk} — {self.customer_name}'

    def calculate_total(self):
        self.total = sum(item.subtotal() for item in self.items.all())
        self.save()


class Brand(models.Model):
    """Бренд для блока «Бренды» на главной — с логотипом."""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    logo = models.FileField(upload_to='brand_logos/', blank=True, null=True,
        help_text='Файл-логотип (SVG/PNG/JPG). Если задан, перебивает logo_url.')
    logo_url = models.URLField(blank=True,
        help_text='URL логотипа (используется, если файл не загружен).')
    website = models.URLField(blank=True)
    featured = models.BooleanField(default=True,
        help_text='Показывать в слайдере брендов на главной.')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Бренд'
        verbose_name_plural = 'Бренды'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    @property
    def logo_src(self):
        if self.logo:
            return self.logo.url
        return self.logo_url or ''


class VideoReview(models.Model):
    """Видео-обзор для главной страницы. Управляется из админки."""
    title = models.CharField(max_length=200, blank=True,
        help_text='Подпись под видео (необязательно).')
    video_url = models.URLField(blank=True,
        help_text='YouTube / Rutube / VK ссылка на видео.')
    video_file = models.FileField(upload_to='homepage_videos/', blank=True, null=True,
        help_text='Видео-файл (mp4). Используется, если ссылка пустая.')
    thumbnail_url = models.URLField(blank=True,
        help_text='Свой превью-кадр. Если пусто — берётся автоматически для YouTube.')
    order = models.PositiveIntegerField(default=0,
        help_text='Чем меньше — тем выше в ленте.')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Видео-обзор (главная)'
        verbose_name_plural = 'Видео-обзоры (главная)'
        ordering = ['order', '-created_at']

    def __str__(self):
        return self.title or self.video_url[:60] or f'Видео #{self.pk}'

    @property
    def src(self):
        if self.video_file:
            return self.video_file.url
        return self.video_url or ''

    @property
    def kind(self):
        if self.video_file:
            return 'video'
        u = (self.video_url or '').lower()
        if 'youtube' in u or 'youtu.be' in u:
            return 'youtube'
        if 'rutube' in u or 'vk.com/video' in u or 'vimeo' in u:
            return 'iframe'
        return 'video'

    @property
    def youtube_id(self):
        u = self.video_url or ''
        if 'youtube.com/embed/' in u:
            return u.split('/embed/')[1].split('?')[0].split('/')[0]
        if 'youtu.be/' in u:
            return u.split('youtu.be/')[1].split('?')[0].split('/')[0]
        if 'youtube.com/watch?v=' in u:
            return u.split('v=')[1].split('&')[0]
        return ''

    @property
    def thumb(self):
        if self.thumbnail_url:
            return self.thumbnail_url
        yid = self.youtube_id
        if yid:
            return f'https://i.ytimg.com/vi/{yid}/hqdefault.jpg'
        return ''


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=500)
    product_article = models.CharField(max_length=200, blank=True)
    product_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    def subtotal(self):
        return self.product_price * self.quantity

    def __str__(self):
        return f'{self.product_name} x{self.quantity}'
