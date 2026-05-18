from django.conf import settings


def cart_count(request):
    cart = request.session.get('cart', {})
    count = sum(item['quantity'] for item in cart.values())
    return {'cart_count': count}


def contacts(request):
    """Контактные номера из .env — доступны во всех шаблонах."""
    wa = ''.join(c for c in settings.WHATSAPP_NUMBER if c.isdigit())
    return {
        'CALL_NUMBER': settings.CALL_NUMBER,
        'WHATSAPP_NUMBER': wa,
    }


def nav(request):
    """Категории верхнего уровня для меню — на всех страницах."""
    from .models import Category
    return {
        'nav_categories': (
            Category.objects.filter(parent__isnull=True)
            .prefetch_related('children').order_by('order', 'name')
        )
    }
