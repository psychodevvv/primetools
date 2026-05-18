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
    image_url = models.URLField(blank=True)
    gallery = models.TextField(blank=True)  # доп. фото, по одному URL в строке
    source_url = models.URLField(blank=True)
    in_stock = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['name']

    def __str__(self):
        return self.name

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
