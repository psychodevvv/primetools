from django.conf import settings


def cart_count(request):
    """Бейдж корзины показывает количество разных товаров (позиций), а не штук."""
    cart = request.session.get('cart', {})
    return {'cart_count': len(cart)}


def contacts(request):
    """Контактные номера из .env — доступны во всех шаблонах."""
    wa = ''.join(c for c in settings.WHATSAPP_NUMBER if c.isdigit())
    return {
        'CALL_NUMBER': settings.CALL_NUMBER,
        'WHATSAPP_NUMBER': wa,
    }


def nav(request):
    """Категории верхнего уровня для меню — на всех страницах.

    Аннотируем количеством товаров (с учётом подкатегорий — берём через
    кеш дерева; для скорости считаем по прямому FK)."""
    from django.db.models import Count
    from .models import Category
    cats = (
        Category.objects.filter(parent__isnull=True)
        .annotate(prod_count=Count('products'))
        .prefetch_related('children')
        .order_by('order', '-prod_count', 'name')
    )
    return {'nav_categories': cats}
